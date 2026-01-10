"""Usage tracking for Claude Code API costs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UsageTracker:
    """Tracks Claude Code API usage costs across phases."""

    phase1_cost: float = field(default=0.0)
    phase3_cost: float = field(default=0.0)

    def add_phase1_usage(self, cost_usd: float) -> None:
        """Add cost from Phase 1 (deep analysis).

        Args:
            cost_usd: Cost in USD to add
        """
        self.phase1_cost += cost_usd

    def add_phase3_usage(self, cost_usd: float) -> None:
        """Add cost from Phase 3 (fix application).

        Args:
            cost_usd: Cost in USD to add
        """
        self.phase3_cost += cost_usd

    def get_phase1_total(self) -> float:
        """Get total Phase 1 cost.

        Returns:
            Total cost in USD for Phase 1
        """
        return self.phase1_cost

    def get_phase3_total(self) -> float:
        """Get total Phase 3 cost.

        Returns:
            Total cost in USD for Phase 3
        """
        return self.phase3_cost

    def get_total(self) -> float:
        """Get total cost across all phases.

        Returns:
            Total cost in USD
        """
        return self.phase1_cost + self.phase3_cost

    def reset(self) -> None:
        """Reset all usage tracking."""
        self.phase1_cost = 0.0
        self.phase3_cost = 0.0
