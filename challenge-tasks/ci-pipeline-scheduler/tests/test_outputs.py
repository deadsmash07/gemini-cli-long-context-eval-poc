from scheduler import simulate


def base_config():
    """Returns a standard test configuration."""
    return {
        "max_concurrent": 2,
        "default_timeout_ms": 5000,
        "retry_limit": 2,
        "priority_order": ["critical", "high", "normal", "low"],
        "resource_pools": {"cpu": 4, "gpu": 2},
        "priority_boost_ms": 1000,
        "priority_decay_ms": 2000,
        "preemption_enabled": True,
    }


def get_transitions_for_build(result, build_id):
    """Extract all transitions for a specific build."""
    return [t for t in result["transitions"] if t["build_id"] == build_id]


def test_submit_creates_pending_build():
    """Submitting a build creates it in pending state with transition recorded."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "pending"
    assert "b1" in result["pending"]
    transitions = get_transitions_for_build(result, "b1")
    assert len(transitions) == 1
    assert transitions[0]["to"] == "pending"


def test_start_next_runs_pending_build():
    """start_next transitions eligible pending build to running with transition recorded."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "running"
    assert "b1" in result["running"]
    transitions = get_transitions_for_build(result, "b1")
    assert len(transitions) == 2
    assert transitions[0]["to"] == "pending"
    assert transitions[1]["to"] == "running"


