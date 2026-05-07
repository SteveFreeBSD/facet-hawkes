from __future__ import annotations

import pytest
from pydantic import ValidationError

from ethnos.models import ExtractionResult


def test_extraction_result_validates_good_json():
    result = ExtractionResult.model_validate_json(
        """
        {
          "chunk_summary": "Plants convert light into chemical energy.",
          "topics": [
            {
              "name": "Photosynthesis",
              "summary": "Plants use light to make sugars.",
              "confidence": 0.9,
              "source_pages": [1]
            }
          ],
          "key_terms": [],
          "examples": [],
          "questions": []
        }
        """
    )

    assert result.topics[0].name == "Photosynthesis"


def test_extraction_result_rejects_extra_keys():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(
            {
                "chunk_summary": "Summary",
                "topics": [],
                "key_terms": [],
                "examples": [],
                "questions": [],
                "unexpected": True,
            }
        )


def test_extraction_result_rejects_blank_study_question_answer():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(
            {
                "chunk_summary": "Summary",
                "topics": [],
                "key_terms": [],
                "examples": [],
                "questions": [
                    {
                        "question": "What is virtue ethics?",
                        "answer": "   ",
                        "difficulty": "easy",
                        "source_pages": [12],
                    }
                ],
            }
        )


def test_extraction_result_rejects_blank_core_study_fields():
    invalid_records = [
        {
            "topics": [
                {
                    "name": " ",
                    "summary": "A useful summary.",
                    "confidence": 0.8,
                    "source_pages": [1],
                }
            ],
            "key_terms": [],
            "examples": [],
            "questions": [],
        },
        {
            "topics": [],
            "key_terms": [
                {
                    "term": "Ethics",
                    "definition": "",
                    "context": "",
                    "source_pages": [1],
                }
            ],
            "examples": [],
            "questions": [],
        },
        {
            "topics": [],
            "key_terms": [],
            "examples": [
                {
                    "title": "Example",
                    "body": " ",
                    "source_pages": [1],
                }
            ],
            "questions": [],
        },
        {
            "topics": [],
            "key_terms": [],
            "examples": [],
            "questions": [
                {
                    "question": " ",
                    "answer": "A supported answer.",
                    "difficulty": "medium",
                    "source_pages": [1],
                }
            ],
        },
    ]

    for record in invalid_records:
        record["chunk_summary"] = "Summary"
        with pytest.raises(ValidationError):
            ExtractionResult.model_validate(record)


def test_extraction_result_accepts_valid_question_and_defaults_difficulty():
    result = ExtractionResult.model_validate(
        {
            "chunk_summary": "Summary",
            "topics": [],
            "key_terms": [],
            "examples": [],
            "questions": [
                {
                    "question": "  What is virtue ethics?  ",
                    "answer": "  It studies moral character and virtues.  ",
                    "source_pages": [12],
                }
            ],
        }
    )

    assert result.questions[0].question == "What is virtue ethics?"
    assert result.questions[0].answer == "It studies moral character and virtues."
    assert result.questions[0].difficulty == "medium"
