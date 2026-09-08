from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizedQuestion:
    question_type: str
    question_text: str
    normalized_question: str
    options: list[dict[str, Any]]
    option_signature: str
    question_fingerprint: str
    tokens: set[str]


@dataclass(frozen=True)
class MemoryMatch:
    question_memory_id: int
    course_id: int
    question_type: str
    question_text: str
    normalized_question: str
    options: list[dict[str, Any]]
    canonical_answer: Any
    answer_text: str | None
    confidence: float
    source: str
    verified_status: str
    match_score: float
    evidence: list[dict[str, Any]]


@dataclass(frozen=True)
class MemoryDecision:
    action: str
    reason: str
    match: MemoryMatch | None = None

    @property
    def should_reuse(self) -> bool:
        return self.action == "reuse"

    @property
    def should_reference(self) -> bool:
        return self.action == "reference"
