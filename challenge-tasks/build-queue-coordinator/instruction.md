build queue coordinator in /app/ is broken. simulate(config, events) runs but doesnt handle most logic correctly. code is split across coordinator.py and scheduler/ modules

config has max_concurrent (int), default_timeout_ms (int), retry_limit (int), priority_order (list highest to lowest), resource_pools (dict pool to capacity), priority_boost_ms (int for pending aging), priority_decay_ms (int for running decay), preemption_enabled (bool)

events have ts and kind. submit has build_id, priority, optional dependencies/timeout_ms/resources/preemptible. start_next starts highest effective priority eligible pending build, preempting lowest priority running preemptible if needed. complete/fail mark builds done releasing resources. fail retries if under retry_limit. cancel cancels build plus all transitive dependents. timeout_check fails expired running builds

build states: pending running completed failed cancelled. eligible means pending with deps completed and resources available. effective priority for pending uses boost aging from submit, for running uses decay from start, both capped at priority bounds. same priority uses submit order for pending, start order for running. failed/cancelled deps cascade to cancel dependents

bugs are spread across modules: priority.py doesnt calculate boost/decay. dependencies.py doesnt check deps or track dependents. coordinator.py doesnt do preemption or retry logic or cancel propagation

Summary has transitions (list by ts then order), final_states dict, completed/failed/cancelled/pending/running lists, retry_counts and preemption_counts dicts (only for builds with counts > 0), resource_usage dict
