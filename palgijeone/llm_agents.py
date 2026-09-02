from __future__ import annotations

import os
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from .schemas import (
    DraftAssessment,
    ToolName,
    VerificationIssue,
    VerificationIssueType,
    VerificationResult,
    VerificationStatus,
)
from .selector import SelectionDecision, ToolSelector
from .verifier import VerificationAgent


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class StructuredLLMClient(Protocol):
    model_name: str

    def generate(self, prompt: str, response_model: type[ResponseModel]) -> ResponseModel:
        ...


class GeminiStructuredClient:
    """Small adapter around Gemini structured output for prototype agents."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-flash-lite",
    ) -> None:
        resolved_key = api_key or os.getenv("GEMINI_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "GEMINI_API_KEY 환경변수가 없습니다. Google AI Studio에서 키를 만든 뒤 설정해 주세요."
            )

        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "google-genai 패키지가 없습니다. requirements.txt를 설치해 주세요."
            ) from exc

        self.model_name = model_name
        self._client = genai.Client(api_key=resolved_key)

    def generate(self, prompt: str, response_model: type[ResponseModel]) -> ResponseModel:
        interaction = self._client.interactions.create(
            model=self.model_name,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": response_model.model_json_schema(),
            },
        )
        if not interaction.output_text:
            raise RuntimeError("Gemini가 구조화 응답을 반환하지 않았습니다.")
        return response_model.model_validate_json(interaction.output_text)


class ToolSelectionItem(BaseModel):
    tool_name: ToolName
    selected: bool
    reason: str = Field(min_length=1)


class ToolSelectionResponse(BaseModel):
    decisions: list[ToolSelectionItem]


class LLMToolSelector(ToolSelector):
    def __init__(self, client: StructuredLLMClient) -> None:
        self.client = client
        self.agent_name = f"llm:{client.model_name}"

    def select(self, product) -> dict[ToolName, SelectionDecision]:
        tools = "\n".join(
            [
                "- customs_requirements: 수입 통관, HS 코드, 세관장 확인 요건",
                "- radio_compliance: 무선 통신 및 방송통신기자재 적합성평가",
                "- food_drug_safety: 식품 접촉, 화장품, 의료기기 및 효능 표방",
                "- electrical_safety: 전기용품, 배터리 및 생활용품 안전관리",
                "- children_product_safety: 어린이제품과 완구 안전관리",
                "- labeling_advertising_detection: 표시 및 광고 문구 위험",
            ]
        )
        prompt = f"""
당신은 한국에서 해외 상품을 판매하기 전 필요한 규제 검토 도구를 선택하는 분석 에이전트입니다.
실제 법률 결론을 내리지 말고, 아래 상품에 대해 추가 검토가 필요한 도구만 선택하세요.
신호가 불확실하지만 적용 가능성이 있으면 안전하게 선택하세요.

사용 가능한 도구:
{tools}

규칙:
1. 여섯 도구를 정확히 한 번씩 모두 반환하세요.
2. 해외 사입 프로토타입이므로 customs_requirements는 항상 선택하세요.
3. reason에는 상품의 어떤 사실 때문에 선택하거나 제외했는지 구체적으로 적으세요.
4. 출력은 제공된 JSON 스키마만 따르세요.

상품:
{product.model_dump_json(indent=2)}
""".strip()
        response = self.client.generate(prompt, ToolSelectionResponse)

        names = [item.tool_name for item in response.decisions]
        if len(names) != len(ToolName) or set(names) != set(ToolName):
            raise ValueError("LLM 선택 결과에는 서로 다른 6개 규제 도구가 모두 있어야 합니다.")

        return {
            item.tool_name: SelectionDecision(selected=item.selected, reason=item.reason)
            for item in response.decisions
        }


class LLMReviewIssue(BaseModel):
    severity: Literal["warning", "critical"]
    issue_type: VerificationIssueType
    description: str = Field(min_length=1)
    related_finding_ids: list[str] = Field(default_factory=list)
    recommended_action: str | None = None


class LLMReviewResponse(BaseModel):
    issues: list[LLMReviewIssue] = Field(default_factory=list)
    additional_tools_required: list[ToolName] = Field(default_factory=list)
    review_summary: str = Field(min_length=1)


class LLMVerificationAgent(VerificationAgent):
    """Combines invariant checks with an independent LLM review."""

    def __init__(
        self,
        client: StructuredLLMClient,
        safety_selector: ToolSelector | None = None,
    ) -> None:
        super().__init__(safety_selector or ToolSelector())
        self.client = client
        self.agent_name = f"llm:{client.model_name}+rules"

    def verify(self, draft: DraftAssessment) -> VerificationResult:
        baseline = super().verify(draft)
        prompt = f"""
당신은 규제 심사 프로토타입의 독립 검증 에이전트입니다.
아래 DraftAssessment에서 내부 모순, 상품 사실과 맞지 않는 도구 선택, 근거 없는 판단,
누락된 규제 검토 가능성을 찾으세요.

주의:
- 실제 법률 자문이나 새로운 법령 사실을 만들어내지 마세요.
- is_mock=true인 출처는 프로토타입 근거로 인정하고, Mock이라는 이유만으로 오류 처리하지 마세요.
- 판매 가능 여부가 아니라 결과의 완전성, 일관성, 추적 가능성을 검증하세요.
- critical은 재실행이나 수정 없이는 결과를 신뢰할 수 없을 때만 사용하세요.
- 출력은 제공된 JSON 스키마만 따르세요.

초안:
{draft.model_dump_json(indent=2)}
""".strip()
        review = self.client.generate(prompt, LLMReviewResponse)

        issues = list(baseline.issues)
        known = {(issue.issue_type, issue.description) for issue in issues}
        for item in review.issues:
            key = (item.issue_type, item.description)
            if key in known:
                continue
            issues.append(
                VerificationIssue(
                    severity=item.severity,
                    issue_type=item.issue_type,
                    description=item.description,
                    related_finding_ids=item.related_finding_ids,
                    recommended_action=item.recommended_action,
                )
            )
            known.add(key)

        additional_tools = list(
            dict.fromkeys([*baseline.additional_tools_required, *review.additional_tools_required])
        )
        if any(issue.severity == "critical" for issue in issues):
            status = VerificationStatus.REVISION_REQUIRED
        elif draft.follow_up_questions:
            status = VerificationStatus.USER_INPUT_REQUIRED
        elif issues:
            status = VerificationStatus.APPROVED_WITH_WARNINGS
        else:
            status = VerificationStatus.APPROVED

        return VerificationResult(
            status=status,
            review_summary=review.review_summary,
            issues=issues,
            additional_tools_required=additional_tools,
            follow_up_questions=draft.follow_up_questions,
            checked_finding_ids=[finding.finding_id for finding in draft.findings],
        )
