#!/bin/bash

cat > /app/scheduler/priority.py << 'EOF'
from typing import List


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
        elapsed = current_ts - submit_ts
        boost_levels = elapsed // self._boost_ms if self._boost_ms > 0 else 0
        effective_rank = max(self._highest_rank, base_rank - boost_levels)
        return effective_rank

    def get_effective_rank_running(
        self, priority: str, start_ts: int, current_ts: int
    ) -> int:
        """Calculate effective priority rank for a running build with decay."""
        base_rank = self.get_base_rank(priority)
        elapsed = current_ts - start_ts
        decay_levels = elapsed // self._decay_ms if self._decay_ms > 0 else 0
        effective_rank = min(self._lowest_rank, base_rank + decay_levels)
        return effective_rank

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
            if dep_id not in self._build_states:
                return False
            if self._build_states[dep_id] != "completed":
                return False
        return True

    def get_dependents(self, build_id: str) -> Set[str]:
        """Get all builds that depend on the given build (transitively)."""
        dependents: Set[str] = set()
        changed = True
        while changed:
            changed = False
            for bid, deps in self._build_deps.items():
                if bid in dependents:
                    continue
                for dep_id in deps:
                    if dep_id == build_id or dep_id in dependents:
                        dependents.add(bid)
                        changed = True
                        break
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

cat > /app/scheduler/coordinator.py << 'EOF'
from typing import Any, Dict, List

from .build import Build
from .priority import PriorityCalculator
from .resources import ResourcePool
from .dependencies import DependencyTracker


