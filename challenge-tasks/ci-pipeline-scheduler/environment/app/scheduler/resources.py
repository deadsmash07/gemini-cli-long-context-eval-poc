from typing import Dict


class ResourcePool:
    """Manages resource pool allocations for builds."""

    def __init__(self, pools: Dict[str, int]):
        self._capacity = dict(pools)
        self._usage = {p: 0 for p in pools}

    def can_acquire(self, resources: Dict[str, int]) -> bool:
        """Check if resources can be acquired."""
        for pool, need in resources.items():
            if pool not in self._capacity:
                return False
            if self._usage[pool] + need > self._capacity[pool]:
                return False
        return True

    def acquire(self, resources: Dict[str, int]) -> None:
        """Acquire resources for a build."""
        for pool, need in resources.items():
            self._usage[pool] += need

    def release(self, resources: Dict[str, int]) -> None:
        """Release resources back to the pool."""
        for pool, need in resources.items():
            self._usage[pool] -= need

    def get_usage(self) -> Dict[str, int]:
        """Get current resource usage."""
        return dict(self._usage)