def test_complete_marks_build_completed():
    """complete event marks running build as completed with transition recorded."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "complete", "build_id": "b1"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "completed"
    assert "b1" in result["completed"]
    transitions = get_transitions_for_build(result, "b1")
    assert len(transitions) == 3
    assert transitions[2]["to"] == "completed"


def test_priority_order_respected():
    """Higher priority build starts before lower priority even when submitted later."""
    config = base_config()
    config["max_concurrent"] = 1
    events = [
        {"ts": 0, "kind": "submit", "build_id": "low1", "priority": "low"},
        {"ts": 1, "kind": "submit", "build_id": "high1", "priority": "high"},
        {"ts": 2, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["high1"] == "running"
    assert result["final_states"]["low1"] == "pending"
    high_transitions = get_transitions_for_build(result, "high1")
    assert any(t["to"] == "running" for t in high_transitions)
    low_transitions = get_transitions_for_build(result, "low1")
    assert not any(t["to"] == "running" for t in low_transitions)


def test_priority_order_same_submit_time():
    """Higher priority wins even with identical submission times."""
    config = base_config()
    config["max_concurrent"] = 1
    events = [
        {"ts": 0, "kind": "submit", "build_id": "low1", "priority": "low"},
        {"ts": 0, "kind": "submit", "build_id": "high1", "priority": "high"},
        {"ts": 1, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["high1"] == "running"
    assert result["final_states"]["low1"] == "pending"


def test_dependency_blocks_start():
    """Build with incomplete dependency cannot start even with higher priority."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "dep", "priority": "normal"},
        {"ts": 1, "kind": "submit", "build_id": "child", "priority": "high", "dependencies": ["dep"]},
        {"ts": 2, "kind": "start_next"},
        {"ts": 3, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["dep"] == "running"
    assert result["final_states"]["child"] == "pending"
    child_transitions = get_transitions_for_build(result, "child")
    assert not any(t["to"] == "running" for t in child_transitions)


def test_dependency_satisfied_allows_start():
    """Build starts after dependency completes."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "dep", "priority": "normal"},
        {"ts": 1, "kind": "submit", "build_id": "child", "priority": "normal", "dependencies": ["dep"]},
        {"ts": 2, "kind": "start_next"},
        {"ts": 3, "kind": "complete", "build_id": "dep"},
        {"ts": 4, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["dep"] == "completed"
    assert result["final_states"]["child"] == "running"
    child_transitions = get_transitions_for_build(result, "child")
    running_trans = [t for t in child_transitions if t["to"] == "running"]
    assert len(running_trans) == 1
    assert running_trans[0]["ts"] == 4


def test_resource_pool_limits_start():
    """Build cannot start if resources unavailable."""
    config = base_config()
    config["resource_pools"] = {"gpu": 1}
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal", "resources": {"gpu": 1}},
        {"ts": 1, "kind": "submit", "build_id": "b2", "priority": "normal", "resources": {"gpu": 1}},
        {"ts": 2, "kind": "start_next"},
        {"ts": 3, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "running"
    assert result["final_states"]["b2"] == "pending"
    assert result["resource_usage"]["gpu"] == 1
    b2_transitions = get_transitions_for_build(result, "b2")
    assert not any(t["to"] == "running" for t in b2_transitions)


def test_resources_released_on_complete():
    """Resources return to pool when build completes allowing next build to start."""
    config = base_config()
    config["resource_pools"] = {"gpu": 1}
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal", "resources": {"gpu": 1}},
        {"ts": 1, "kind": "submit", "build_id": "b2", "priority": "normal", "resources": {"gpu": 1}},
        {"ts": 2, "kind": "start_next"},
        {"ts": 3, "kind": "complete", "build_id": "b1"},
        {"ts": 4, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "completed"
    assert result["final_states"]["b2"] == "running"
    b2_transitions = get_transitions_for_build(result, "b2")
    running_trans = [t for t in b2_transitions if t["to"] == "running"]
    assert len(running_trans) == 1


def test_fail_with_retry_goes_pending():
    """Failed build with retries remaining transitions to pending with retry count incremented."""
    config = base_config()
    config["retry_limit"] = 2
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "fail", "build_id": "b1"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "pending"
    assert "b1" in result["retry_counts"]
    assert result["retry_counts"]["b1"] == 1
    transitions = get_transitions_for_build(result, "b1")
    states = [t["to"] for t in transitions]
    assert states == ["pending", "running", "pending"]


def test_fail_exceeds_retry_limit():
    """Build fails permanently after exhausting retries with transitions recorded."""
    config = base_config()
    config["retry_limit"] = 1
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "fail", "build_id": "b1"},
        {"ts": 3, "kind": "start_next"},
        {"ts": 4, "kind": "fail", "build_id": "b1"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "failed"
    assert "b1" in result["retry_counts"]
    assert result["retry_counts"]["b1"] == 1
    transitions = get_transitions_for_build(result, "b1")
    states = [t["to"] for t in transitions]
    assert states == ["pending", "running", "pending", "running", "failed"]


def test_cancel_cancels_build():
    """cancel event cancels pending build with transition recorded."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "cancel", "build_id": "b1"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "cancelled"
    assert "b1" in result["cancelled"]
    transitions = get_transitions_for_build(result, "b1")
    states = [t["to"] for t in transitions]
    assert states == ["pending", "cancelled"]


def test_cancel_releases_resources():
    """Cancelling running build releases its resources."""
    config = base_config()
    config["resource_pools"] = {"gpu": 1}
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal", "resources": {"gpu": 1}},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "cancel", "build_id": "b1"},
    ]
    result = simulate(config, events)
    assert result["resource_usage"]["gpu"] == 0
    assert result["final_states"]["b1"] == "cancelled"