def simulate(config: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Simulate a CI build queue with the given configuration and events."""
    max_concurrent = config["max_concurrent"]
    default_timeout = config["default_timeout_ms"]
    retry_limit = config["retry_limit"]
    priority_order = config["priority_order"]
    resource_pools = config["resource_pools"]
    priority_boost_ms = config["priority_boost_ms"]
    priority_decay_ms = config["priority_decay_ms"]
    preemption_enabled = config["preemption_enabled"]

    priority_calc = PriorityCalculator(priority_order, priority_boost_ms, priority_decay_ms)
    resources = ResourcePool(resource_pools)
    deps = DependencyTracker()

    builds: Dict[str, Build] = {}
    transitions: List[Dict[str, Any]] = []

    def get_effective_priority_pending(bid: str, ts: int) -> int:
        b = builds[bid]
        return priority_calc.get_effective_rank_pending(b.priority, b.submit_ts, ts)

    def get_effective_priority_running(bid: str, ts: int) -> int:
        b = builds[bid]
        return priority_calc.get_effective_rank_running(b.priority, b.start_ts, ts)

    def get_eligible_pending(ts: int) -> List[str]:
        """Get pending builds sorted by effective priority."""
        eligible = []
        for bid, b in builds.items():
            if b.state != "pending":
                continue
            if not deps.deps_satisfied(bid):
                continue
            eligible.append(bid)

        eligible.sort(key=lambda x: (get_effective_priority_pending(x, ts), builds[x].submit_ts))
        return eligible

    def get_preemptible_running(ts: int) -> List[str]:
        """Get running preemptible builds sorted by lowest effective priority."""
        preemptible = []
        for bid, b in builds.items():
            if b.state != "running":
                continue
            if not b.preemptible:
                continue
            preemptible.append(bid)
        preemptible.sort(key=lambda x: (-get_effective_priority_running(x, ts), -builds[x].start_ts))
        return preemptible

    def get_running_count() -> int:
        return sum(1 for b in builds.values() if b.state == "running")

    def cancel_dependents(cancelled_id: str, ts: int) -> None:
        """Cancel all builds that depend on the cancelled/failed build."""
        to_cancel = deps.get_dependents(cancelled_id)
        for bid in to_cancel:
            b = builds[bid]
            if b.state in ("completed", "failed", "cancelled"):
                continue
            if b.state == "running":
                resources.release(b.resources)
            b.state = "cancelled"
            deps.update_state(bid, "cancelled")
            transitions.append({"ts": ts, "build_id": bid, "to": "cancelled"})

    for event in events:
        ts = event["ts"]
        kind = event["kind"]

        if kind == "submit":
            bid = event["build_id"]
            if bid in builds:
                continue
            build = Build.from_event(event, default_timeout)
            builds[bid] = build
            deps.register_build(bid, build.dependencies)
            deps.update_state(bid, "pending")
            transitions.append({"ts": ts, "build_id": bid, "to": "pending"})

        elif kind == "start_next":
            eligible = get_eligible_pending(ts)
            if not eligible:
                continue

            chosen = eligible[0]
            b = builds[chosen]

            running_count = get_running_count()
            can_start = resources.can_acquire(b.resources)
            under_max = running_count < max_concurrent

            if preemption_enabled and eligible:
                chosen_eff_rank = get_effective_priority_pending(chosen, ts)
                preemptible = get_preemptible_running(ts)

                if preemptible:
                    worst_running = preemptible[0]
                    worst_eff_rank = get_effective_priority_running(worst_running, ts)

                    if chosen_eff_rank < worst_eff_rank:
                        wb = builds[worst_running]
                        resources.release(wb.resources)
                        wb.state = "pending"
                        wb.preemption_count += 1
                        wb.start_ts = None
                        deps.update_state(worst_running, "pending")
                        transitions.append({"ts": ts, "build_id": worst_running, "to": "pending"})
                        running_count -= 1
                        can_start = resources.can_acquire(b.resources)
                        under_max = running_count < max_concurrent

            if can_start and under_max:
                b.state = "running"
                b.start_ts = ts
                resources.acquire(b.resources)
                deps.update_state(chosen, "running")
                transitions.append({"ts": ts, "build_id": chosen, "to": "running"})

        elif kind == "complete":
            bid = event["build_id"]
            if bid not in builds:
                continue
            b = builds[bid]
            if b.state != "running":
                continue
            resources.release(b.resources)
            b.state = "completed"
            deps.update_state(bid, "completed")
            transitions.append({"ts": ts, "build_id": bid, "to": "completed"})

        elif kind == "fail":
            bid = event["build_id"]
            if bid not in builds:
                continue
            b = builds[bid]
            if b.state != "running":
                continue
            resources.release(b.resources)

            if b.retry_count < retry_limit:
                b.retry_count += 1
                b.state = "pending"
                b.start_ts = None
                deps.update_state(bid, "pending")
                transitions.append({"ts": ts, "build_id": bid, "to": "pending"})
            else:
                b.state = "failed"
                deps.update_state(bid, "failed")
                transitions.append({"ts": ts, "build_id": bid, "to": "failed"})
                cancel_dependents(bid, ts)

        elif kind == "cancel":
            bid = event["build_id"]
            if bid not in builds:
                continue
            b = builds[bid]
            if b.state in ("completed", "failed", "cancelled"):
                continue
            if b.state == "running":
                resources.release(b.resources)
            b.state = "cancelled"
            deps.update_state(bid, "cancelled")
            transitions.append({"ts": ts, "build_id": bid, "to": "cancelled"})
            cancel_dependents(bid, ts)

        elif kind == "timeout_check":
            timed_out = []
            for bid, b in builds.items():
                if b.state == "running":
                    if ts >= b.start_ts + b.timeout_ms:
                        timed_out.append(bid)
            for bid in timed_out:
                b = builds[bid]
                resources.release(b.resources)
                if b.retry_count < retry_limit:
                    b.retry_count += 1
                    b.state = "pending"
                    b.start_ts = None
                    deps.update_state(bid, "pending")
                    transitions.append({"ts": ts, "build_id": bid, "to": "pending"})
                else:
                    b.state = "failed"
                    deps.update_state(bid, "failed")
                    transitions.append({"ts": ts, "build_id": bid, "to": "failed"})
                    cancel_dependents(bid, ts)

    final_states = {bid: b.state for bid, b in builds.items()}
    completed = [bid for bid, b in builds.items() if b.state == "completed"]
    failed = [bid for bid, b in builds.items() if b.state == "failed"]
    cancelled = [bid for bid, b in builds.items() if b.state == "cancelled"]
    pending = [bid for bid, b in builds.items() if b.state == "pending"]
    running = [bid for bid, b in builds.items() if b.state == "running"]
    retry_counts = {bid: b.retry_count for bid, b in builds.items() if b.retry_count > 0}
    preemption_counts = {bid: b.preemption_count for bid, b in builds.items() if b.preemption_count > 0}

    return {
        "transitions": transitions,
        "final_states": final_states,
        "completed": completed,
        "failed": failed,
        "cancelled": cancelled,
        "pending": pending,
        "running": running,
        "retry_counts": retry_counts,
        "preemption_counts": preemption_counts,
        "resource_usage": resources.get_usage(),
    }
EOF
