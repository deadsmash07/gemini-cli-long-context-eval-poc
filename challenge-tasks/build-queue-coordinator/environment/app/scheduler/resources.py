from typing import Dict


class ResourcePool:
    """Manages resource pool allocations for builds."""

    def __init__(self, pools: Dict[str, int]):
        self._capacity = dict(pools)
        self._usage = {p: 0 for p in pools}

    def can_acquire(self, resources: Dict[str, int]) -> bool:
        """Check if resources can be acquired."""
        for pool, need in resources.items():
            capacity = self._capacity.get(pool, 0)
            if self._usage.get(pool, 0) + need > capacity:
                return False
        return True

    def can_acquire_with_release(
        self, resources: Dict[str, int], release: Dict[str, int]
    ) -> bool:
        """Check if resources can be acquired after releasing some."""
        for pool, need in resources.items():
            capacity = self._capacity.get(pool, 0)
            current = self._usage.get(pool, 0)
            released = release.get(pool, 0)
            if current - released + need > capacity:
                return False
        return True

    def acquire(self, resources: Dict[str, int]) -> None:
        """Acquire resources for a build."""
        for pool, need in resources.items():
            if pool not in self._usage:
                self._usage[pool] = 0
            self._usage[pool] += need

    def release(self, resources: Dict[str, int]) -> None:
        """Release resources back to the pool."""
        for pool, need in resources.items():
            if pool in self._usage:
                self._usage[pool] = max(0, self._usage[pool] - need)

    def get_usage(self) -> Dict[str, int]:
        """Get current resource usage."""
        return dict(self._usage)