def test_cancel_propagates_to_dependents():
    """Cancelling build cancels all transitive dependents with transitions recorded."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "root", "priority": "normal"},
        {"ts": 1, "kind": "submit", "build_id": "child", "priority": "normal", "dependencies": ["root"]},
        {"ts": 2, "kind": "submit", "build_id": "grandchild", "priority": "normal", "dependencies": ["child"]},
        {"ts": 3, "kind": "cancel", "build_id": "root"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["root"] == "cancelled"
    assert result["final_states"]["child"] == "cancelled"
    assert result["final_states"]["grandchild"] == "cancelled"
    for build_id in ["root", "child", "grandchild"]:
        transitions = get_transitions_for_build(result, build_id)
        assert any(t["to"] == "cancelled" for t in transitions)
    child_cancel = [t for t in get_transitions_for_build(result, "child") if t["to"] == "cancelled"]
    assert len(child_cancel) == 1
    grandchild_cancel = [t for t in get_transitions_for_build(result, "grandchild") if t["to"] == "cancelled"]
    assert len(grandchild_cancel) == 1


def test_failed_dependency_cancels_dependents():
    """Builds depending on failed build get cancelled with transitions."""
    config = base_config()
    config["retry_limit"] = 0
    events = [
        {"ts": 0, "kind": "submit", "build_id": "dep", "priority": "normal"},
        {"ts": 1, "kind": "submit", "build_id": "child", "priority": "normal", "dependencies": ["dep"]},
        {"ts": 2, "kind": "start_next"},
        {"ts": 3, "kind": "fail", "build_id": "dep"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["dep"] == "failed"
    assert result["final_states"]["child"] == "cancelled"
    dep_transitions = get_transitions_for_build(result, "dep")
    assert any(t["to"] == "failed" for t in dep_transitions)
    child_transitions = get_transitions_for_build(result, "child")
    assert any(t["to"] == "cancelled" for t in child_transitions)


def test_timeout_check_fails_expired_builds():
    """timeout_check fails builds past their timeout with transition."""
    config = base_config()
    config["default_timeout_ms"] = 100
    config["retry_limit"] = 0
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 200, "kind": "timeout_check"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "failed"
    transitions = get_transitions_for_build(result, "b1")
    assert any(t["to"] == "failed" and t["ts"] == 200 for t in transitions)


def test_custom_timeout_respected():
    """Build uses its own timeout_ms if specified."""
    config = base_config()
    config["default_timeout_ms"] = 1000
    config["retry_limit"] = 0
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal", "timeout_ms": 50},
        {"ts": 1, "kind": "start_next"},
        {"ts": 100, "kind": "timeout_check"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "failed"


def test_max_concurrent_respected():
    """Cannot exceed max_concurrent running builds."""
    config = base_config()
    config["max_concurrent"] = 1
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "submit", "build_id": "b2", "priority": "normal"},
        {"ts": 2, "kind": "start_next"},
        {"ts": 3, "kind": "start_next"},
    ]
    result = simulate(config, events)
    running = [b for b in ["b1", "b2"] if result["final_states"][b] == "running"]
    pending = [b for b in ["b1", "b2"] if result["final_states"][b] == "pending"]
    assert len(running) == 1
    assert len(pending) == 1


def test_priority_boost_aging():
    """Pending builds gain effective priority over time allowing old low to beat new high."""
    config = base_config()
    config["max_concurrent"] = 1
    config["priority_boost_ms"] = 100
    events_no_aging = [
        {"ts": 0, "kind": "submit", "build_id": "old_low", "priority": "low"},
        {"ts": 50, "kind": "submit", "build_id": "new_high", "priority": "high"},
        {"ts": 100, "kind": "start_next"},
    ]
    result_no_aging = simulate(config, events_no_aging)
    assert result_no_aging["final_states"]["new_high"] == "running", "Without sufficient aging, high must beat low"
    assert result_no_aging["final_states"]["old_low"] == "pending", "Without sufficient aging, high must beat low"

    events_with_aging = [
        {"ts": 0, "kind": "submit", "build_id": "old_low2", "priority": "low"},
        {"ts": 500, "kind": "submit", "build_id": "new_high2", "priority": "high"},
        {"ts": 600, "kind": "start_next"},
    ]
    result_with_aging = simulate(config, events_with_aging)
    assert result_with_aging["final_states"]["old_low2"] == "running"
    assert result_with_aging["final_states"]["new_high2"] == "pending"
    old_transitions = get_transitions_for_build(result_with_aging, "old_low2")
    assert any(t["to"] == "running" and t["ts"] == 600 for t in old_transitions)


def test_priority_boost_insufficient_time():
    """Without enough time, priority boost doesn't overcome priority difference."""
    config = base_config()
    config["max_concurrent"] = 1
    config["priority_boost_ms"] = 100
    events = [
        {"ts": 0, "kind": "submit", "build_id": "old_low", "priority": "low"},
        {"ts": 50, "kind": "submit", "build_id": "new_high", "priority": "high"},
        {"ts": 100, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["new_high"] == "running"
    assert result["final_states"]["old_low"] == "pending"


def test_priority_boost_capped():
    """Priority boost cannot exceed highest priority level."""
    config = base_config()
    config["max_concurrent"] = 1
    config["priority_boost_ms"] = 10
    events = [
        {"ts": 0, "kind": "submit", "build_id": "critical1", "priority": "critical"},
        {"ts": 1, "kind": "submit", "build_id": "low1", "priority": "low"},
        {"ts": 1000, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["critical1"] == "running"
    assert result["final_states"]["low1"] == "pending"


def test_priority_boost_capped_low_submitted_first():
    """When low submitted first and both reach critical, low wins via tie-breaker."""
    config = base_config()
    config["max_concurrent"] = 1
    config["priority_boost_ms"] = 10
    events_short = [
        {"ts": 0, "kind": "submit", "build_id": "low1", "priority": "low"},
        {"ts": 1, "kind": "submit", "build_id": "critical1", "priority": "critical"},
        {"ts": 20, "kind": "start_next"},
    ]
    result_short = simulate(config, events_short)
    assert result_short["final_states"]["critical1"] == "running", "With only 20ms boost, critical still beats low"
    assert result_short["final_states"]["low1"] == "pending"

    events_long = [
        {"ts": 0, "kind": "submit", "build_id": "low2", "priority": "low"},
        {"ts": 1, "kind": "submit", "build_id": "critical2", "priority": "critical"},
        {"ts": 1000, "kind": "start_next"},
    ]
    result_long = simulate(config, events_long)
    assert result_long["final_states"]["low2"] == "running", "With 1000ms boost, low reaches critical and wins via submit_ts"
    assert result_long["final_states"]["critical2"] == "pending"


def test_preemption_basic():
    """Higher priority pending build preempts lower priority running build with transitions."""
    config = base_config()
    config["max_concurrent"] = 1
    config["preemption_enabled"] = True
    events = [
        {"ts": 0, "kind": "submit", "build_id": "low1", "priority": "low"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "submit", "build_id": "critical1", "priority": "critical"},
        {"ts": 3, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["critical1"] == "running"
    assert result["final_states"]["low1"] == "pending"
    assert "low1" in result["preemption_counts"]
    assert result["preemption_counts"]["low1"] == 1
    low_transitions = get_transitions_for_build(result, "low1")
    states = [t["to"] for t in low_transitions]
    assert states == ["pending", "running", "pending"]
    critical_transitions = get_transitions_for_build(result, "critical1")
    assert any(t["to"] == "running" and t["ts"] == 3 for t in critical_transitions)


def test_preemption_disabled():
    """Preemption does not occur when preemption_enabled is false."""
    config = base_config()
    config["max_concurrent"] = 1
    config["preemption_enabled"] = True
    events_enabled = [
        {"ts": 0, "kind": "submit", "build_id": "low1", "priority": "low"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "submit", "build_id": "critical1", "priority": "critical"},
        {"ts": 3, "kind": "start_next"},
    ]
    result_enabled = simulate(config, events_enabled)
    assert result_enabled["final_states"]["critical1"] == "running", "Preemption must work when enabled"
    assert result_enabled["final_states"]["low1"] == "pending", "Preemption must work when enabled"

    config["preemption_enabled"] = False
    events_disabled = [
        {"ts": 0, "kind": "submit", "build_id": "low2", "priority": "low"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "submit", "build_id": "critical2", "priority": "critical"},
        {"ts": 3, "kind": "start_next"},
    ]
    result_disabled = simulate(config, events_disabled)
    assert result_disabled["final_states"]["low2"] == "running"
    assert result_disabled["final_states"]["critical2"] == "pending"
    assert "low2" not in result_disabled.get("preemption_counts", {})


def test_non_preemptible_build():
    """Builds marked preemptible=false cannot be preempted."""
    config = base_config()
    config["max_concurrent"] = 1
    config["preemption_enabled"] = True
    events_preemptible = [
        {"ts": 0, "kind": "submit", "build_id": "low1", "priority": "low", "preemptible": True},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "submit", "build_id": "critical1", "priority": "critical"},
        {"ts": 3, "kind": "start_next"},
    ]
    result_preemptible = simulate(config, events_preemptible)
    assert result_preemptible["final_states"]["critical1"] == "running", "Preemption must work for preemptible builds"
    assert result_preemptible["final_states"]["low1"] == "pending", "Preemption must work for preemptible builds"

    events_non = [
        {"ts": 0, "kind": "submit", "build_id": "low2", "priority": "low", "preemptible": False},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "submit", "build_id": "critical2", "priority": "critical"},
        {"ts": 3, "kind": "start_next"},
    ]
    result_non = simulate(config, events_non)
    assert result_non["final_states"]["low2"] == "running"
    assert result_non["final_states"]["critical2"] == "pending"
    assert "low2" not in result_non.get("preemption_counts", {})


def test_preempted_build_preserves_submit_ts():
    """Preempted build keeps original submit_ts for aging calculation."""
    config = base_config()
    config["max_concurrent"] = 1
    config["priority_boost_ms"] = 100
    events = [
        {"ts": 0, "kind": "submit", "build_id": "low1", "priority": "low"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "submit", "build_id": "critical1", "priority": "critical"},
        {"ts": 3, "kind": "start_next"},
        {"ts": 4, "kind": "complete", "build_id": "critical1"},
        {"ts": 5, "kind": "submit", "build_id": "normal1", "priority": "normal"},
        {"ts": 600, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["low1"] == "running"
    assert "low1" in result["preemption_counts"]


def test_duplicate_build_id_ignored():
    """Submitting same build_id twice is ignored with only one transition."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "submit", "build_id": "b1", "priority": "critical"},
    ]
    result = simulate(config, events)
    transitions = get_transitions_for_build(result, "b1")
    pending_transitions = [t for t in transitions if t["to"] == "pending"]
    assert len(pending_transitions) == 1


def test_unknown_build_id_ignored():
    """Events referencing unknown build_id are ignored with no transitions."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "complete", "build_id": "unknown"},
        {"ts": 1, "kind": "fail", "build_id": "unknown"},
        {"ts": 2, "kind": "cancel", "build_id": "unknown"},
    ]
    result = simulate(config, events)
    assert result["final_states"] == {}
    assert result["transitions"] == []


def test_complete_non_running_ignored():
    """complete event on non-running build is ignored."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "complete", "build_id": "b1"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "pending"
    transitions = get_transitions_for_build(result, "b1")
    assert not any(t["to"] == "completed" for t in transitions)


def test_fail_non_running_ignored():
    """fail event on non-running build is ignored."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "fail", "build_id": "b1"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "pending"
    transitions = get_transitions_for_build(result, "b1")
    assert len(transitions) == 1


def test_transitions_ordered_by_timestamp():
    """Transitions are ordered by timestamp then processing order."""
    config = base_config()
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 0, "kind": "submit", "build_id": "b2", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
    ]
    result = simulate(config, events)
    timestamps = [t["ts"] for t in result["transitions"]]
    assert timestamps == sorted(timestamps)
    assert len(result["transitions"]) >= 3


def test_submission_order_tiebreaker():
    """Same effective priority uses submission order."""
    config = base_config()
    config["max_concurrent"] = 1
    events = [
        {"ts": 0, "kind": "submit", "build_id": "first", "priority": "normal"},
        {"ts": 1, "kind": "submit", "build_id": "second", "priority": "normal"},
        {"ts": 2, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["first"] == "running"
    assert result["final_states"]["second"] == "pending"


def test_priority_decay_for_running():
    """Running builds lose effective priority over time allowing preemption."""
    config = base_config()
    config["max_concurrent"] = 1
    config["priority_decay_ms"] = 100
    config["preemption_enabled"] = True
    events = [
        {"ts": 0, "kind": "submit", "build_id": "high1", "priority": "high"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 500, "kind": "submit", "build_id": "normal1", "priority": "normal"},
        {"ts": 600, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["normal1"] == "running"
    assert result["final_states"]["high1"] == "pending"
    assert "high1" in result["preemption_counts"]
    assert result["preemption_counts"]["high1"] == 1
    high_transitions = get_transitions_for_build(result, "high1")
    states = [t["to"] for t in high_transitions]
    assert states == ["pending", "running", "pending"]


def test_retry_preserves_submit_ts():
    """Retried build keeps original submit_ts for aging calculation."""
    config = base_config()
    config["max_concurrent"] = 1
    config["priority_boost_ms"] = 100
    config["retry_limit"] = 1
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "low"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "fail", "build_id": "b1"},
        {"ts": 3, "kind": "submit", "build_id": "b2", "priority": "normal"},
        {"ts": 600, "kind": "start_next"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "running"
    assert "b1" in result["retry_counts"]
    b1_transitions = get_transitions_for_build(result, "b1")
    states = [t["to"] for t in b1_transitions]
    assert "pending" in states and "running" in states


def test_preemption_requires_strictly_higher_priority():
    """Preemption only occurs when pending has strictly higher effective priority."""
    config = base_config()
    config["max_concurrent"] = 1
    config["preemption_enabled"] = True
    events_diff = [
        {"ts": 0, "kind": "submit", "build_id": "low1", "priority": "low"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "submit", "build_id": "high1", "priority": "high"},
        {"ts": 3, "kind": "start_next"},
    ]
    result_diff = simulate(config, events_diff)
    assert result_diff["final_states"]["high1"] == "running", "Preemption must occur for different priorities"
    assert result_diff["final_states"]["low1"] == "pending", "Preemption must occur for different priorities"

    events_same = [
        {"ts": 0, "kind": "submit", "build_id": "normal1", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "submit", "build_id": "normal2", "priority": "normal"},
        {"ts": 3, "kind": "start_next"},
    ]
    result_same = simulate(config, events_same)
    assert result_same["final_states"]["normal1"] == "running"
    assert result_same["final_states"]["normal2"] == "pending"
    assert "normal1" not in result_same.get("preemption_counts", {})


def test_multiple_retries_increment_count():
    """Multiple failures increment retry count correctly."""
    config = base_config()
    config["retry_limit"] = 3
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 2, "kind": "fail", "build_id": "b1"},
        {"ts": 3, "kind": "start_next"},
        {"ts": 4, "kind": "fail", "build_id": "b1"},
        {"ts": 5, "kind": "start_next"},
        {"ts": 6, "kind": "complete", "build_id": "b1"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "completed"
    assert result["retry_counts"]["b1"] == 2


def test_timeout_with_retry():
    """Timed out build retries if within retry limit."""
    config = base_config()
    config["default_timeout_ms"] = 100
    config["retry_limit"] = 2
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 200, "kind": "timeout_check"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "pending"
    assert result["retry_counts"]["b1"] == 1
    transitions = get_transitions_for_build(result, "b1")
    states = [t["to"] for t in transitions]
    assert states == ["pending", "running", "pending"]


def test_timeout_exceeds_retry_limit():
    """Build fails permanently after exhausting retries via timeout."""
    config = base_config()
    config["default_timeout_ms"] = 100
    config["retry_limit"] = 1
    events = [
        {"ts": 0, "kind": "submit", "build_id": "b1", "priority": "normal"},
        {"ts": 1, "kind": "start_next"},
        {"ts": 200, "kind": "timeout_check"},
        {"ts": 201, "kind": "start_next"},
        {"ts": 400, "kind": "timeout_check"},
    ]
    result = simulate(config, events)
    assert result["final_states"]["b1"] == "failed"
    assert result["retry_counts"]["b1"] == 1
    transitions = get_transitions_for_build(result, "b1")
    states = [t["to"] for t in transitions]
    assert states == ["pending", "running", "pending", "running", "failed"]
