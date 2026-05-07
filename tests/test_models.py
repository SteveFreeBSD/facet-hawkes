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

