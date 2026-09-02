"""파이프라인의 입력부터 최종 출력까지 사용하는 Pydantic 계약 모음.

외부 API 원본(`raw_response`), 툴별 정규화 결과(`result`), 공통 규제 판단
(`findings`)을 분리해 각 판단의 근거를 역추적할 수 있도록 설계한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """타임존이 포함된 현재 UTC 시각을 반환한다."""

    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    """정의되지 않은 입력 필드를 거부하는 모든 프로젝트 스키마의 기반 모델."""

    model_config = ConfigDict(extra="forbid")


# 상품 파싱 단계 -------------------------------------------------------------
class Attribute(StrictModel):
    """고정 Product 필드에 포함되지 않는 상품별 추가 속성과 출처."""

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
    target_age: str | None = Field(
        default=None,
        description="'만 14세 이상'처럼 상세페이지에 표시된 대상 연령 원문",
    )

    # bool의 None은 False가 아니라 상세페이지에서 확인하지 못했다는 뜻이다.
    wireless: bool | None = None
    battery_included: bool | None = None
    electrical_powered: bool | None = None
    food_contact: bool | None = None
    medical_claim: bool | None = None
    cosmetic_claim: bool | None = None

    listing_text: list[str] = Field(
        default_factory=list,
        description="표시광고 문구 탐지에 사용할 상세페이지 문장",
    )
    attributes: list[Attribute] = Field(default_factory=list)
    source_url: str | None = None


# 공통 상태 값 ---------------------------------------------------------------
class ToolName(StrEnum):
    """분석 에이전트가 선택할 수 있는 6개 규제 툴의 식별자."""

    CUSTOMS = "customs_requirements"
    RADIO = "radio_compliance"
    FOOD_DRUG = "food_drug_safety"
    ELECTRICAL = "electrical_safety"
    CHILDREN = "children_product_safety"
    LABEL_AD = "labeling_advertising_detection"


class ToolStatus(StrEnum):
    """툴 호출 자체의 실행 상태."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class Determination(StrEnum):
    """툴 실행 후 내려진 개별 규제 적용 판단."""

    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    POSSIBLY_REQUIRED = "possibly_required"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    NOT_APPLICABLE = "not_applicable"


