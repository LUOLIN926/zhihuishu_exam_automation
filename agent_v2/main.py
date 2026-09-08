from __future__ import annotations

import json

from .pipeline import AnswerResult, MemoryAwareAnswerPipeline, QuestionInput


def demo() -> None:
    """Smoke-test the V2 memory layer without touching the existing browser automation."""
    pipeline = MemoryAwareAnswerPipeline()
    question = QuestionInput(
        course_name="示例课程",
        exam_name="示例考试",
        question_type="单选",
        question_text="马克思主义中国化时代化的最新理论成果是什么？",
        options=[
            {"letter": "A", "content": "科学发展观"},
            {"letter": "B", "content": "习近平新时代中国特色社会主义思想"},
            {"letter": "C", "content": "邓小平理论"},
            {"letter": "D", "content": "三个代表重要思想"},
        ],
        question_number=1,
    )
    course_id, exam_id, decision, context = pipeline.prepare(question)
    print(json.dumps({"decision": decision.action, "reason": decision.reason}, ensure_ascii=False, indent=2))
    if context:
        print(context)

    if not decision.should_reuse:
        pipeline.commit(
            question=question,
            result=AnswerResult(
                answer=[2],
                answer_text="2",
                model_name="demo",
                rag_max_score=0.0,
                evidence=[
                    {
                        "evidence_type": "demo",
                        "source_label": "agent_v2 demo",
                        "content_excerpt": "示例写入，用于验证 memory schema 与 pipeline。",
                        "score": 1.0,
                    }
                ],
            ),
            course_id=course_id,
            exam_id=exam_id,
            memory_match_score=decision.match.match_score if decision.match else None,
        )
        print("demo memory committed")


if __name__ == "__main__":
    demo()
