"""동일한 ToolResult 계약을 따르는 6개 규제 툴의 Mock 구현.

현재 판단과 법적 근거는 흐름 검증용이다. 실제 연동 시 각 `run()`의 Mock 로직을
관세청·식약처·법제처 등의 API 호출로 교체하되 반환 스키마는 유지한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from .schemas import (
    AdvertisingAssessment,
    AdvertisingPhrase,
    ChildrenAssessment,
    CustomsAssessment,
    Determination,
    ElectricalAssessment,
    FoodDrugAssessment,
    LegalSource,
    Product,
    RadioAssessment,
    RegulatoryFinding,
    RiskLevel,
    ToolAssessment,
    ToolName,
    ToolResult,
    ToolStatus,
)
from .selector import SelectionDecision


def mock_source(name: str, law: str, article: str | None = None) -> LegalSource:
    """Mock 근거가 실제 법령 조회 결과로 오인되지 않도록 명시해 생성한다."""

    return LegalSource(
        source_name=name,
        law_name=law,
        article=article,
        quoted_text="프로토타입 흐름 검증용 가상 근거입니다. 실제 API 응답으로 교체해야 합니다.",
        source_url="https://example.com/mock-legal-source",
        is_mock=True,
    )


class RegulatoryTool(ABC):
    """모든 규제 툴이 구현해야 하는 공통 실행 인터페이스."""

    name: ToolName

    def execute(self, product: Product, decision: SelectionDecision) -> ToolResult:
        """선택된 툴만 실행하고 제외된 툴도 not_applicable 결과로 남긴다."""

        if not decision.selected:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.NOT_APPLICABLE,
                selected=False,
                selection_reason=decision.reason,
                query={"product_id": product.product_id},
                raw_response={"mock": True, "skipped": True},
            )
        return self.run(product, decision)

    @abstractmethod
    def run(self, product: Product, decision: SelectionDecision) -> ToolResult:
        """도메인별 규제 조회와 결과 정규화를 구현하는 확장 지점."""

        raise NotImplementedError

    def result(
        self,
        product: Product,
        decision: SelectionDecision,
        payload: ToolAssessment,
        findings: Iterable[RegulatoryFinding],
        actions: list[str] | None = None,
        missing: list[str] | None = None,
    ) -> ToolResult:
        """도메인 결과와 공통 finding을 표준 ToolResult로 감싼다."""

        return ToolResult(
            tool_name=self.name,
            status=ToolStatus.PARTIAL if missing else ToolStatus.SUCCESS,
            selected=True,
            selection_reason=decision.reason,
            query={"product_id": product.product_id, "category": product.category},
            result=payload,
            findings=list(findings),
            required_actions=actions or [],
            missing_information=missing or [],
            raw_response={"mock": True, "adapter": self.__class__.__name__},
        )


class CustomsRequirementsTool(RegulatoryTool):
    """통관, HS 코드와 세관장 확인 요건을 점검하는 툴."""

    name = ToolName.CUSTOMS

    def run(self, product: Product, decision: SelectionDecision) -> ToolResult:
        missing = [] if product.category else ["통관 품목 분류를 위한 상품 카테고리"]
        determination = Determination.INSUFFICIENT_INFORMATION if missing else Determination.POSSIBLY_REQUIRED
        finding = RegulatoryFinding(
            tool_name=self.name,
            subject="수입 통관 및 세관장 확인 요건",
            determination=determination,
            risk_level=RiskLevel.UNKNOWN if missing else RiskLevel.MEDIUM,
            summary="품목분류 및 세관장 확인대상 여부 확인이 필요합니다.",
            rationale="해외 사입 상품은 상품 특성과 HS 코드 후보에 따라 통관 요건이 달라집니다.",
            product_facts_used=[value for value in (product.product_name, product.category) if value],
            requirements=["HS 코드 후보 확인", "세관장 확인대상 여부 조회"],
            legal_sources=[mock_source("관세청", "관세법 및 세관장확인고시")],
            confidence=0.55 if missing else 0.78,
        )
        payload = CustomsAssessment(
            hs_code_candidates=[] if missing else ["분류 필요(예시 후보)"],
            customs_confirmation_required=None,
            applicable_requirements=["HS 코드 확정 후 세관장 확인대상 여부 조회"],
            required_documents=["제품 사양서", "거래명세 또는 인보이스"],
            legal_sources=finding.legal_sources,
        )
        return self.result(
            product,
            decision,
            payload,
            [finding],
            ["관세청 API로 HS 코드와 통관 요건 확인"],
            missing,
        )


class RadioComplianceTool(RegulatoryTool):
    """무선 기능과 방송통신기자재 적합성평가 가능성을 점검하는 툴."""

    name = ToolName.RADIO

    def run(self, product: Product, decision: SelectionDecision) -> ToolResult:
        finding = RegulatoryFinding(
            tool_name=self.name,
            subject="방송통신기자재 적합성평가",
            determination=Determination.POSSIBLY_REQUIRED,
            risk_level=RiskLevel.HIGH,
            summary="무선 기능이 확인되어 적합성평가 대상 여부를 확인해야 합니다.",
            rationale="상품 정보에서 무선 또는 주파수 사용 신호가 발견되었습니다.",
            product_facts_used=["wireless=true", *[f"{a.name}={a.value}" for a in product.attributes]],
            requirements=["무선 사양 확인", "적합등록·적합인증 대상 여부 조회"],
            legal_sources=[mock_source("국립전파연구원", "전파법", "적합성평가 관련 조항")],
            confidence=0.88,
        )
        frequencies = [a.value for a in product.attributes if "주파수" in a.name]
        payload = RadioAssessment(
            wireless_features=[a.value for a in product.attributes if a.name in {"통신", "주파수"}],
            frequency_bands=frequencies,
            conformity_assessment_required=None,
            certification_type=None,
            legal_sources=finding.legal_sources,
        )
        return self.result(
            product,
            decision,
            payload,
            [finding],
            ["정확한 모델명과 무선 모듈 사양 확보"],
        )


class FoodDrugSafetyTool(RegulatoryTool):
    """식품 접촉·화장품·의료 효능 표방을 식약처 영역에서 점검하는 툴."""

    name = ToolName.FOOD_DRUG

    def run(self, product: Product, decision: SelectionDecision) -> ToolResult:
        if product.medical_claim:
            subject, summary, risk = "의료기기 오인·표방", "치료 효능 문구에 대한 의료기기 해당성 검토가 필요합니다.", RiskLevel.HIGH
        elif product.cosmetic_claim:
            subject, summary, risk = "화장품 및 효능 표현", "화장품 유형·성분·효능 표현 검토가 필요합니다.", RiskLevel.HIGH
        else:
            subject, summary, risk = "식품용 기구·용기", "식품 접촉 재질의 기준·규격 검토가 필요합니다.", RiskLevel.MEDIUM
        finding = RegulatoryFinding(
            tool_name=self.name,
            subject=subject,
            determination=Determination.POSSIBLY_REQUIRED,
            risk_level=risk,
            summary=summary,
            rationale="상품 파싱 결과에서 식약처 소관 가능성이 있는 신호가 발견되었습니다.",
            product_facts_used=[
                f"food_contact={product.food_contact}",
                f"medical_claim={product.medical_claim}",
                f"cosmetic_claim={product.cosmetic_claim}",
            ],
            requirements=["제품 유형 및 원료·재질 확인", "식약처 규제정보 API 조회"],
            legal_sources=[mock_source("식품의약품안전처", "식품위생법·화장품법·의료기기법")],
            confidence=0.82,
        )
        categories = []
        if product.food_contact:
            categories.append("food_contact")
        if product.medical_claim:
            categories.append("medical_claim")
        if product.cosmetic_claim:
            categories.append("cosmetic")
        payload = FoodDrugAssessment(
            regulatory_categories=categories,
            regulated=None,
            detected_claims=product.listing_text if product.medical_claim or product.cosmetic_claim else [],
            ingredients_or_materials=[
                attribute.value
                for attribute in product.attributes
                if attribute.name in {"성분", "원료", "재질", "소재"}
            ],
            applicable_requirements=["제품 유형 확정 후 식약처 기준 조회"],
            legal_sources=finding.legal_sources,
        )
        return self.result(
            product,
            decision,
            payload,
            [finding],
            ["식약처 API에서 제품 유형별 요건 확인"],
        )


class ElectricalSafetyTool(RegulatoryTool):
    """전원과 배터리 정보를 바탕으로 전안법 적용 가능성을 점검하는 툴."""

    name = ToolName.ELECTRICAL

    def run(self, product: Product, decision: SelectionDecision) -> ToolResult:
        finding = RegulatoryFinding(
            tool_name=self.name,
            subject="전기용품 및 생활용품 안전관리",
            determination=Determination.POSSIBLY_REQUIRED,
            risk_level=RiskLevel.HIGH,
            summary="전원 또는 배터리 사용 상품으로 전안법상 안전관리 대상 여부 확인이 필요합니다.",
            rationale="electrical_powered 또는 battery_included 값이 참입니다.",
            product_facts_used=[
                f"electrical_powered={product.electrical_powered}",
                f"battery_included={product.battery_included}",
            ],
            requirements=["정격·전원 방식 확인", "안전인증·안전확인·공급자적합성 대상 구분"],
            legal_sources=[mock_source("국가기술표준원", "전기용품 및 생활용품 안전관리법")],
            confidence=0.84,
        )
        power_sources = []
        if product.electrical_powered:
            power_sources.append("electrical_power")
        if product.battery_included:
            power_sources.append("battery_included")
        payload = ElectricalAssessment(
            power_sources=power_sources,
            rated_specifications=[
                attribute.value
                for attribute in product.attributes
                if attribute.name in {"정격", "전압", "전류", "배터리"}
            ],
            safety_management_required=None,
            certification_type=None,
            legal_sources=finding.legal_sources,
        )
        return self.result(
            product,
            decision,
            payload,
            [finding],
            ["제품 정격 및 배터리 사양 확보"],
        )


class ChildrenProductSafetyTool(RegulatoryTool):
    """연령 원문과 실제 용도를 함께 사용해 어린이제품 여부를 점검하는 툴."""

    name = ToolName.CHILDREN

    def run(self, product: Product, decision: SelectionDecision) -> ToolResult:
        age = product.target_age or "연령 정보 없음"
        ambiguous = product.target_age is None or "14" in age
        determination = Determination.INSUFFICIENT_INFORMATION if ambiguous else Determination.POSSIBLY_REQUIRED
        missing = ["표시 연령과 실제 사용 목적의 관계"] if ambiguous else []
        finding = RegulatoryFinding(
            tool_name=self.name,
            subject="어린이제품 안전관리",
            determination=determination,
            risk_level=RiskLevel.UNKNOWN if ambiguous else RiskLevel.HIGH,
            summary="대상 연령 표현만으로 적용 여부를 확정하지 않고 실제 사용 목적을 함께 확인해야 합니다.",
            rationale=f"상품의 대상 연령 원문은 '{age}'입니다.",
            product_facts_used=[f"target_age={age}", f"category={product.category}"],
            requirements=["대상 연령 원문 보존", "어린이제품·완구 해당성 확인"],
            legal_sources=[mock_source("국가기술표준원", "어린이제품 안전 특별법")],
            confidence=0.58 if ambiguous else 0.8,
        )
        payload = ChildrenAssessment(
            target_age_raw=product.target_age,
            intended_for_children=None if ambiguous else True,
            product_type=product.category,
            safety_management_required=None,
            certification_type=None,
            legal_sources=finding.legal_sources,
        )
        return self.result(
            product,
            decision,
            payload,
            [finding],
            ["연령 표시와 실제 용도 교차 확인"],
            missing,
        )


class LabelAdvertisingDetectionTool(RegulatoryTool):
    """상세페이지에서 치료·절대·비교 표현과 입증 필요 문구를 탐지하는 툴."""

    name = ToolName.LABEL_AD
    RISKY_TERMS = ("완전 제거", "치료", "최저가", "100%", "완벽")

    def run(self, product: Product, decision: SelectionDecision) -> ToolResult:
        matched = [text for text in product.listing_text if any(term in text for term in self.RISKY_TERMS)]
        determination = Determination.POSSIBLY_REQUIRED if matched else Determination.NOT_REQUIRED
        risk = RiskLevel.HIGH if any("치료" in item or "완전 제거" in item for item in matched) else (
            RiskLevel.MEDIUM if matched else RiskLevel.LOW
        )
        finding = RegulatoryFinding(
            tool_name=self.name,
            subject="표시·광고 문구 위험 탐지",
            determination=determination,
            risk_level=risk,
            summary=f"검토가 필요한 문구 {len(matched)}건을 탐지했습니다." if matched else "규칙 기반 위험 문구가 탐지되지 않았습니다.",
            rationale="과장·절대적 표현 및 치료 효능 표현을 규칙 기반으로 탐지했습니다.",
            product_facts_used=matched,
            requirements=["문구의 객관적 입증자료 확인"] if matched else [],
            legal_sources=[mock_source("공정거래위원회", "표시·광고의 공정화에 관한 법률")],
            confidence=0.86,
        )
        phrases = [
            AdvertisingPhrase(
                text=text,
                risk_type="medical_or_absolute_claim"
                if "치료" in text or "완전 제거" in text
                else "absolute_or_comparative_claim",
                risk_level=RiskLevel.HIGH
                if "치료" in text or "완전 제거" in text
                else RiskLevel.MEDIUM,
                reason="치료 효능 또는 객관적 입증이 필요한 절대·비교 표현이 포함되었습니다.",
                evidence_required=True,
            )
            for text in matched
        ]
        payload = AdvertisingAssessment(
            reviewed_phrases=product.listing_text,
            detected_phrases=phrases,
            overall_risk=risk,
            legal_sources=finding.legal_sources,
        )
        return self.result(
            product,
            decision,
            payload,
            [finding],
            ["위험 문구 수정 또는 입증자료 확보"] if matched else [],
        )


def build_default_tools() -> dict[ToolName, RegulatoryTool]:
    """ToolName으로 즉시 조회할 수 있는 기본 툴 레지스트리를 생성한다."""

    tools: list[RegulatoryTool] = [
        CustomsRequirementsTool(),
        RadioComplianceTool(),
        FoodDrugSafetyTool(),
        ElectricalSafetyTool(),
        ChildrenProductSafetyTool(),
        LabelAdvertisingDetectionTool(),
    ]
    return {tool.name: tool for tool in tools}
