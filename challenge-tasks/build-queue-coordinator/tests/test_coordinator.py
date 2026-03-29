from coordinator import simulate


def _cfg(**overrides):
    cfg = {
        "max_concurrent": 2,
        "default_timeout_ms": 1000,
        "retry_limit": 2,
        "priority_order": ["critical", "high", "normal", "low"],
        "resource_pools": {"gpu": 2, "cpu": 4},
        "priority_boost_ms": 500,
        "priority_decay_ms": 0,
        "preemption_enabled": False,
    }
    cfg.update(overrides)
    return cfg


def _submit(ts, build_id, priority="normal", dependencies=None, timeout_ms=None, resources=None, preemptible=None):
    ev = {"ts": ts, "kind": "submit", "build_id": build_id, "priority": priority}
    if dependencies is not None:
        ev["dependencies"] = dependencies
    if timeout_ms is not None:
        ev["timeout_ms"] = timeout_ms
    if resources is not None:
        ev["resources"] = resources
    if preemptible is not None:
        ev["preemptible"] = preemptible
    return ev


def _start(ts):
    return {"ts": ts, "kind": "start_next"}


def _complete(ts, build_id):
    return {"ts": ts, "kind": "complete", "build_id": build_id}


def _fail(ts, build_id):
    return {"ts": ts, "kind": "fail", "build_id": build_id}


def _cancel(ts, build_id):
    return {"ts": ts, "kind": "cancel", "build_id": build_id}


def _timeout_check(ts):
    return {"ts": ts, "kind": "timeout_check"}


def test_basic_submit_start_complete():
    """A submitted build can be started and completed."""
    events = [
        _submit(0, "build1"),
        _start(10),
        _complete(100, "build1"),
    ]
    summary = simulate(_cfg(), events)
    assert "build1" in summary.completed
    assert summary.final_states.get("build1") == "completed"


def test_priority_ordering():
    """Higher priority builds are started before lower priority ones."""
    events = [
        _submit(0, "low1", priority="low"),
        _submit(1, "high1", priority="high"),
        _submit(2, "critical1", priority="critical"),
        _start(10),
    ]
    summary = simulate(_cfg(max_concurrent=1), events)
    assert summary.final_states.get("critical1") == "running"
    assert summary.final_states.get("high1") == "pending"


def test_fifo_within_same_priority():
    """Within the same priority level, builds are started in submission order."""
    events = [
        _submit(0, "build1", priority="normal"),
        _submit(1, "build2", priority="normal"),
        _start(10),
    ]
    summary = simulate(_cfg(max_concurrent=1), events)
    assert summary.final_states.get("build1") == "running"
    assert summary.final_states.get("build2") == "pending"


def test_max_concurrent_respected():
    """Cannot start more builds than max_concurrent allows."""
    events = [
        _submit(0, "build1"),
        _submit(1, "build2"),
        _submit(2, "build3"),
        _start(10),
        _start(11),
        _start(12),
    ]
    summary = simulate(_cfg(max_concurrent=2), events)
    assert len(summary.running) == 2
    assert len(summary.pending) == 1


def test_resource_pool_blocks_start():
    """Build cannot start if required resources are not available."""
    events = [
        _submit(0, "gpu_job1", resources={"gpu": 2}),
        _submit(1, "gpu_job2", resources={"gpu": 1}),
        _start(10),
        _start(11),
    ]
    summary = simulate(_cfg(resource_pools={"gpu": 2}), events)
    assert summary.final_states.get("gpu_job1") == "running"
    assert summary.final_states.get("gpu_job2") == "pending"
    assert summary.resource_usage.get("gpu") == 2


def test_resources_released_on_terminal_states():
    """Resources are released when build completes, fails, or is cancelled."""
    events = [
        _submit(0, "job1", resources={"gpu": 2}),
        _submit(1, "job2", resources={"gpu": 1}),
        _start(10),
        _complete(100, "job1"),
        _start(110),
    ]
    summary = simulate(_cfg(resource_pools={"gpu": 2}), events)
    assert summary.final_states.get("job1") == "completed"
    assert summary.final_states.get("job2") == "running"


def test_priority_boost_after_wait():
    """Pending build gets priority boosted after priority_boost_ms elapsed."""
    events = [
        _submit(0, "low_old", priority="low"),
        _submit(1100, "high_new", priority="high"),
        _start(1200),
    ]
    summary = simulate(_cfg(max_concurrent=1, priority_boost_ms=500), events)
    assert summary.final_states.get("low_old") == "running"


