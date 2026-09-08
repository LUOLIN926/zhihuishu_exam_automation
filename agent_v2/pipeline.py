from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import MemoryDecision
from .policy import MemoryPolicy
from .storage import MemoryManager


@dataclass(frozen=True)
class QuestionInput:
    course_name: str
    question_type: str
    question_text: str
    options: list[Any]
    exam_name: str | None = None
    exam_url: str | None = None
    deadline_text: str | None = None
    question_number: int | None = None


@dataclass(frozen=True)
class AnswerResult:
    answer: Any
    answer_text: str | None
    model_name: str | None = None
    rag_max_score: float | None = None
    evidence: list[dict[str, Any]] | None = None
    action_status: str = "answered"


class MemoryAwareAnswerPipeline:
    """Memory facade used by the future V2 browser-answering flow."""

    def __init__(
        self,
        memory: MemoryManager | None = None,
        policy: MemoryPolicy | None = None,
    ) -> None:
        self.memory = memory or MemoryManager()
        self.policy = policy or MemoryPolicy()

    def prepare(self, question: QuestionInput) -> tuple[int, int | None, MemoryDecision, str]:
        course_id = self.memory.get_or_create_course(question.course_name)
        exam_id = None
        if question.exam_name or question.exam_url:
            exam_id = self.memory.get_or_create_exam(
                course_id=course_id,
                exam_name=question.exam_name,
                exam_url=question.exam_url,
                deadline_text=question.deadline_text,
            )

        match = self.memory.search_question(
            course_id=course_id,
            question_type=question.question_type,
            question_text=question.question_text,
            options=question.options,
        )
        decision = self.policy.decide(match)
        context = self.memory.build_memory_context(match) if decision.should_reference and match else ""
        return course_id, exam_id, decision, context

    def commit(
        self,
        question: QuestionInput,
        result: AnswerResult,
        course_id: int,
        exam_id: int | None = None,
        memory_match_score: float | None = None,
    ) -> int:
        memory_id = self.memory.upsert_question_memory(
            course_id=course_id,
            question_type=question.question_type,
            question_text=question.question_text,
            options=question.options,
            answer=result.answer,
            answer_text=result.answer_text,
            confidence=0.55,
            source="model",
            verified_status="unverified",
            evidence=result.evidence,
        )
        self.memory.record_attempt(
            question_memory_id=memory_id,
            exam_id=exam_id,
            question_number=question.question_number,
            model_name=result.model_name,
            rag_max_score=result.rag_max_score,
            memory_match_score=memory_match_score,
            answer=result.answer,
            action_status=result.action_status,
        )
        return memory_id
