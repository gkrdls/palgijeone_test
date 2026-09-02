"""종합 결과의 구조적 불변 조건을 검사하고 최종 결과를 만드는 검증 에이전트."""

from collections import defaultdict

from .schemas import (
    Determination,
    DraftAssessment,
    FinalAssessment,
    FinalVerificationStatus,
    ToolName,
    ToolStatus,
    VerificationIssue,
    VerificationIssueType,
    VerificationResult,
    VerificationStatus,
)
from .selector import ToolSelector


class VerificationAgent:
    """종합 결과의 툴 누락, 근거 누락, 정보 부족 및 모순을 검사한다."""

    def __init__(self, selector: ToolSelector | None = None) -> None:
        self.selector = selector or ToolSelector()

    def verify(self, draft: DraftAssessment) -> VerificationResult:
        """툴 누락·실패, 근거 누락, 모순과 핵심 상품 정보 부족을 검사한다."""

        issues: list[VerificationIssue] = []
        expected_names = set(ToolName)
        actual_names = {result.tool_name for result in draft.tool_results}

        # 6개 중 제외된 툴도 not_applicable로 존재해야 전체 검토 여부를 감사할 수 있다.
        for missing_tool in sorted(expected_names - actual_names, key=lambda item: item.value):
            issues.append(
                VerificationIssue(
                    severity="critical",
                    issue_type=VerificationIssueType.MISSING_TOOL,
                    description=f"6개 툴 결과 중 {missing_tool.value} 결과가 없습니다.",
                    recommended_action="누락된 툴을 실행하거나 not_applicable 결과를 명시하세요.",
                )
            )

        # 안전 규칙으로 툴 선택을 다시 계산해 분석 에이전트의 누락을 독립적으로 확인한다.
        expected_selection = self.selector.select(draft.product)
        additional_tools: list[ToolName] = []
        by_name = {result.tool_name: result for result in draft.tool_results}
        for name, decision in expected_selection.items():
            result = by_name.get(name)
            if decision.selected and (result is None or not result.selected):
                additional_tools.append(name)
                issues.append(
                    VerificationIssue(
                        severity="critical",
                        issue_type=VerificationIssueType.MISSING_TOOL,
                        description=f"상품 신호상 필요한 {name.value} 툴이 선택되지 않았습니다.",
                        recommended_action=f"{name.value} 툴을 실행하세요.",
                    )
                )

        for result in draft.tool_results:
            if result.selected and result.status == ToolStatus.FAILED:
                issues.append(
                    VerificationIssue(
                        severity="critical",
                        issue_type=VerificationIssueType.TOOL_FAILURE,
                        description=f"선택된 {result.tool_name.value} 툴이 실패했습니다: {result.error}",
                        recommended_action="실패 원인을 해결하고 툴을 재호출하세요.",
                    )
                )

        # 확정 또는 가능성 판단에는 최소 한 개 이상의 법적 근거가 필요하다.
        for finding in draft.findings:
            needs_evidence = finding.determination in {
                Determination.REQUIRED,
                Determination.POSSIBLY_REQUIRED,
                Determination.NOT_REQUIRED,
            }
            if needs_evidence and not finding.legal_sources:
                issues.append(
                    VerificationIssue(
                        severity="critical",
                        issue_type=VerificationIssueType.MISSING_EVIDENCE,
                        description=f"'{finding.subject}' 판단에 법적 근거가 없습니다.",
                        related_finding_ids=[finding.finding_id],
                        recommended_action="근거 API를 다시 조회하고 출처를 연결하세요.",
                    )
                )

        determinations: dict[ToolName, set[Determination]] = defaultdict(set)
        ids_by_tool: dict[ToolName, list[str]] = defaultdict(list)
        for finding in draft.findings:
            determinations[finding.tool_name].add(finding.determination)
            ids_by_tool[finding.tool_name].append(finding.finding_id)
        for name, values in determinations.items():
            if Determination.REQUIRED in values and Determination.NOT_REQUIRED in values:
                issues.append(
                    VerificationIssue(
                        severity="critical",
                        issue_type=VerificationIssueType.CONTRADICTION,
                        description=f"{name.value} 결과에 required와 not_required가 동시에 존재합니다.",
                        related_finding_ids=ids_by_tool[name],
                        recommended_action="충돌하는 근거와 상품 사실을 다시 검토하세요.",
                    )
                )

        essential_missing = []
        if not draft.product.category:
            essential_missing.append("category")
        if not draft.product.intended_use:
            essential_missing.append("intended_use")
        if essential_missing:
            issues.append(
                VerificationIssue(
                    severity="warning",
                    issue_type=VerificationIssueType.INSUFFICIENT_PRODUCT_DATA,
                    description=f"핵심 상품 정보가 비어 있습니다: {', '.join(essential_missing)}",
                    recommended_action="사용자에게 추가 정보를 요청하세요.",
                )
            )

        critical = any(issue.severity == "critical" for issue in issues)
        if critical:
            status = VerificationStatus.REVISION_REQUIRED
        elif draft.follow_up_questions:
            status = VerificationStatus.USER_INPUT_REQUIRED
        elif issues:
            status = VerificationStatus.APPROVED_WITH_WARNINGS
        else:
            status = VerificationStatus.APPROVED

        return VerificationResult(
            status=status,
            issues=issues,
            additional_tools_required=additional_tools,
            follow_up_questions=draft.follow_up_questions,
            checked_finding_ids=[finding.finding_id for finding in draft.findings],
        )

    def finalize(self, draft: DraftAssessment, verification: VerificationResult) -> FinalAssessment:
        """세부 검증 상태를 사용자용 최종 상태로 변환해 결과를 생성한다."""

        if verification.status == VerificationStatus.APPROVED:
            final_status = FinalVerificationStatus.VERIFIED
        elif verification.status == VerificationStatus.APPROVED_WITH_WARNINGS:
            final_status = FinalVerificationStatus.VERIFIED_WITH_WARNINGS
        else:
            final_status = FinalVerificationStatus.INCOMPLETE

        return FinalAssessment(
            assessment_id=draft.assessment_id,
            product=draft.product,
            verification_status=final_status,
            overall_status=draft.overall_status,
            summary=draft.summary,
            selected_tools=draft.selected_tools,
            tool_results=draft.tool_results,
            findings=draft.findings,
            required_actions=draft.required_actions,
            missing_information=draft.missing_information,
            follow_up_questions=verification.follow_up_questions,
            verification=verification,
        )
