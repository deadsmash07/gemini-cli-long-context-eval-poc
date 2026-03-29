#!/bin/bash

cat > /app/scheduler/priority.py << 'EOF'
from typing import Dict, List


class PriorityCalculator:
    """Calculates effective priority for builds with boost and decay."""

    def __init__(
        self,
        priority_order: List[str],
        priority_boost_ms: int,
        priority_decay_ms: int,
    ):
        self._priority_order = priority_order
        self._priority_rank = {p: i for i, p in enumerate(priority_order)}
        self._boost_ms = priority_boost_ms
        self._decay_ms = priority_decay_ms
        self._highest_rank = 0
        self._lowest_rank = len(priority_order) - 1

    def get_base_rank(self, priority: str) -> int:
        """Get the base rank for a priority level."""
        return self._priority_rank.get(priority, self._lowest_rank)

    def get_effective_rank_pending(
        self, priority: str, submit_ts: int, current_ts: int
    ) -> int:
        """Calculate effective priority rank for a pending build with aging boost."""
        base_rank = self.get_base_rank(priority)
        if self._boost_ms <= 0:
            return base_rank
        elapsed = current_ts - submit_ts
        boost_levels = elapsed // self._boost_ms
        return max(self._highest_rank, base_rank - boost_levels)

    def get_effective_rank_running(
        self, priority: str, start_ts: int, current_ts: int
    ) -> int:
        """Calculate effective priority rank for a running build with decay."""
        base_rank = self.get_base_rank(priority)
        if self._decay_ms <= 0:
            return base_rank
        elapsed = current_ts - start_ts
        decay_levels = elapsed // self._decay_ms
        return min(self._lowest_rank, base_rank + decay_levels)

    @property
    def highest_rank(self) -> int:
        return self._highest_rank

    @property
    def lowest_rank(self) -> int:
        return self._lowest_rank
EOF

cat > /app/scheduler/dependencies.py << 'EOF'
from typing import Dict, List, Set


class DependencyTracker:
    """Tracks build dependencies and determines eligibility."""

    def __init__(self):
        self._build_states: Dict[str, str] = {}
        self._build_deps: Dict[str, List[str]] = {}

    def register_build(self, build_id: str, dependencies: List[str]) -> None:
        """Register a build and its dependencies."""
        self._build_deps[build_id] = dependencies

    def update_state(self, build_id: str, state: str) -> None:
        """Update the state of a build."""
        self._build_states[build_id] = state

    def deps_satisfied(self, build_id: str) -> bool:
        """Check if all dependencies are satisfied (completed)."""
        deps = self._build_deps.get(build_id, [])
        for dep_id in deps:
            dep_state = self._build_states.get(dep_id)
            if dep_state != "completed":
                return False
        return True

    def get_dependents(self, build_id: str) -> Set[str]:
        """Get all builds that depend on the given build (transitively)."""
        dependents: Set[str] = set()
        to_check = [build_id]
        while to_check:
            current = to_check.pop()
            for bid, deps in self._build_deps.items():
                if bid in dependents:
                    continue
                if current in deps:
                    dependents.add(bid)
                    to_check.append(bid)
        return dependents

    def get_builds_with_failed_deps(self) -> Set[str]:
        """Get builds whose dependencies have failed or been cancelled."""
        affected: Set[str] = set()
        changed = True
        while changed:
            changed = False
            for bid, deps in self._build_deps.items():
                if bid in affected:
                    continue
                state = self._build_states.get(bid, "pending")
                if state in ("completed", "failed", "cancelled"):
                    continue
                for dep_id in deps:
                    dep_state = self._build_states.get(dep_id, "pending")
                    if dep_state in ("failed", "cancelled") or dep_id in affected:
                        affected.add(bid)
                        changed = True
                        break
        return affected
EOF

