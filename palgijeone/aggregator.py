from .schemas import (
    Determination,
    DraftAssessment,
    FollowUpQuestion,
    OverallStatus,
    Product,
    RiskLevel,
    ToolName,
    ToolResult,
    ToolStatus,
)


class ResultAggregationTool:
    """6개 툴 결과를 검증 에이전트 입력 스키마로 정규화한다."""

    def run(self, product: Product, tool_results: list[ToolResult]) -> DraftAssessment:
        findings = [finding for result in tool_results for finding in result.findings]
        selected_tools = [result.tool_name for result in tool_results if result.selected]
        actions = list(dict.fromkeys(action for result in tool_results for action in result.required_actions))
        missing = list(dict.fromkeys(item for result in tool_results for item in result.missing_information))

        questions = [
            FollowUpQuestion(
                question=f"'{item}' 정보를 확인해 주세요.",
                reason="규제 적용 여부를 확정하기 위해 추가 상품 정보가 필요합니다.",
                related_tools=[
                    result.tool_name for result in tool_results if item in result.missing_information
                ],
            )
            for item in missing
        ]

        if any(f.risk_level == RiskLevel.HIGH and f.determination != Determination.NOT_REQUIRED for f in findings):
            overall = OverallStatus.HIGH_RISK
        elif missing or any(f.determination == Determination.INSUFFICIENT_INFORMATION for f in findings):
            overall = OverallStatus.INSUFFICIENT_INFORMATION
        elif actions:
            overall = OverallStatus.ACTION_REQUIRED
        else:
            overall = OverallStatus.LIKELY_COMPLIANT

        failed = [r.tool_name.value for r in tool_results if r.status == ToolStatus.FAILED]
        summary = (
            f"6개 규제 툴 중 {len(selected_tools)}개를 선택했고, "
            f"{len(findings)}개의 정규화된 판단을 생성했습니다."
        )
        if failed:
            summary += f" 실패한 툴: {', '.join(failed)}."

        return DraftAssessment(
            product=product,
            selected_tools=selected_tools,
            tool_results=tool_results,
            findings=findings,
            overall_status=overall,
            summary=summary,
            required_actions=actions,
            missing_information=missing,
            follow_up_questions=questions,
            assumptions=["현재 규제 근거와 API 응답은 전체 흐름 확인을 위한 Mock 데이터임"],
        )

