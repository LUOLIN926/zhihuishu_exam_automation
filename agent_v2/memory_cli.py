from __future__ import annotations

import argparse
import json
from typing import Any

from .storage import MemoryManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect and maintain the Zhihuishu V2 memory database.")
    parser.add_argument("--db", default=None, help="SQLite database path. Defaults to MEMORY_DB_PATH.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("stats", help="Show memory database counts.")

    search_parser = subparsers.add_parser("search", help="Search remembered questions by text.")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)

    feedback_parser = subparsers.add_parser("feedback", help="Record user feedback for a remembered question.")
    feedback_parser.add_argument("--id", type=int, required=True, dest="question_memory_id")
    feedback_parser.add_argument(
        "--type",
        choices=("confirmed", "corrected", "wrong", "note"),
        default="confirmed",
        dest="feedback_type",
    )
    feedback_parser.add_argument("--answer", default=None, help="Correct answer as JSON, for example '[1]' or '[\"北京\"]'.")
    feedback_parser.add_argument("--note", default=None)

    args = parser.parse_args()
    memory = MemoryManager(db_path=args.db)

    if args.command == "stats":
        print(json.dumps(memory.stats(), ensure_ascii=False, indent=2))
        return

    if args.command == "search":
        print(json.dumps(memory.search_text(args.query, limit=args.limit), ensure_ascii=False, indent=2))
        return

    if args.command == "feedback":
        answer: Any | None = None
        if args.answer is not None:
            answer = json.loads(args.answer)
        memory.record_feedback(
            question_memory_id=args.question_memory_id,
            feedback_type=args.feedback_type,
            correct_answer=answer,
            note=args.note,
        )
        print("feedback recorded")
        return


if __name__ == "__main__":
    main()
