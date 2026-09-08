from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .models import NormalizedQuestion


class QuestionNormalizer:
    """Normalize OCR-extracted questions into stable memory lookup keys."""

    _decorations = (
        r"^\s*\d+\s*[\.、)]\s*",
        r"^\s*第\s*\d+\s*题\s*",
        r"【\s*(单选|多选|判断|填空|简答)[^】]*】",
        r"\(\s*\d+\s*分\s*\)",
    )

    def normalize_text(self, text: str | None) -> str:
        if not text:
            return ""
        value = text.strip().lower()
        for pattern in self._decorations:
            value = re.sub(pattern, "", value)
        value = re.sub(r"\s+", "", value)
        value = re.sub(r"[，,。.;；:：、!?！？\"'“”‘’（）()\[\]{}<>《》|/\\_-]+", "", value)
        return value

    def normalize_question_type(self, question_type: str | None) -> str:
        value = question_type or "未知题型"
        for candidate in ("单选", "多选", "判断", "填空", "简答"):
            if candidate in value:
                return candidate
        return value.strip() or "未知题型"

    def normalize_options(self, options: list[Any] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        if not options:
            return normalized

        for index, option in enumerate(options):
            if isinstance(option, dict):
                letter = str(option.get("letter") or option.get("label") or "").strip()
                content = str(option.get("content") or option.get("text") or "").strip()
            elif isinstance(option, (tuple, list)):
                letter = str(option[0]) if len(option) > 0 else ""
                content = str(option[1]) if len(option) > 1 else ""
            else:
                letter = ""
                content = str(option)

            normalized.append(
                {
                    "index": index + 1,
                    "letter": letter.upper(),
                    "content": content,
                    "normalized_content": self.normalize_text(content),
                }
            )
        return normalized

    def option_signature(self, options: list[dict[str, Any]]) -> str:
        payload = [
            {
                "index": option["index"],
                "letter": option["letter"],
                "content": option["normalized_content"],
            }
            for option in options
        ]
        return self._sha256_json(payload)

    def tokenize(self, text: str | None) -> set[str]:
        value = self.normalize_text(text)
        if not value:
            return set()

        chinese_chars = re.findall(r"[\u4e00-\u9fa5]", value)
        english_words = re.findall(r"[a-z0-9]+", value)
        tokens = set(english_words)

        for i in range(len(chinese_chars) - 1):
            tokens.add(chinese_chars[i] + chinese_chars[i + 1])
        for i in range(len(chinese_chars) - 2):
            tokens.add(chinese_chars[i] + chinese_chars[i + 1] + chinese_chars[i + 2])
        return tokens

    def normalize(
        self,
        question_type: str | None,
        question_text: str | None,
        options: list[Any] | None = None,
    ) -> NormalizedQuestion:
        normalized_type = self.normalize_question_type(question_type)
        normalized_question = self.normalize_text(question_text)
        normalized_options = self.normalize_options(options)
        option_signature = self.option_signature(normalized_options)
        fingerprint = self.question_fingerprint(
            normalized_type,
            normalized_question,
            option_signature,
        )
        tokens = self.tokenize(normalized_question)
        for option in normalized_options:
            tokens.update(self.tokenize(option["normalized_content"]))

        return NormalizedQuestion(
            question_type=normalized_type,
            question_text=question_text or "",
            normalized_question=normalized_question,
            options=normalized_options,
            option_signature=option_signature,
            question_fingerprint=fingerprint,
            tokens=tokens,
        )

    def question_fingerprint(
        self,
        question_type: str,
        normalized_question: str,
        option_signature: str,
    ) -> str:
        return self._sha256_json(
            {
                "question_type": question_type,
                "normalized_question": normalized_question,
                "option_signature": option_signature,
            }
        )

    def similarity(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _sha256_json(self, payload: Any) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
