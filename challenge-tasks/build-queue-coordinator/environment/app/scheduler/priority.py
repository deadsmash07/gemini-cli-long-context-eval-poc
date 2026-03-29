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
        """Calculate effective priority rank for a pending build."""
        base_rank = self.get_base_rank(priority)
        return base_rank

    def get_effective_rank_running(
        self, priority: str, start_ts: int, current_ts: int
    ) -> int:
        """Calculate effective priority rank for a running build."""
        base_rank = self.get_base_rank(priority)
        return base_rank

    @property
    def highest_rank(self) -> int:
        return self._highest_rank

    @property
    def lowest_rank(self) -> int:
        return self._lowest_rank
