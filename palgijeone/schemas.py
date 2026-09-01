from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Attribute(StrictModel):
    name: str
    value: str
    source_text: str | None = None
    source_url: str | None = None


class Product(StrictModel):
    """상품 상세페이지에서 파싱해 툴 선택에 사용하는 정보."""

    product_id: str
    product_name: str | None = None
    category: str | None = None
    intended_use: str | None = None
    target_age: str | None = None

    wireless: bool | None = None
    battery_included: bool | None = None
    electrical_powered: bool | None = None
    food_contact: bool | None = None
    medical_claim: bool | None = None
    cosmetic_claim: bool | None = None

    listing_text: list[str] = Field(default_factory=list)
    attributes: list[Attribute] = Field(default_factory=list)
    source_url: str | None = None


class ToolName(StrEnum):
    CUSTOMS = "customs_requirements"
    RADIO = "radio_compliance"
    FOOD_DRUG = "food_drug_safety"
    ELECTRICAL = "electrical_safety"
    CHILDREN = "children_product_safety"
    LABEL_AD = "labeling_advertising_detection"


class ToolStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class Determination(StrEnum):
    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    POSSIBLY_REQUIRED = "possibly_required"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    NOT_APPLICABLE = "not_applicable"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class OverallStatus(StrEnum):
    LIKELY_COMPLIANT = "likely_compliant"
    ACTION_REQUIRED = "action_required"
    HIGH_RISK = "high_risk"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class LegalSource(StrictModel):
    source_name: str
    law_name: str | None = None
    article: str | None = None
    quoted_text: str | None = None
    source_url: str | None = None
    effective_date: str | None = None
    is_mock: bool = True


class RegulatoryFinding(StrictModel):
    finding_id: str = Field(default_factory=lambda: str(uuid4()))
    tool_name: ToolName
    subject: str
    determination: Determination
    risk_level: RiskLevel
    summary: str
    rationale: str
    product_facts_used: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    legal_sources: list[LegalSource] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ToolResult(StrictModel):
    tool_name: ToolName
    status: ToolStatus
    selected: bool
    selection_reason: str
    query: dict[str, Any] = Field(default_factory=dict)
    findings: list[RegulatoryFinding] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    raw_response: dict[str, Any] | list[Any] | str | None = None
    error: str | None = None
    executed_at: datetime = Field(default_factory=utc_now)


class FollowUpQuestion(StrictModel):
    question_id: str = Field(default_factory=lambda: str(uuid4()))
    question: str
    reason: str
    related_tools: list[ToolName] = Field(default_factory=list)
    required: bool = True


class TraceEvent(StrictModel):
    sequence: int
    stage: str
    component: str
    action: str
    status: str
    detail: str
    created_at: datetime = Field(default_factory=utc_now)


class DraftAssessment(StrictModel):
    assessment_id: str = Field(default_factory=lambda: str(uuid4()))
    product: Product
    selected_tools: list[ToolName]
    tool_results: list[ToolResult]
    findings: list[RegulatoryFinding]
    overall_status: OverallStatus
    summary: str
    required_actions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class VerificationIssueType(StrEnum):
    MISSING_TOOL = "missing_tool"
    TOOL_FAILURE = "tool_failure"
    MISSING_EVIDENCE = "missing_evidence"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CONTRADICTION = "contradiction"
    INSUFFICIENT_PRODUCT_DATA = "insufficient_product_data"
    INCORRECT_DETERMINATION = "incorrect_determination"


class VerificationIssue(StrictModel):
    issue_id: str = Field(default_factory=lambda: str(uuid4()))
    severity: str
    issue_type: VerificationIssueType
    description: str
    related_finding_ids: list[str] = Field(default_factory=list)
    recommended_action: str | None = None


class VerificationStatus(StrEnum):
    APPROVED = "approved"
    APPROVED_WITH_WARNINGS = "approved_with_warnings"
    REVISION_REQUIRED = "revision_required"
    USER_INPUT_REQUIRED = "user_input_required"


class VerificationResult(StrictModel):
    status: VerificationStatus
    issues: list[VerificationIssue] = Field(default_factory=list)
    additional_tools_required: list[ToolName] = Field(default_factory=list)
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)
    checked_finding_ids: list[str] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=utc_now)


class FinalVerificationStatus(StrEnum):
    VERIFIED = "verified"
    VERIFIED_WITH_WARNINGS = "verified_with_warnings"
    INCOMPLETE = "incomplete"


class FinalAssessment(StrictModel):
    assessment_id: str
    schema_version: str = "0.1.0"
    product: Product
    verification_status: FinalVerificationStatus
    overall_status: OverallStatus
    summary: str
    findings: list[RegulatoryFinding]
    required_actions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)
    verification: VerificationResult
    trace: list[TraceEvent] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)