cat > /app/coordinator.py << 'EOF'
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

    def _find_best_pending(self, ts: int, extra_resources: Dict[str, int] = None) -> Optional[str]:
        """Find the highest priority eligible pending build."""
        candidates = []
        for bid, build in self._builds.items():
            if build.state != "pending":
                continue
            if not self._deps.deps_satisfied(bid):
                continue
            if extra_resources:
                if not self._resources.can_acquire_with_release(build.resources, extra_resources):
                    continue
            else:
                if not self._resources.can_acquire(build.resources):
                    continue
            eff_priority = self._get_effective_priority_pending(build, ts)
            candidates.append((eff_priority, build.submit_order, bid))

        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _find_worst_preemptible_running(self, ts: int) -> Optional[str]:
        """Find the lowest effective priority preemptible running build."""
        candidates = []
        for bid, build in self._builds.items():
            if build.state != "running":
                continue
            if not build.preemptible:
                continue
            eff_priority = self._get_effective_priority_running(build, ts)
            candidates.append((eff_priority, build.start_order or 0, bid))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][2]

    def _cancel_build_and_dependents(self, ts: int, build_id: str) -> None:
        """Cancel a build and all its transitive dependents."""
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

        for dep_id in self._deps.get_dependents(build_id):
            dep = self._builds.get(dep_id)
            if dep and dep.state not in ("completed", "failed", "cancelled"):
                old = dep.state
                if old == "running":
                    self._resources.release(dep.resources)
                dep.state = "cancelled"
                self._deps.update_state(dep_id, "cancelled")
                self._record(ts, dep_id, old, "cancelled", "dependency_cancelled")

    def _check_dependency_failures(self, ts: int) -> None:
        """Cancel builds whose dependencies have failed."""
        for bid in self._deps.get_builds_with_failed_deps():
            build = self._builds.get(bid)
            if build and build.state == "pending":
                build.state = "cancelled"
                self._deps.update_state(bid, "cancelled")
                self._record(ts, bid, "pending", "cancelled", "dependency_failed")

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

            if self.preemption_enabled:
                worst_running_id = self._find_worst_preemptible_running(ts)
                if worst_running_id:
                    worst_running = self._builds[worst_running_id]
                    running_resources = worst_running.resources

                    preempt_candidate_id = self._find_best_pending(ts, running_resources) if not best_id else best_id

                    if preempt_candidate_id:
                        preempt_candidate = self._builds[preempt_candidate_id]
                        preempt_priority = self._get_effective_priority_pending(preempt_candidate, ts)
                        worst_priority = self._get_effective_priority_running(worst_running, ts)

                        if preempt_priority < worst_priority:
                            can_start_now = self._resources.can_acquire(preempt_candidate.resources)
                            need_preempt = (self._running_count() >= self.max_concurrent) or not can_start_now

                            if need_preempt:
                                self._resources.release(running_resources)
                                worst_running.state = "pending"
                                worst_running.preemption_count += 1
                                worst_running.start_ts = None
                                worst_running.start_order = None
                                self._deps.update_state(worst_running_id, "pending")
                                self._record(ts, worst_running_id, "running", "pending", "preempted")
                                best_id = preempt_candidate_id

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

            if build.retry_count < self.retry_limit:
                build.retry_count += 1
                build.state = "pending"
                build.start_ts = None
                build.start_order = None
                self._deps.update_state(build_id, "pending")
                self._record(ts, build_id, "running", "pending", "retry")
            else:
                build.state = "failed"
                self._deps.update_state(build_id, "failed")
                self._record(ts, build_id, "running", "failed", "fail")
                self._check_dependency_failures(ts)

        elif kind == "cancel":
            build_id = event["build_id"]
            self._cancel_build_and_dependents(ts, build_id)

        elif kind == "timeout_check":
            timed_out = []
            for bid, build in self._builds.items():
                if build.state != "running":
                    continue
                if ts >= (build.start_ts or 0) + build.timeout_ms:
                    timed_out.append(bid)

            for bid in timed_out:
                build = self._builds[bid]
                self._resources.release(build.resources)

                if build.retry_count < self.retry_limit:
                    build.retry_count += 1
                    build.state = "pending"
                    build.start_ts = None
                    build.start_order = None
                    self._deps.update_state(bid, "pending")
                    self._record(ts, bid, "running", "pending", "timeout_retry")
                else:
                    build.state = "failed"
                    self._deps.update_state(bid, "failed")
                    self._record(ts, bid, "running", "failed", "timeout")
                    self._check_dependency_failures(ts)

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
EOF
