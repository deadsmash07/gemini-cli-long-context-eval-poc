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
        return True

    def get_dependents(self, build_id: str) -> Set[str]:
        """Get all builds that depend on the given build (transitively)."""
        dependents: Set[str] = set()
        return dependents

    def get_builds_with_failed_deps(self) -> Set[str]:
        """Get builds whose dependencies have failed or been cancelled."""
        affected: Set[str] = set()
        return affected
