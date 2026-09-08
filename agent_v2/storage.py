from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import MemoryMatch
from .normalizer import QuestionNormalizer


DEFAULT_DB_PATH = "./memory/zhihuishu_memory.sqlite3"


class MemoryManager:
    """SQLite-backed long-term memory for the V2 answering agent."""

    def __init__(
        self,
        db_path: str | os.PathLike[str] | None = None,
        normalizer: QuestionNormalizer | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.db_path = Path(db_path or os.getenv("MEMORY_DB_PATH", DEFAULT_DB_PATH))
        self.normalizer = normalizer or QuestionNormalizer()
        self.enabled = enabled if enabled is not None else os.getenv("MEMORY_ENABLED", "true").lower() == "true"
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        if not self.enabled:
            return
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def get_or_create_course(self, course_name: str) -> int:
        course_name = (course_name or "未知课程").strip() or "未知课程"
        now = _now()
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM courses WHERE course_name = ?", (course_name,)).fetchone()
            if row:
                conn.execute("UPDATE courses SET updated_at = ? WHERE id = ?", (now, row["id"]))
                return int(row["id"])
            cursor = conn.execute(
                "INSERT INTO courses (course_name, created_at, updated_at) VALUES (?, ?, ?)",
                (course_name, now, now),
            )
            return int(cursor.lastrowid)

    def get_or_create_exam(
        self,
        course_id: int,
        exam_name: str | None,
        exam_url: str | None,
        deadline_text: str | None,
    ) -> int:
        url_hash = self.normalizer._sha256_json(exam_url or "") if exam_url else None
        name = (exam_name or "未知考试").strip() or "未知考试"
        now = _now()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM exams
                WHERE course_id = ? AND exam_name = ? AND COALESCE(exam_url_hash, '') = COALESCE(?, '')
                """,
                (course_id, name, url_hash),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE exams SET deadline_text = ?, updated_at = ? WHERE id = ?",
                    (deadline_text, now, row["id"]),
                )
                return int(row["id"])

            cursor = conn.execute(
                """
                INSERT INTO exams (course_id, exam_name, exam_url_hash, deadline_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (course_id, name, url_hash, deadline_text, now, now),
            )
            return int(cursor.lastrowid)

    def search_question(
        self,
        course_id: int,
        question_type: str,
        question_text: str,
        options: list[Any] | None = None,
    ) -> MemoryMatch | None:
        if not self.enabled:
            return None

        normalized = self.normalizer.normalize(question_type, question_text, options)
        with self.connect() as conn:
            exact = conn.execute(
                """
                SELECT * FROM question_memories
                WHERE course_id = ? AND question_fingerprint = ?
                LIMIT 1
                """,
                (course_id, normalized.question_fingerprint),
            ).fetchone()
            if exact:
                return self._row_to_match(conn, exact, match_score=1.0)

            candidates = conn.execute(
                """
                SELECT * FROM question_memories
                WHERE course_id = ? AND question_type = ?
                ORDER BY last_seen_at DESC
                LIMIT 500
                """,
                (course_id, normalized.question_type),
            ).fetchall()

            best_row: sqlite3.Row | None = None
            best_score = 0.0
            for row in candidates:
                row_tokens = self.normalizer.tokenize(row["normalized_question"])
                for option in json.loads(row["options_json"] or "[]"):
                    row_tokens.update(self.normalizer.tokenize(option.get("normalized_content", "")))
                question_score = self.normalizer.similarity(normalized.tokens, row_tokens)
                option_bonus = 0.2 if row["option_signature"] == normalized.option_signature else 0.0
                score = min(1.0, question_score * 0.8 + option_bonus)
                if score > best_score:
                    best_score = score
                    best_row = row

            if best_row is None:
                return None
            return self._row_to_match(conn, best_row, match_score=best_score)

    def build_memory_context(self, match: MemoryMatch) -> str:
        answer = json.dumps(match.canonical_answer, ensure_ascii=False)
        evidence_lines = []
        for item in match.evidence[:3]:
            excerpt = (item.get("content_excerpt") or "").strip()
            if excerpt:
                evidence_lines.append(f"- {item.get('source_label') or item.get('evidence_type')}: {excerpt}")
        evidence = "\n".join(evidence_lines) if evidence_lines else "- 暂无额外证据摘要"
        return (
            "【历史记忆参考】\n"
            f"相似度: {match.match_score:.2f}\n"
            f"可信度: {match.confidence:.2f}\n"
            f"验证状态: {match.verified_status}\n"
            f"历史题干: {match.question_text}\n"
            f"历史答案: {answer}\n"
            f"证据摘要:\n{evidence}\n"
            "请将历史记忆作为参考；如果本题题干或选项存在关键差异，应重新判断。"
        )

    def record_attempt(
        self,
        question_memory_id: int | None,
        exam_id: int | None,
        question_number: int | None,
        model_name: str | None,
        rag_max_score: float | None,
        memory_match_score: float | None,
        answer: Any,
        action_status: str,
    ) -> int:
        answer_json = _json(answer)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO answer_attempts (
                    question_memory_id, exam_id, question_number, model_name, rag_max_score,
                    memory_match_score, answer_json, action_status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question_memory_id,
                    exam_id,
                    question_number,
                    model_name,
                    rag_max_score,
                    memory_match_score,
                    answer_json,
                    action_status,
                    _now(),
                ),
            )
            return int(cursor.lastrowid)

    def upsert_question_memory(
        self,
        course_id: int,
        question_type: str,
        question_text: str,
        options: list[Any] | None,
        answer: Any,
        answer_text: str | None = None,
        confidence: float = 0.55,
        source: str = "model",
        verified_status: str = "unverified",
        evidence: list[dict[str, Any]] | None = None,
    ) -> int:
        normalized = self.normalizer.normalize(question_type, question_text, options)
        now = _now()
        answer_json = _json(answer)
        options_json = _json(normalized.options)

        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, seen_count, confidence, canonical_answer_json
                FROM question_memories
                WHERE course_id = ? AND question_fingerprint = ?
                """,
                (course_id, normalized.question_fingerprint),
            ).fetchone()
            if row:
                next_confidence = max(float(row["confidence"]), confidence)
                if row["canonical_answer_json"] == answer_json:
                    next_confidence = min(0.85, next_confidence + 0.05)
                if verified_status == "confirmed":
                    next_confidence = 1.0
                conn.execute(
                    """
                    UPDATE question_memories
                    SET canonical_answer_json = ?, answer_text = ?, confidence = ?, source = ?,
                        verified_status = ?, last_seen_at = ?, seen_count = seen_count + 1
                    WHERE id = ?
                    """,
                    (
                        answer_json,
                        answer_text,
                        next_confidence,
                        source,
                        verified_status,
                        now,
                        row["id"],
                    ),
                )
                question_memory_id = int(row["id"])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO question_memories (
                        course_id, question_type, question_text, normalized_question,
                        question_fingerprint, options_json, option_signature,
                        canonical_answer_json, answer_text, confidence, source,
                        verified_status, first_seen_at, last_seen_at, seen_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        course_id,
                        normalized.question_type,
                        normalized.question_text,
                        normalized.normalized_question,
                        normalized.question_fingerprint,
                        options_json,
                        normalized.option_signature,
                        answer_json,
                        answer_text,
                        confidence,
                        source,
                        verified_status,
                        now,
                        now,
                    ),
                )
                question_memory_id = int(cursor.lastrowid)

            if evidence:
                self._insert_evidence(conn, question_memory_id, evidence)
            return question_memory_id

    def record_feedback(
        self,
        question_memory_id: int,
        feedback_type: str,
        correct_answer: Any | None = None,
        note: str | None = None,
    ) -> None:
        correct_answer_json = _json(correct_answer) if correct_answer is not None else None
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO user_feedback (
                    question_memory_id, feedback_type, correct_answer_json, note, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (question_memory_id, feedback_type, correct_answer_json, note, _now()),
            )
            if feedback_type in {"confirmed", "corrected"}:
                fields = ["verified_status = ?", "confidence = ?"]
                values: list[Any] = ["confirmed", 1.0]
                if correct_answer is not None:
                    fields.append("canonical_answer_json = ?")
                    values.append(correct_answer_json)
                    fields.append("answer_text = ?")
                    values.append(str(correct_answer))
                values.append(question_memory_id)
                conn.execute(
                    f"UPDATE question_memories SET {', '.join(fields)} WHERE id = ?",
                    values,
                )

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            return {
                "courses": conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0],
                "exams": conn.execute("SELECT COUNT(*) FROM exams").fetchone()[0],
                "questions": conn.execute("SELECT COUNT(*) FROM question_memories").fetchone()[0],
                "attempts": conn.execute("SELECT COUNT(*) FROM answer_attempts").fetchone()[0],
                "feedback": conn.execute("SELECT COUNT(*) FROM user_feedback").fetchone()[0],
            }

    def search_text(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        tokens = self.normalizer.tokenize(query)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM question_memories ORDER BY last_seen_at DESC LIMIT 1000"
            ).fetchall()
            scored = []
            for row in rows:
                row_tokens = self.normalizer.tokenize(row["normalized_question"])
                score = self.normalizer.similarity(tokens, row_tokens)
                if score > 0:
                    scored.append((score, row))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [
                {
                    "id": row["id"],
                    "score": round(score, 3),
                    "question_type": row["question_type"],
                    "question_text": row["question_text"],
                    "answer": json.loads(row["canonical_answer_json"]),
                    "confidence": row["confidence"],
                    "verified_status": row["verified_status"],
                }
                for score, row in scored[:limit]
            ]

    def _row_to_match(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        match_score: float,
    ) -> MemoryMatch:
        evidence = conn.execute(
            """
            SELECT evidence_type, source_label, content_excerpt, score, created_at
            FROM evidence_sources
            WHERE question_memory_id = ?
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (row["id"],),
        ).fetchall()
        return MemoryMatch(
            question_memory_id=int(row["id"]),
            course_id=int(row["course_id"]),
            question_type=row["question_type"],
            question_text=row["question_text"],
            normalized_question=row["normalized_question"],
            options=json.loads(row["options_json"] or "[]"),
            canonical_answer=json.loads(row["canonical_answer_json"]),
            answer_text=row["answer_text"],
            confidence=float(row["confidence"]),
            source=row["source"],
            verified_status=row["verified_status"],
            match_score=match_score,
            evidence=[dict(item) for item in evidence],
        )

    def _insert_evidence(
        self,
        conn: sqlite3.Connection,
        question_memory_id: int,
        evidence: list[dict[str, Any]],
    ) -> None:
        for item in evidence:
            conn.execute(
                """
                INSERT INTO evidence_sources (
                    question_memory_id, evidence_type, source_label, content_excerpt, score, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    question_memory_id,
                    item.get("evidence_type", "text"),
                    item.get("source_label"),
                    item.get("content_excerpt"),
                    item.get("score"),
                    _now(),
                ),
            )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    exam_name TEXT NOT NULL,
    exam_url_hash TEXT,
    deadline_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(course_id, exam_name, exam_url_hash)
);

CREATE TABLE IF NOT EXISTS question_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    question_type TEXT NOT NULL,
    question_text TEXT NOT NULL,
    normalized_question TEXT NOT NULL,
    question_fingerprint TEXT NOT NULL,
    options_json TEXT NOT NULL,
    option_signature TEXT NOT NULL,
    canonical_answer_json TEXT NOT NULL,
    answer_text TEXT,
    confidence REAL NOT NULL DEFAULT 0.55,
    source TEXT NOT NULL DEFAULT 'model',
    verified_status TEXT NOT NULL DEFAULT 'unverified',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    UNIQUE(course_id, question_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_question_memories_lookup
ON question_memories(course_id, question_type, last_seen_at);

CREATE TABLE IF NOT EXISTS answer_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_memory_id INTEGER REFERENCES question_memories(id) ON DELETE SET NULL,
    exam_id INTEGER REFERENCES exams(id) ON DELETE SET NULL,
    question_number INTEGER,
    model_name TEXT,
    rag_max_score REAL,
    memory_match_score REAL,
    answer_json TEXT,
    action_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_memory_id INTEGER NOT NULL REFERENCES question_memories(id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    source_label TEXT,
    content_excerpt TEXT,
    score REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_memory_id INTEGER NOT NULL REFERENCES question_memories(id) ON DELETE CASCADE,
    feedback_type TEXT NOT NULL,
    correct_answer_json TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
"""
