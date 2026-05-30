"""Schemas and model profiles for source-grounded agent review."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import OllamaThink


AgentToolName = Literal[
    "search_pdf",
    "inspect_chunk",
    "inspect_page",
    "ground_quiz_item",
    "compare_options",
    "render_page_image",
    "vision_inspect_page",
    "web_search",
    "web_fetch",
    "finalize_item_review",
]
AgentVerdict = Literal[
    "key_supported",
    "key_conflict_candidate",
    "source_missing",
    "ambiguous_question",
    "needs_human_review",
]
FindingSeverity = Literal["info", "low", "medium", "high"]
EvidenceStrength = Literal["direct", "strong", "partial", "weak", "missing"]
DistractorVerdict = Literal[
    "contradicted_by_source",
    "plausible_but_wrong",
    "not_discussed",
    "ambiguous",
]
ReviewPriority = Literal["pass", "inspect", "fix"]


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal[
        "cpu-local", "review-local", "gemma3-local", "gemma3-fast", "hybrid-max"
    ]
    recommended_model: str
    fallback_model: str | None = None
    num_ctx: int
    num_predict: int
    think: OllamaThink = False
    allow_web_default: bool = False
    vision_pages_default: Literal["auto", "off", "on"] = "auto"


MODEL_PROFILES: dict[str, ModelProfile] = {
    "cpu-local": ModelProfile(
        name="cpu-local",
        recommended_model="gemma-python",
        fallback_model=None,
        num_ctx=8192,
        num_predict=768,
        think=False,
        allow_web_default=False,
        vision_pages_default="off",
    ),
    "review-local": ModelProfile(
        name="review-local",
        recommended_model="gemma-python",
        fallback_model=None,
        num_ctx=8192,
        num_predict=1024,
        think=False,
        allow_web_default=False,
        vision_pages_default="off",
    ),
    "gemma3-local": ModelProfile(
        name="gemma3-local",
        recommended_model="gemma3:12b",
        fallback_model="gemma3:4b",
        num_ctx=65536,
        num_predict=2048,
        think=False,
        allow_web_default=False,
        vision_pages_default="auto",
    ),
    "gemma3-fast": ModelProfile(
        name="gemma3-fast",
        recommended_model="gemma3:4b",
        fallback_model="gemma3:4b",
        num_ctx=32768,
        num_predict=1024,
        think=False,
        allow_web_default=False,
        vision_pages_default="auto",
    ),
    "hybrid-max": ModelProfile(
        name="hybrid-max",
        recommended_model="gemma3:12b",
        fallback_model="gemma3:4b",
        num_ctx=131072,
        num_predict=3072,
        think="medium",
        allow_web_default=False,
        vision_pages_default="auto",
    ),
}


def resolve_model_profile(
    name: str | None, explicit_model: str | None = None
) -> ModelProfile:
    profile_name = name or "cpu-local"
    try:
        profile = MODEL_PROFILES[profile_name]
    except KeyError as exc:
        choices = ", ".join(sorted(MODEL_PROFILES))
        raise ValueError(
            f"Unknown model profile {profile_name!r}; choose one of: {choices}"
        ) from exc
    if explicit_model is None:
        return profile
    return profile.model_copy(update={"recommended_model": explicit_model})


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    chunk_id: int | None = None
    page: int | None = None
    citation: str | None = None
    snippet: str


class QuestionQualityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: FindingSeverity = "info"
    finding_type: str
    message: str


class DistractorReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: str
    option_text: str
    verdict: DistractorVerdict
    confidence_score: float = Field(ge=0.0, le=1.0)
    rationale: str


class AgentReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    verdict: AgentVerdict
    keyed_option: str | None = None
    keyed_option_text: str | None = None
    selected_option: str | None = None
    selected_option_text: str | None = None
    explanation: str
    evidence_strength: EvidenceStrength = "missing"
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    support_reason: str | None = None
    distractor_analysis: dict[str, str] = Field(default_factory=dict)
    distractor_verdicts: dict[str, DistractorReview] = Field(default_factory=dict)
    misconception_risks: list[str] = Field(default_factory=list)
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    quality_findings: list[QuestionQualityFinding] = Field(default_factory=list)
    source_status: str | None = None
    tool_calls: list[str] = Field(default_factory=list)
    needs_human_review_reason: str | None = None
    review_priority: ReviewPriority = "inspect"


class AgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: AgentToolName
    arguments: dict[str, Any] = Field(default_factory=dict)
    final_review: AgentReviewItem | None = None

    @field_validator("final_review")
    @classmethod
    def require_final_for_finalize(
        _cls, value: AgentReviewItem | None, info
    ) -> AgentReviewItem | None:
        if info.data.get("tool") == "finalize_item_review" and value is None:
            raise ValueError("finalize_item_review requires final_review")
        return value


class AgentToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: int
    quiz: str
    model: str
    model_profile: str
    allow_web: bool
    vision_pages: Literal["auto", "off", "on"]
    item_count: int
    verdict_counts: dict[str, int]
    quality_counts: dict[str, int]
    priority_counts: dict[str, int] = Field(default_factory=dict)
    items: list[AgentReviewItem]
    tool_trace_path: str | None = None
