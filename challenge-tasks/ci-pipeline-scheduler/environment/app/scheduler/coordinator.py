from typing import Any, Dict, List

from .build import Build
from .priority import PriorityCalculator
from .resources import ResourcePool
from .dependencies import DependencyTracker


def simulate(config: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Simulate a CI build queue with the given configuration and events."""
    max_concurrent = config["max_concurrent"]
    default_timeout = config["default_timeout_ms"]
    _retry_limit = config["retry_limit"]  # noqa: F841
    priority_order = config["priority_order"]
    resource_pools = config["resource_pools"]
    priority_boost_ms = config["priority_boost_ms"]
    priority_decay_ms = config["priority_decay_ms"]
    _preemption_enabled = config["preemption_enabled"]  # noqa: F841

    _priority_calc = PriorityCalculator(priority_order, priority_boost_ms, priority_decay_ms)  # noqa: F841
    resources = ResourcePool(resource_pools)
    deps = DependencyTracker()

    builds: Dict[str, Build] = {}
    transitions: List[Dict[str, Any]] = []

    def get_eligible_pending(ts: int) -> List[str]:
        """Get pending builds sorted by effective priority."""
        eligible = []
        for bid, b in builds.items():
            if b.state != "pending":
                continue
            if not deps.deps_satisfied(bid):
                continue
            eligible.append(bid)

        eligible.sort(key=lambda x: builds[x].submit_ts)
        return eligible

    def get_running_count() -> int:
        return sum(1 for b in builds.values() if b.state == "running")

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

            can_start = resources.can_acquire(b.resources)
            under_max = get_running_count() < max_concurrent

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
            b.state = "failed"
            deps.update_state(bid, "failed")
            transitions.append({"ts": ts, "build_id": bid, "to": "failed"})

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

        elif kind == "timeout_check":
            for bid, b in builds.items():
                if b.state == "running":
                    if ts >= b.start_ts + b.timeout_ms:
                        resources.release(b.resources)
                        b.state = "failed"
                        deps.update_state(bid, "failed")
                        transitions.append({"ts": ts, "build_id": bid, "to": "failed"})

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
