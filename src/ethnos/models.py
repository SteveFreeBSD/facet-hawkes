"""Typed records and validation schemas used across the pipeline."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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

    name: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_pages: list[int] = Field(default_factory=list)


class KeyTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str
    definition: str
    context: str = ""
    source_pages: list[int] = Field(default_factory=list)


class Example(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body: str
    source_pages: list[int] = Field(default_factory=list)


class StudyQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    source_pages: list[int] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_summary: str
    topics: list[TopicExtraction] = Field(default_factory=list)
    key_terms: list[KeyTerm] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    questions: list[StudyQuestion] = Field(default_factory=list)