def test_priority_boost_caps_at_highest():
    """Priority boost caps at highest level with submission order tiebreaker."""
    events = [
        _submit(0, "low_very_old", priority="low"),
        _submit(2000, "critical_new", priority="critical"),
        _start(2100),
    ]
    summary = simulate(_cfg(max_concurrent=1, priority_boost_ms=500), events)
    assert summary.final_states.get("low_very_old") == "running"


def test_dependency_blocks_until_complete():
    """A build with dependencies cannot start until all dependencies complete."""
    events = [
        _submit(0, "base"),
        _submit(1, "dependent", dependencies=["base"]),
        _start(10),
        _complete(100, "base"),
        _start(110),
    ]
    summary = simulate(_cfg(), events)
    assert "base" in summary.completed
    assert summary.final_states.get("dependent") == "running"


def test_dependency_on_unknown_build():
    """Build depending on unknown build_id stays pending forever."""
    events = [
        _submit(0, "orphan", dependencies=["nonexistent"]),
        _start(10),
    ]
    summary = simulate(_cfg(), events)
    assert summary.final_states.get("orphan") == "pending"


def test_dependent_submitted_before_dependency():
    """A build submitted before its dependency stays pending until dependency completes."""
    events = [
        _submit(0, "child", dependencies=["parent"]),
        _start(10),
        _submit(20, "parent"),
        _start(30),
    ]
    summary = simulate(_cfg(max_concurrent=2), events)
    assert summary.final_states.get("parent") == "running"
    assert summary.final_states.get("child") == "pending"


def test_fail_with_retry():
    """Failed build goes back to pending if retries remain, preserving submit_ts for aging."""
    events = [
        _submit(0, "old_build", priority="low"),
        _start(10),
        _fail(100, "old_build"),
        _submit(1050, "new_build", priority="high"),
        _start(1100),
    ]
    summary = simulate(_cfg(max_concurrent=1, priority_boost_ms=500, retry_limit=2), events)
    assert summary.final_states.get("old_build") == "running"
    assert summary.retry_counts.get("old_build") == 1


def test_fail_exhausts_retries():
    """A build that exhausts all retries becomes permanently failed."""
    events = [
        _submit(0, "build1"),
        _start(10),
        _fail(100, "build1"),
        _start(110),
        _fail(200, "build1"),
        _start(210),
        _fail(300, "build1"),
    ]
    summary = simulate(_cfg(retry_limit=2), events)
    assert "build1" in summary.failed
    assert summary.retry_counts.get("build1") == 2


def test_cancel_propagates_transitively():
    """Cancelling a build also cancels all builds that depend on it transitively."""
    events = [
        _submit(0, "base"),
        _submit(1, "dep1", dependencies=["base"]),
        _submit(2, "dep2", dependencies=["dep1"]),
        _cancel(10, "base"),
    ]
    summary = simulate(_cfg(), events)
    assert all(b in summary.cancelled for b in ["base", "dep1", "dep2"])


def test_failed_dependency_cancels_dependents():
    """A build whose dependency fails permanently becomes cancelled."""
    events = [
        _submit(0, "base"),
        _submit(1, "dependent", dependencies=["base"]),
        _start(10),
        _fail(100, "base"),
        _start(110),
        _fail(200, "base"),
        _start(210),
        _fail(300, "base"),
    ]
    summary = simulate(_cfg(retry_limit=2), events)
    assert "base" in summary.failed
    assert "dependent" in summary.cancelled


def test_timeout_check():
    """Builds exceeding timeout are failed; those within timeout are unaffected."""
    events = [
        _submit(0, "build1", timeout_ms=500),
        _start(10),
        _timeout_check(600),
    ]
    summary = simulate(_cfg(retry_limit=0), events)
    assert "build1" in summary.failed


def test_timeout_can_retry():
    """A build that times out can be retried if retries remain."""
    events = [
        _submit(0, "build1", timeout_ms=100),
        _start(10),
        _timeout_check(200),
        _start(210),
    ]
    summary = simulate(_cfg(retry_limit=2), events)
    assert summary.final_states.get("build1") == "running"
    assert summary.retry_counts.get("build1") == 1


