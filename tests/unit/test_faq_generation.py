from __future__ import annotations

import json

import httpx

from src.core.config import Settings
from src.services.faq import GatewayFaqGenerator, combined_faq_score, parse_generated_faqs


def test_malformed_entries_are_rejected_without_losing_valid_siblings() -> None:
    parsed = parse_generated_faqs(
        json.dumps(
            {
                "faqs": [
                    {
                        "question": "چطور برنامه را مستقر کنم؟",
                        "answer": "با دستور liara deploy برنامه را مستقر کنید.",
                        "chunk_ordinal": 2,
                        "tags": ["deploy"],
                    },
                    {"question": "", "answer": "کوتاه", "chunk_ordinal": 2, "tags": []},
                    {
                        "question": "پرسش با منبع اشتباه چیست؟",
                        "answer": "این پاسخ ordinal نامعتبر دارد.",
                        "chunk_ordinal": 99,
                        "tags": [],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        {2},
    )

    assert len(parsed.accepted) == 1
    assert parsed.accepted[0].chunk_ordinal == 2
    assert len(parsed.rejected) == 2


def test_gateway_requests_strict_schema_with_low_reasoning_effort() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"faqs": []}'}}]},
        )

    settings = Settings(
        _env_file=None,
        faq_reasoning_effort="low",
        llm_api_key="test-only",
    )
    generator = GatewayFaqGenerator(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = generator.generate(title="استقرار", chunks=[])

    assert result == '{"faqs": []}'
    assert captured["reasoning_effort"] == "low"
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True


def test_curated_priority_changes_ordering_without_changing_similarity() -> None:
    similarity = 0.73

    score = combined_faq_score(similarity, priority=4, priority_weight=0.01)

    assert score == 0.77
    assert similarity == 0.73
