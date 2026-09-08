from __future__ import annotations

import os

from .models import MemoryDecision, MemoryMatch


class MemoryPolicy:
    """Decide whether a memory hit should be reused, referenced, or ignored."""

    def __init__(
        self,
        reuse_threshold: float | None = None,
        reference_threshold: float | None = None,
    ) -> None:
        self.reuse_threshold = reuse_threshold if reuse_threshold is not None else float(
            os.getenv("MEMORY_REUSE_THRESHOLD", "0.92")
        )
        self.reference_threshold = reference_threshold if reference_threshold is not None else float(
            os.getenv("MEMORY_REFERENCE_THRESHOLD", "0.70")
        )

    def decide(self, match: MemoryMatch | None) -> MemoryDecision:
        if match is None:
            return MemoryDecision(action="ignore", reason="no memory match")

        is_confirmed = match.verified_status == "confirmed"
        can_reuse = (
            match.match_score >= self.reuse_threshold
            and (match.confidence >= self.reuse_threshold or is_confirmed)
        )
        if can_reuse:
            return MemoryDecision(
                action="reuse",
                reason=(
                    f"match_score={match.match_score:.2f}, "
                    f"confidence={match.confidence:.2f}, status={match.verified_status}"
                ),
                match=match,
            )

        if match.match_score >= self.reference_threshold:
            return MemoryDecision(
                action="reference",
                reason=f"similar historical question, match_score={match.match_score:.2f}",
                match=match,
            )

        return MemoryDecision(
            action="ignore",
            reason=f"memory match below threshold, match_score={match.match_score:.2f}",
            match=match,
        )