def test_duplicate_build_id_ignored():
    """Submitting the same build_id twice is silently ignored."""
    events = [
        _submit(0, "build1", priority="low"),
        _submit(10, "build1", priority="critical"),
        _start(20),
    ]
    summary = simulate(_cfg(max_concurrent=1), events)
    assert summary.final_states.get("build1") == "running"
    initial_transitions = [t for t in summary.transitions if t.build_id == "build1" and t.from_state is None and t.to_state == "pending"]
    assert len(initial_transitions) == 1


def test_events_on_wrong_state_ignored():
    """Complete/fail on pending builds and events on unknown builds are ignored."""
    events = [
        _submit(0, "build1"),
        _complete(10, "build1"),
        _fail(20, "build1"),
        _complete(30, "unknown"),
    ]
    summary = simulate(_cfg(), events)
    assert summary.final_states.get("build1") == "pending"
    assert "unknown" not in summary.final_states


def test_cancel_terminal_build_no_effect():
    """Cancelling a completed or failed build has no effect."""
    events = [
        _submit(0, "build1"),
        _start(10),
        _complete(100, "build1"),
        _cancel(200, "build1"),
    ]
    summary = simulate(_cfg(), events)
    assert "build1" in summary.completed


def test_transitions_ordered_by_ts():
    """Transitions are ordered by timestamp then processing order."""
    events = [
        _submit(0, "build1"),
        _submit(0, "build2"),
        _start(10),
        _start(10),
    ]
    summary = simulate(_cfg(max_concurrent=2), events)
    timestamps = [t.ts for t in summary.transitions]
    assert timestamps == sorted(timestamps)


def test_custom_priority_order():
    """Custom priority_order is respected."""
    cfg = _cfg(priority_order=["p1", "p2", "p3"], max_concurrent=1)
    events = [
        _submit(0, "build_p3", priority="p3"),
        _submit(1, "build_p1", priority="p1"),
        _start(10),
    ]
    summary = simulate(cfg, events)
    assert summary.final_states.get("build_p1") == "running"


def test_diamond_dependency():
    """Diamond dependency pattern is handled correctly."""
    events = [
        _submit(0, "base"),
        _submit(1, "left", dependencies=["base"]),
        _submit(2, "right", dependencies=["base"]),
        _submit(3, "final", dependencies=["left", "right"]),
        _start(10),
        _complete(100, "base"),
        _start(110),
        _start(111),
        _complete(200, "left"),
        _complete(201, "right"),
        _start(210),
    ]
    summary = simulate(_cfg(max_concurrent=3), events)
    assert summary.final_states.get("final") == "running"


def test_cancel_in_diamond():
    """Cancelling base in diamond pattern cancels all dependents."""
    events = [
        _submit(0, "base"),
        _submit(1, "left", dependencies=["base"]),
        _submit(2, "right", dependencies=["base"]),
        _submit(3, "final", dependencies=["left", "right"]),
        _cancel(10, "base"),
    ]
    summary = simulate(_cfg(), events)
    assert all(b in summary.cancelled for b in ["base", "left", "right", "final"])


def test_priority_decay_running():
    """Running builds lose priority over time based on priority_decay_ms."""
    events = [
        _submit(0, "high_old", priority="high"),
        _start(10),
        _submit(2000, "normal_new", priority="normal"),
        _start(2100),
    ]
    summary = simulate(_cfg(max_concurrent=1, priority_decay_ms=500, preemption_enabled=True), events)
    assert summary.final_states.get("normal_new") == "running"
    assert summary.final_states.get("high_old") == "pending"
    assert summary.preemption_counts.get("high_old") == 1


def test_preemption_basic():
    """Higher priority pending build preempts lower priority running build when enabled."""
    events = [
        _submit(0, "low_job", priority="low"),
        _start(10),
        _submit(100, "critical_job", priority="critical"),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=1, preemption_enabled=True), events)
    assert summary.final_states.get("critical_job") == "running"
    assert summary.final_states.get("low_job") == "pending"
    assert summary.preemption_counts.get("low_job") == 1


def test_preemption_disabled():
    """When preemption_enabled is false, no preemption occurs."""
    events = [
        _submit(0, "low_job", priority="low"),
        _start(10),
        _submit(100, "critical_job", priority="critical"),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=1, preemption_enabled=False), events)
    assert summary.final_states.get("low_job") == "running"
    assert summary.final_states.get("critical_job") == "pending"
    assert "low_job" not in summary.preemption_counts