class RiskLevel(StrEnum):
    """개별 판단 또는 문구의 위험 수준."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class OverallStatus(StrEnum):
    """여러 툴 결과를 종합한 상품 전체 상태."""

    LIKELY_COMPLIANT = "likely_compliant"
    ACTION_REQUIRED = "action_required"
    HIGH_RISK = "high_risk"
    INSUFFICIENT_INFORMATION = "insufficient_information"


# 근거와 툴별 상세 결과 ------------------------------------------------------
class LegalSource(StrictModel):
    """규제 판단을 뒷받침하는 법령·기관·API 출처."""

    source_name: str
    law_name: str | None = None
    article: str | None = None
    quoted_text: str | None = None
    source_url: str | None = None
    effective_date: str | None = None
    is_mock: bool = True


class CustomsAssessment(StrictModel):
    """통관 요건 툴이 정규화한 HS 코드·서류·확인 요건."""

    kind: Literal["customs"] = "customs"
    hs_code_candidates: list[str] = Field(default_factory=list)
    customs_confirmation_required: bool | None = None
    applicable_requirements: list[str] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    legal_sources: list[LegalSource] = Field(default_factory=list)


class RadioAssessment(StrictModel):
    """전파 툴이 정규화한 무선 기능·주파수·적합성평가 정보."""

    kind: Literal["radio"] = "radio"
    wireless_features: list[str] = Field(default_factory=list)
    frequency_bands: list[str] = Field(default_factory=list)
    conformity_assessment_required: bool | None = None
    certification_type: str | None = None
    legal_sources: list[LegalSource] = Field(default_factory=list)


class FoodDrugAssessment(StrictModel):
    """식약 툴이 정규화한 제품 유형·효능 표방·원료 정보."""

    kind: Literal["food_drug"] = "food_drug"
    regulatory_categories: list[str] = Field(default_factory=list)
    regulated: bool | None = None
    detected_claims: list[str] = Field(default_factory=list)
    ingredients_or_materials: list[str] = Field(default_factory=list)
    applicable_requirements: list[str] = Field(default_factory=list)
    legal_sources: list[LegalSource] = Field(default_factory=list)


class ElectricalAssessment(StrictModel):
    """전안법 툴이 정규화한 전원·정격·안전관리 정보."""

    kind: Literal["electrical"] = "electrical"
    power_sources: list[str] = Field(default_factory=list)
    rated_specifications: list[str] = Field(default_factory=list)
    safety_management_required: bool | None = None
    certification_type: str | None = None
    legal_sources: list[LegalSource] = Field(default_factory=list)


class ChildrenAssessment(StrictModel):
    """어린이제품 툴이 연령 원문과 실제 용도를 구분해 정리한 결과."""

    kind: Literal["children"] = "children"
    target_age_raw: str | None = None
    intended_for_children: bool | None = None
    product_type: str | None = None
    safety_management_required: bool | None = None
    certification_type: str | None = None
    legal_sources: list[LegalSource] = Field(default_factory=list)


class AdvertisingPhrase(StrictModel):
    """표시광고 툴이 탐지한 개별 위험 문구."""

    text: str
    risk_type: str
    risk_level: RiskLevel
    reason: str
    evidence_required: bool = False


class AdvertisingAssessment(StrictModel):
    """검사한 문구 전체와 탐지 결과를 포함한 표시광고 툴 결과."""

    kind: Literal["advertising"] = "advertising"
    reviewed_phrases: list[str] = Field(default_factory=list)
    detected_phrases: list[AdvertisingPhrase] = Field(default_factory=list)
    overall_risk: RiskLevel
    legal_sources: list[LegalSource] = Field(default_factory=list)


# kind 필드를 discriminator로 사용해 JSON을 올바른 전용 모델로 복원한다.
ToolAssessment = Annotated[
    CustomsAssessment
    | RadioAssessment
    | FoodDrugAssessment
    | ElectricalAssessment
    | ChildrenAssessment
    | AdvertisingAssessment,
    Field(discriminator="kind"),
]


# 툴 공통 결과 ---------------------------------------------------------------
class RegulatoryFinding(StrictModel):
    """서로 다른 규제 툴을 종합·검증하기 위한 공통 판단 단위."""

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
    """규제 툴 한 번의 선택 여부, 실행 상태, 상세 결과와 원본 응답."""

    tool_name: ToolName
    attempt: int = Field(default=1, ge=1)
    status: ToolStatus
    selected: bool
    selection_reason: str
    query: dict[str, Any] = Field(default_factory=dict)
    result: ToolAssessment | None = Field(
        default=None,
        description="6개 툴 중 하나가 반환한 도메인별 정규화 결과",
    )
    findings: list[RegulatoryFinding] = Field(
        default_factory=list,
        description="종합기와 검증기가 공통으로 처리할 규제 판단",
    )
    required_actions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    raw_response: dict[str, Any] | list[Any] | str | None = Field(
        default=None,
        description="관세청·식약처·법제처 등 외부 API가 반환한 가공 전 응답",
    )
    error: str | None = None
    executed_at: datetime = Field(default_factory=utc_now)


# 종합 단계 ------------------------------------------------------------------
class FollowUpQuestion(StrictModel):
    """규제 판단에 정보가 부족할 때 사용자에게 요청할 추가 정보."""

    question_id: str = Field(default_factory=lambda: str(uuid4()))
    question: str
    reason: str
    related_tools: list[ToolName] = Field(default_factory=list)
    required: bool = True


class TraceEvent(StrictModel):
    """툴 선택부터 재검사까지 파이프라인 동작을 시간순으로 남기는 로그."""

    sequence: int
    stage: str
    component: str
    action: str
    status: str
    detail: str
    created_at: datetime = Field(default_factory=utc_now)


class DraftAssessment(StrictModel):
    """6개 툴 결과를 합쳐 검증 에이전트에 전달하는 검증 전 초안."""

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


# 검증 단계 ------------------------------------------------------------------
class VerificationIssueType(StrEnum):
    """검증 에이전트가 보고할 수 있는 문제 유형."""

    MISSING_TOOL = "missing_tool"
    TOOL_FAILURE = "tool_failure"
    MISSING_EVIDENCE = "missing_evidence"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CONTRADICTION = "contradiction"
    INSUFFICIENT_PRODUCT_DATA = "insufficient_product_data"
    INCORRECT_DETERMINATION = "incorrect_determination"
    INVALID_VERIFICATION_RESPONSE = "invalid_verification_response"
    VERIFICATION_FAILURE = "verification_failure"


class VerificationIssue(StrictModel):
    """검증 과정에서 발견한 하나의 문제와 권장 조치."""

    issue_id: str = Field(default_factory=lambda: str(uuid4()))
    severity: str
    issue_type: VerificationIssueType
    description: str
    related_finding_ids: list[str] = Field(default_factory=list)
    recommended_action: str | None = None


class VerificationStatus(StrEnum):
    """검증 에이전트가 다음 파이프라인 동작을 결정하는 상태."""

    APPROVED = "approved"
    APPROVED_WITH_WARNINGS = "approved_with_warnings"
    REVISION_REQUIRED = "revision_required"
    USER_INPUT_REQUIRED = "user_input_required"


class VerificationResult(StrictModel):
    """검증 이슈, 추가 툴, 사용자 질문을 포함한 검증 에이전트 출력."""

    status: VerificationStatus
    review_summary: str | None = None
    issues: list[VerificationIssue] = Field(default_factory=list)
    additional_tools_required: list[ToolName] = Field(default_factory=list)
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)
    checked_finding_ids: list[str] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=utc_now)


class RemediationRecord(StrictModel):
    """revision_required 이후 실행한 한 번의 자동 재검사 기록."""

    iteration: int = Field(ge=1)
    trigger_status: VerificationStatus
    tools: list[ToolName]
    reason: str
    result_statuses: dict[ToolName, ToolStatus] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class PipelineState(StrictModel):
    """재검사 루프 중 유지하는 내부 실행 상태."""

    product: Product
    verification_round: int = Field(default=1, ge=1)
    max_remediation_attempts: int = Field(default=2, ge=0)
    tool_results: list[ToolResult] = Field(default_factory=list)
    tool_result_history: list[ToolResult] = Field(default_factory=list)
    draft: DraftAssessment | None = None
    verification: VerificationResult | None = None
    verification_history: list[VerificationResult] = Field(default_factory=list)
    remediation_history: list[RemediationRecord] = Field(default_factory=list)


# 최종 출력 ------------------------------------------------------------------
class FinalVerificationStatus(StrEnum):
    """세부 검증 상태를 사용자용으로 단순화한 최종 상태."""

    VERIFIED = "verified"
    VERIFIED_WITH_WARNINGS = "verified_with_warnings"
    INCOMPLETE = "incomplete"


class FinalAssessment(StrictModel):
    """최신 툴 결과, 검증 및 전체 이력을 포함한 파이프라인 최종 출력."""

    assessment_id: str
    schema_version: str = "0.3.0"
    product: Product
    verification_status: FinalVerificationStatus
    overall_status: OverallStatus
    summary: str
    selected_tools: list[ToolName]
    tool_results: list[ToolResult]
    tool_result_history: list[ToolResult] = Field(
        default_factory=list,
        description="최초 실행과 모든 재검사를 포함한 툴 결과 이력",
    )
    findings: list[RegulatoryFinding]
    required_actions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)
    verification: VerificationResult
    verification_history: list[VerificationResult] = Field(default_factory=list)
    verification_rounds: int = Field(default=1, ge=1)
    remediation_history: list[RemediationRecord] = Field(
        default_factory=list,
        description="검증 에이전트 요청으로 수행된 자동 추가 조치 이력",
    )
    trace: list[TraceEvent] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)

