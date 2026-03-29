from typing import Any, Dict, List, Optional

from models import Summary, Transition
from scheduler import PriorityCalculator, ResourcePool, DependencyTracker, Build


class BuildQueueCoordinator:
    """
    Manages CI/CD build jobs with priorities, dependencies, retries,
    timeouts, resource pools, and cancellation propagation.
    """

    def __init__(self, config: Dict[str, Any]):
        self.max_concurrent = config.get("max_concurrent", 2)
        self.default_timeout_ms = config.get("default_timeout_ms", 1000)
        self.retry_limit = config.get("retry_limit", 2)
        self.priority_order = config.get("priority_order", ["critical", "high", "normal", "low"])
        self.preemption_enabled = config.get("preemption_enabled", False)

        self._priority_calc = PriorityCalculator(
            self.priority_order,
            config.get("priority_boost_ms", 500),
            config.get("priority_decay_ms", 0),
        )
        self._resources = ResourcePool(config.get("resource_pools", {}))
        self._deps = DependencyTracker()

        self._builds: Dict[str, Build] = {}
        self._transitions: List[Transition] = []
        self._submit_order = 0
        self._start_order = 0

    def _record(
        self, ts: int, build_id: str, from_state: Optional[str], to_state: str, note: str
    ) -> None:
        self._transitions.append(
            Transition(ts=ts, build_id=build_id, from_state=from_state, to_state=to_state, note=note)
        )

    def _running_count(self) -> int:
        return sum(1 for b in self._builds.values() if b.state == "running")

    def _get_effective_priority_pending(self, build: Build, ts: int) -> int:
        return self._priority_calc.get_effective_rank_pending(build.priority, build.submit_ts, ts)

    def _get_effective_priority_running(self, build: Build, ts: int) -> int:
        return self._priority_calc.get_effective_rank_running(build.priority, build.start_ts or ts, ts)

    def _find_best_pending(self, ts: int) -> Optional[str]:
        """Find the highest priority eligible pending build."""
        candidates = []
        for bid, build in self._builds.items():
            if build.state != "pending":
                continue
            if not self._deps.deps_satisfied(bid):
                continue
            if not self._resources.can_acquire(build.resources):
                continue
            eff_priority = self._get_effective_priority_pending(build, ts)
            candidates.append((eff_priority, build.submit_order, bid))

        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def apply_event(self, event: Dict[str, Any]) -> None:
        ts = event["ts"]
        kind = event["kind"]

        if kind == "submit":
            build_id = event["build_id"]
            if build_id in self._builds:
                return
            build = Build.from_event(event, self.default_timeout_ms, self._submit_order)
            self._builds[build_id] = build
            self._deps.register_build(build_id, build.dependencies)
            self._deps.update_state(build_id, "pending")
            self._submit_order += 1
            self._record(ts, build_id, None, "pending", "submit")

        elif kind == "start_next":
            best_id = self._find_best_pending(ts)
            if not best_id:
                return
            if self._running_count() >= self.max_concurrent:
                return

            build = self._builds[best_id]
            if not self._resources.can_acquire(build.resources):
                return

            build.state = "running"
            build.start_ts = ts
            build.start_order = self._start_order
            self._start_order += 1
            self._resources.acquire(build.resources)
            self._deps.update_state(best_id, "running")
            self._record(ts, best_id, "pending", "running", "start")

        elif kind == "complete":
            build_id = event["build_id"]
            build = self._builds.get(build_id)
            if not build or build.state != "running":
                return
            self._resources.release(build.resources)
            build.state = "completed"
            self._deps.update_state(build_id, "completed")
            self._record(ts, build_id, "running", "completed", "complete")

        elif kind == "fail":
            build_id = event["build_id"]
            build = self._builds.get(build_id)
            if not build or build.state != "running":
                return
            self._resources.release(build.resources)
            build.state = "failed"
            self._deps.update_state(build_id, "failed")
            self._record(ts, build_id, "running", "failed", "fail")

        elif kind == "cancel":
            build_id = event["build_id"]
            build = self._builds.get(build_id)
            if not build:
                return
            if build.state in ("completed", "failed", "cancelled"):
                return
            old_state = build.state
            if old_state == "running":
                self._resources.release(build.resources)
            build.state = "cancelled"
            self._deps.update_state(build_id, "cancelled")
            self._record(ts, build_id, old_state, "cancelled", "cancel")

        elif kind == "timeout_check":
            for bid, build in list(self._builds.items()):
                if build.state != "running":
                    continue
                if ts >= (build.start_ts or 0) + build.timeout_ms:
                    self._resources.release(build.resources)
                    build.state = "failed"
                    self._deps.update_state(bid, "failed")
                    self._record(ts, bid, "running", "failed", "timeout")

    def result(self) -> Summary:
        completed = []
        failed = []
        cancelled = []
        pending = []
        running = []
        final_states = {}
        retry_counts = {}
        preemption_counts = {}

        for bid, build in self._builds.items():
            final_states[bid] = build.state
            if build.state == "completed":
                completed.append(bid)
            elif build.state == "failed":
                failed.append(bid)
            elif build.state == "cancelled":
                cancelled.append(bid)
            elif build.state == "pending":
                pending.append(bid)
            elif build.state == "running":
                running.append(bid)
            if build.retry_count > 0:
                retry_counts[bid] = build.retry_count
            if build.preemption_count > 0:
                preemption_counts[bid] = build.preemption_count

        sorted_transitions = sorted(
            self._transitions, key=lambda t: (t.ts, self._transitions.index(t))
        )

        return Summary(
            transitions=sorted_transitions,
            final_states=final_states,
            completed=completed,
            failed=failed,
            cancelled=cancelled,
            pending=pending,
            running=running,
            retry_counts=retry_counts,
            preemption_counts=preemption_counts,
            resource_usage=self._resources.get_usage(),
        )


def simulate(config: Dict[str, Any], events: List[Dict[str, Any]]) -> Summary:
    coordinator = BuildQueueCoordinator(config)
    for ev in events:
        coordinator.apply_event(ev)
    return coordinator.result()
