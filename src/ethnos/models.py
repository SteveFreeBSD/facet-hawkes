"""Typed records and validation schemas used across the pipeline."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from typing_extensions import Annotated


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DocumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    source_path: str
    filename: str
    sha256: str
    title: str | None = None
    page_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    document_id: int
    page_number: int
    raw_text: str
    cleaned_text: str
    char_count: int
    extraction_method: str = "pymupdf:get_text(sort=True)"


class ChunkRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    document_id: int
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    heading: str | None = None
    char_count: int
    source_citation: str


class TopicExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyStr
    summary: NonEmptyStr
    confidence: float
    source_pages: list[int] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: Any) -> float:
        """Normalize confidence to 0-1.  Gemma sometimes returns integer scales."""
        v = float(v)
        if v > 1.0:
            v = v / (5.0 if v <= 5.0 else 10.0)
        return max(0.0, min(1.0, v))


class KeyTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: NonEmptyStr
    definition: NonEmptyStr
    context: str = ""
    source_pages: list[int] = Field(default_factory=list)


class Example(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyStr
    body: NonEmptyStr
    source_pages: list[int] = Field(default_factory=list)


class StudyQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: NonEmptyStr
    answer: NonEmptyStr
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    source_pages: list[int] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_summary: str
    topics: list[TopicExtraction]
    key_terms: list[KeyTerm]
    examples: list[Example]
    questions: list[StudyQuestion]