def test_preemption_requires_strictly_higher():
    """Preemption only occurs when pending has strictly higher effective priority."""
    events = [
        _submit(0, "normal1", priority="normal"),
        _start(10),
        _submit(100, "normal2", priority="normal"),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=1, preemption_enabled=True), events)
    assert summary.final_states.get("normal1") == "running"
    assert summary.final_states.get("normal2") == "pending"


def test_preemption_non_preemptible_build():
    """Builds marked preemptible=false cannot be preempted."""
    events = [
        _submit(0, "low_protected", priority="low", preemptible=False),
        _start(10),
        _submit(100, "critical_job", priority="critical"),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=1, preemption_enabled=True), events)
    assert summary.final_states.get("low_protected") == "running"
    assert summary.final_states.get("critical_job") == "pending"


def test_preemption_releases_resources():
    """Preempted build releases its resources for the preempting build."""
    events = [
        _submit(0, "low_job", priority="low", resources={"gpu": 2}),
        _start(10),
        _submit(100, "critical_job", priority="critical", resources={"gpu": 2}),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=2, preemption_enabled=True, resource_pools={"gpu": 2}), events)
    assert summary.final_states.get("critical_job") == "running"
    assert summary.final_states.get("low_job") == "pending"
    assert summary.resource_usage.get("gpu") == 2


def test_preemption_preserves_submit_ts():
    """Preempted build preserves submit_ts for priority aging."""
    events = [
        _submit(0, "low_job", priority="low"),
        _start(10),
        _submit(100, "critical_job", priority="critical"),
        _start(110),
        _complete(200, "critical_job"),
        _submit(1100, "high_job", priority="high"),
        _start(1200),
    ]
    summary = simulate(_cfg(max_concurrent=1, preemption_enabled=True, priority_boost_ms=500), events)
    assert summary.final_states.get("low_job") == "running"
    assert summary.final_states.get("high_job") == "pending"


def test_preemption_does_not_increment_retry():
    """Preemption does not increment retry count."""
    events = [
        _submit(0, "low_job", priority="low"),
        _start(10),
        _submit(100, "critical_job", priority="critical"),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=1, preemption_enabled=True, retry_limit=2), events)
    assert "low_job" not in summary.retry_counts
    assert summary.preemption_counts.get("low_job") == 1


def test_preemption_with_decay_interaction():
    """Priority decay affects which running build gets preempted - later started build preempted."""
    events = [
        _submit(0, "high_old", priority="high"),
        _submit(1, "normal", priority="normal"),
        _start(10),
        _start(11),
        _submit(2000, "critical", priority="critical"),
        _start(2100),
    ]
    summary = simulate(_cfg(max_concurrent=2, preemption_enabled=True, priority_decay_ms=500), events)
    assert summary.final_states.get("critical") == "running"
    assert summary.final_states.get("high_old") == "running"
    assert summary.preemption_counts.get("normal") == 1


def test_preemption_selects_worst_running():
    """Preemption selects the lowest effective priority running build."""
    events = [
        _submit(0, "critical_job", priority="critical"),
        _submit(1, "low_job", priority="low"),
        _start(10),
        _start(11),
        _submit(100, "high_job", priority="high", resources={"gpu": 1}),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=2, preemption_enabled=True, resource_pools={"gpu": 1}), events)
    assert summary.final_states.get("high_job") == "running"
    assert summary.final_states.get("low_job") == "pending"
    assert summary.final_states.get("critical_job") == "running"


def test_preemption_needs_resource_availability():
    """Preemption only happens if preempting build can actually start after."""
    events = [
        _submit(0, "job1", priority="low", resources={"gpu": 1}),
        _submit(1, "job2", priority="low", resources={"gpu": 1}),
        _start(10),
        _start(11),
        _submit(100, "critical_job", priority="critical", resources={"gpu": 3}),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=3, preemption_enabled=True, resource_pools={"gpu": 2}), events)
    assert summary.final_states.get("job1") == "running"
    assert summary.final_states.get("job2") == "running"
    assert summary.final_states.get("critical_job") == "pending"


def test_priority_decay_caps_at_lowest():
    """Priority decay caps at lowest priority level - same priority means no preemption."""
    events = [
        _submit(0, "critical_job", priority="critical"),
        _start(10),
        _submit(2000, "high_job", priority="high"),
        _start(2100),
    ]
    summary = simulate(_cfg(max_concurrent=1, priority_decay_ms=500, preemption_enabled=True), events)
    assert summary.final_states.get("high_job") == "running"
    assert summary.final_states.get("critical_job") == "pending"
    assert summary.preemption_counts.get("critical_job") == 1


