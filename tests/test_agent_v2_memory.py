from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_v2.normalizer import QuestionNormalizer
from agent_v2.policy import MemoryPolicy
from agent_v2.storage import MemoryManager


class QuestionNormalizerTests(unittest.TestCase):
    def test_question_decorations_do_not_change_fingerprint(self) -> None:
        normalizer = QuestionNormalizer()
        options = [
            {"letter": "A", "content": "科学发展观"},
            {"letter": "B", "content": "习近平新时代中国特色社会主义思想"},
        ]
        left = normalizer.normalize("单选题", "1. 【单选题】马克思主义中国化时代化的最新理论成果是什么？", options)
        right = normalizer.normalize("单选", "马克思主义中国化时代化的最新理论成果是什么", options)
        self.assertEqual(left.question_fingerprint, right.question_fingerprint)


class MemoryManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "memory.sqlite3"
        self.memory = MemoryManager(db_path=self.db_path)
        self.course_id = self.memory.get_or_create_course("思想道德与法治")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_exact_question_can_be_confirmed_and_reused(self) -> None:
        options = [
            {"letter": "A", "content": "科学发展观"},
            {"letter": "B", "content": "习近平新时代中国特色社会主义思想"},
        ]
        memory_id = self.memory.upsert_question_memory(
            course_id=self.course_id,
            question_type="单选",
            question_text="马克思主义中国化时代化的最新理论成果是什么？",
            options=options,
            answer=[2],
            answer_text="2",
            evidence=[{"evidence_type": "rag", "source_label": "参考资料", "content_excerpt": "最新理论成果相关内容"}],
        )

        self.memory.record_feedback(memory_id, "confirmed", correct_answer=[2], note="人工确认")
        match = self.memory.search_question(
            self.course_id,
            "单选题",
            "1. 【单选题】马克思主义中国化时代化的最新理论成果是什么？",
            options,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.match_score, 1.0)
        self.assertEqual(match.confidence, 1.0)
        self.assertEqual(match.verified_status, "confirmed")

        decision = MemoryPolicy().decide(match)
        self.assertTrue(decision.should_reuse)

    def test_similar_question_becomes_reference_not_reuse(self) -> None:
        self.memory.upsert_question_memory(
            course_id=self.course_id,
            question_type="单选",
            question_text="理想信念是精神之钙。",
            options=[
                {"letter": "A", "content": "正确"},
                {"letter": "B", "content": "错误"},
            ],
            answer=[1],
            answer_text="1",
        )

        match = self.memory.search_question(
            self.course_id,
            "判断",
            "理想信念是精神上的钙。",
            [
                {"letter": "A", "content": "正确"},
                {"letter": "B", "content": "错误"},
            ],
        )
        self.assertIsNone(match)

        match = self.memory.search_question(
            self.course_id,
            "单选",
            "理想信念是精神上的钙。",
            [
                {"letter": "A", "content": "正确"},
                {"letter": "B", "content": "错误"},
            ],
        )
        self.assertIsNotNone(match)
        assert match is not None
        decision = MemoryPolicy(reuse_threshold=0.92, reference_threshold=0.30).decide(match)
        self.assertEqual(decision.action, "reference")

    def test_stats_and_text_search(self) -> None:
        self.memory.upsert_question_memory(
            course_id=self.course_id,
            question_type="填空",
            question_text="社会主义核心价值观国家层面的价值目标包括富强、民主、文明、和谐。",
            options=[],
            answer=["富强", "民主", "文明", "和谐"],
        )
        stats = self.memory.stats()
        self.assertEqual(stats["courses"], 1)
        self.assertEqual(stats["questions"], 1)
        results = self.memory.search_text("核心价值观")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["question_type"], "填空")


if __name__ == "__main__":
    unittest.main()