def test_preemption_multiple_times():
    """A build can be preempted multiple times."""
    events = [
        _submit(0, "low_job", priority="low"),
        _start(10),
        _submit(100, "high_job", priority="high"),
        _start(110),
        _complete(200, "high_job"),
        _start(210),
        _submit(300, "critical_job", priority="critical"),
        _start(310),
    ]
    summary = simulate(_cfg(max_concurrent=1, preemption_enabled=True), events)
    assert summary.preemption_counts.get("low_job") == 2


def test_preemption_count_only_for_preempted():
    """preemption_counts only includes builds that were actually preempted."""
    events = [
        _submit(0, "build1", priority="critical"),
        _submit(1, "build2", priority="low"),
        _start(10),
        _complete(100, "build1"),
        _start(110),
        _complete(200, "build2"),
    ]
    summary = simulate(_cfg(preemption_enabled=True), events)
    assert "build1" not in summary.preemption_counts
    assert "build2" not in summary.preemption_counts


def test_boost_and_decay_combined():
    """Priority boost for pending and decay for running work together."""
    events = [
        _submit(0, "normal_running", priority="normal"),
        _start(10),
        _submit(100, "low_pending", priority="low"),
        _start(2100),
    ]
    summary = simulate(_cfg(max_concurrent=1, priority_boost_ms=500, priority_decay_ms=500, preemption_enabled=True), events)
    assert summary.final_states.get("low_pending") == "running"
    assert summary.final_states.get("normal_running") == "pending"


def test_resource_pool_zero_or_undefined():
    """Build requiring resource from zero-capacity or undefined pool cannot start."""
    events = [
        _submit(0, "job1", resources={"gpu": 1}),
        _start(10),
    ]
    summary = simulate(_cfg(resource_pools={"gpu": 0}), events)
    assert summary.final_states.get("job1") == "pending"


def test_cancel_mid_dependency_chain():
    """Cancelling middle of dependency chain cancels dependents but not ancestors."""
    events = [
        _submit(0, "base"),
        _submit(1, "mid", dependencies=["base"]),
        _submit(2, "final", dependencies=["mid"]),
        _start(10),
        _complete(100, "base"),
        _cancel(110, "mid"),
    ]
    summary = simulate(_cfg(), events)
    assert "base" in summary.completed
    assert "mid" in summary.cancelled
    assert "final" in summary.cancelled


def test_start_next_respects_all_constraints():
    """start_next only picks builds with resources, dependencies, and priority satisfied."""
    events = [
        _submit(0, "dep"),
        _submit(1, "needs_dep", dependencies=["dep"]),
        _submit(2, "needs_resource", resources={"gpu": 3}),
        _submit(3, "can_run"),
        _start(10),
        _start(11),
    ]
    summary = simulate(_cfg(resource_pools={"gpu": 2}, max_concurrent=4), events)
    assert summary.final_states.get("dep") == "running"
    assert summary.final_states.get("can_run") == "running"
    assert summary.final_states.get("needs_dep") == "pending"
    assert summary.final_states.get("needs_resource") == "pending"


def test_preemption_with_dependencies():
    """Preemption respects dependency constraints for the preempting build."""
    events = [
        _submit(0, "base"),
        _submit(1, "low_job", priority="low"),
        _start(10),
        _start(11),
        _submit(100, "critical_dep", priority="critical", dependencies=["base"]),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=2, preemption_enabled=True), events)
    assert summary.final_states.get("base") == "running"
    assert summary.final_states.get("low_job") == "running"
    assert summary.final_states.get("critical_dep") == "pending"


def test_preemption_running_order_tiebreaker():
    """When multiple running builds have same priority, preempt the one started last."""
    events = [
        _submit(0, "job1", priority="normal"),
        _submit(1, "job2", priority="normal"),
        _start(10),
        _start(11),
        _submit(100, "critical", priority="critical"),
        _start(110),
    ]
    summary = simulate(_cfg(max_concurrent=2, preemption_enabled=True), events)
    assert summary.final_states.get("job2") == "pending"
    assert summary.final_states.get("job1") == "running"
    assert summary.preemption_counts.get("job2") == 1
