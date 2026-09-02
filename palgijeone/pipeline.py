"""상품 입력부터 검증·재검사·최종 출력까지 연결하는 오케스트레이터."""

from __future__ import annotations

from .aggregator import ResultAggregationTool
from .regulatory_tools import RegulatoryTool, build_default_tools
from .schemas import (
    DraftAssessment,
    FinalAssessment,
    Product,
    ToolName,
    ToolResult,
    TraceEvent,
    VerificationIssue,
    VerificationIssueType,
    VerificationResult,
)
from .schemas import PipelineState, RemediationRecord, ToolStatus, VerificationStatus
from .selector import SelectionDecision, ToolSelector
from .verifier import VerificationAgent


class InvalidVerificationReferenceError(ValueError):
    """A verification issue references a finding outside the current draft."""


class CompliancePipeline:
    """분석 에이전트, 6개 규제 툴, 종합기와 검증 에이전트를 실행한다.

    `revision_required`이면 검증 결과가 지목한 툴만 다시 실행한다. 재검사 횟수는
    `max_remediation_attempts`로 제한해 LLM 판단이나 외부 API 오류로 인한 무한 루프를
    방지한다. `user_input_required`는 자동으로 해결할 수 없으므로 즉시 반환한다.
    """

    def __init__(
        self,
        tools: dict[ToolName, RegulatoryTool] | None = None,
        selector: ToolSelector | None = None,
        aggregator: ResultAggregationTool | None = None,
        verifier: VerificationAgent | None = None,
        max_remediation_attempts: int = 2,
    ) -> None:
        self.tools = tools or build_default_tools()
        self.selector = selector or ToolSelector()
        self.aggregator = aggregator or ResultAggregationTool()
        self.verifier = verifier or VerificationAgent(self.selector)
        if max_remediation_attempts < 0:
            raise ValueError("max_remediation_attempts는 0 이상이어야 합니다.")
        self.max_remediation_attempts = max_remediation_attempts

    def run(self, product: Product) -> FinalAssessment:
        """상품 하나를 입력받아 감사 가능한 실행 이력과 최종 진단을 반환한다."""

        trace: list[TraceEvent] = []

        def record(stage: str, component: str, action: str, status: str, detail: str) -> None:
            trace.append(
                TraceEvent(
                    sequence=len(trace) + 1,
                    stage=stage,
                    component=component,
                    action=action,
                    status=status,
                    detail=detail,
                )
            )

        record("input", "product_parser", "load_product", "completed", product.product_name or product.product_id)

        # 1) 파싱된 상품 신호를 바탕으로 실행할 규제 툴을 선택한다.
        decisions = self.selector.select(product)
        selected = [name.value for name, decision in decisions.items() if decision.selected]
        selector_name = getattr(self.selector, "agent_name", "rules")
        record(
            "analysis",
            "analysis_agent",
            "select_tools",
            "completed",
            f"agent={selector_name}; selected={', '.join(selected)}",
        )

        # 2) 여섯 툴을 모두 순회한다. 선택하지 않은 툴도 not_applicable로 기록한다.
        tool_results: list[ToolResult] = []
        for name in ToolName:
            tool = self.tools[name]
            decision = decisions[name]
            record("tool", name.value, "start_or_skip", "started", decision.reason)
            try:
                result = tool.execute(product, decision)
            except Exception as exc:  # 프로토타입에서 실패도 스키마로 전달
                result = ToolResult(
                    tool_name=name,
                    attempt=1,
                    status="failed",
                    selected=decision.selected,
                    selection_reason=decision.reason,
                    query={"product_id": product.product_id},
                    error=str(exc),
                )
            tool_results.append(result)
            record(
                "tool",
                name.value,
                "complete",
                result.status.value,
                f"attempt=1; findings={len(result.findings)}",
            )

        # 최신 결과와 전체 시도 이력을 분리한다. 재검사 시 최신 결과만 교체되고
        # tool_result_history에는 실패를 포함한 이전 결과가 계속 남는다.
        state = PipelineState(
            product=product,
            max_remediation_attempts=self.max_remediation_attempts,
            tool_results=tool_results,
            tool_result_history=list(tool_results),
        )

        # 3) 종합 → 검증 → 필요한 툴 재호출을 승인 또는 중단 상태까지 반복한다.
        while True:
            state.draft = self.aggregator.run(product, state.tool_results)
            record(
                "aggregation",
                "result_aggregation_tool",
                "aggregate",
                "completed",
                f"round={state.verification_round}; findings={len(state.draft.findings)}; "
                f"status={state.draft.overall_status.value}",
            )

            verification_failed = False
            try:
                state.verification = self.verifier.verify(state.draft)
                self._validate_verification_references(state.draft, state.verification)
                # A pending tool request cannot be treated as an approval.
                if state.verification.additional_tools_required:
                    state.verification.status = VerificationStatus.REVISION_REQUIRED
            except Exception as exc:
                verification_failed = True
                invalid_reference = isinstance(exc, InvalidVerificationReferenceError)
                issue_type = (
                    VerificationIssueType.INVALID_VERIFICATION_RESPONSE
                    if invalid_reference
                    else VerificationIssueType.VERIFICATION_FAILURE
                )
                description = (
                    "검증 응답의 finding 참조가 현재 초안과 일치하지 않습니다."
                    if invalid_reference
                    else f"검증을 완료하지 못했습니다 ({type(exc).__name__})."
                )
                # SDK exception messages can contain credentials or request contents.
                state.verification = VerificationResult(
                    status=VerificationStatus.REVISION_REQUIRED,
                    review_summary="검증 실패로 자동 처리를 중단했습니다. 기존 툴 결과는 보존됩니다.",
                    issues=[VerificationIssue(
                        severity="critical",
                        issue_type=issue_type,
                        description=description,
                        recommended_action=(
                            "현재 초안의 finding_id를 사용하도록 검증 응답을 수정하세요."
                            if invalid_reference
                            else "검증 서비스 연결 또는 응답 형식을 확인한 뒤 다시 실행하세요."
                        ),
                    )],
                    follow_up_questions=state.draft.follow_up_questions,
                )
            state.verification_history.append(state.verification.model_copy(deep=True))
            record(
                "verification",
                "verification_agent",
                "verify",
                "failed" if verification_failed else state.verification.status.value,
                f"round={state.verification_round}; "
                f"agent={getattr(self.verifier, 'agent_name', 'rules')}; "
                f"issues={len(state.verification.issues)}",
            )

            if verification_failed:
                record(
                    "remediation", "pipeline", "stop_retry", "verification_failed",
                    state.verification.issues[0].description,
                )
                break

            # 승인, 경고 승인, 사용자 입력 필요 상태는 자동 재검사 대상이 아니다.
            if state.verification.status != VerificationStatus.REVISION_REQUIRED:
                break

            if len(state.remediation_history) >= state.max_remediation_attempts:
                record(
                    "remediation",
                    "pipeline",
                    "stop_retry",
                    "exhausted",
                    f"max_remediation_attempts={state.max_remediation_attempts}",
                )
                break

            # 검증 결과에서 구조적으로 재실행할 수 있는 툴만 추출한다.
            retry_tools = self._retry_tools(state.draft, state.verification)
            if not retry_tools:
                record(
                    "remediation",
                    "pipeline",
                    "stop_retry",
                    "no_action_available",
                    "검증 결과에 재호출할 툴이 명시되지 않았습니다.",
                )
                break

            attempt = len(state.remediation_history) + 2
            retry_reason = self._retry_reason(state.verification)
            record(
                "remediation",
                "pipeline",
                "plan_retry",
                "started",
                f"attempt={attempt}; tools={', '.join(name.value for name in retry_tools)}",
            )

            # 재실행한 툴 결과만 교체하고 다른 툴의 최신 결과는 유지한다.
            current = {result.tool_name: result for result in state.tool_results}
            statuses: dict[ToolName, ToolStatus] = {}
            for name in retry_tools:
                decision = SelectionDecision(selected=True, reason=retry_reason)
                record("tool", name.value, "retry", "started", f"attempt={attempt}; {retry_reason}")
                try:
                    result = self.tools[name].execute(product, decision)
                    result.attempt = attempt
                except Exception as exc:
                    result = ToolResult(
                        tool_name=name,
                        attempt=attempt,
                        status=ToolStatus.FAILED,
                        selected=True,
                        selection_reason=retry_reason,
                        query={"product_id": product.product_id},
                        error=str(exc),
                    )
                current[name] = result
                state.tool_result_history.append(result)
                statuses[name] = result.status
                record(
                    "tool",
                    name.value,
                    "retry_complete",
                    result.status.value,
                    f"attempt={attempt}; findings={len(result.findings)}",
                )

            state.tool_results = [current[name] for name in ToolName]
            state.remediation_history.append(
                RemediationRecord(
                    iteration=attempt - 1,
                    trigger_status=VerificationStatus.REVISION_REQUIRED,
                    tools=retry_tools,
                    reason=retry_reason,
                    result_statuses=statuses,
                )
            )
            state.verification_round += 1

        assert state.draft is not None
        assert state.verification is not None
        # 4) 종료 시점의 최신 초안과 검증 결과에 전체 재검사 이력을 합친다.
        final = self.verifier.finalize(state.draft, state.verification)
        final.tool_result_history = state.tool_result_history
        final.verification_rounds = state.verification_round
        final.verification_history = state.verification_history
        final.remediation_history = state.remediation_history
        record(
            "output",
            "verification_agent",
            "finalize",
            final.verification_status.value,
            final.overall_status.value,
        )
        final.trace = trace
        return final

    @staticmethod
    def _validate_verification_references(
        draft: DraftAssessment, verification: VerificationResult
    ) -> None:
        finding_ids = {finding.finding_id for finding in draft.findings}
        references = {
            finding_id
            for issue in verification.issues
            for finding_id in issue.related_finding_ids
        } | set(verification.checked_finding_ids)
        if not references.issubset(finding_ids):
            raise InvalidVerificationReferenceError("Unknown finding reference")

    @staticmethod
    def _retry_tools(draft: DraftAssessment, verification: VerificationResult) -> list[ToolName]:
        """추가 요청, 툴 실패, critical finding을 재실행 대상 목록으로 합친다."""

        CompliancePipeline._validate_verification_references(draft, verification)
        requested = list(verification.additional_tools_required)
        requested.extend(
            result.tool_name
            for result in draft.tool_results
            if result.selected and result.status == ToolStatus.FAILED
        )

        finding_tools = {finding.finding_id: finding.tool_name for finding in draft.findings}
        for issue in verification.issues:
            if issue.severity != "critical":
                continue
            requested.extend(
                finding_tools[finding_id]
                for finding_id in issue.related_finding_ids
            )

        return list(dict.fromkeys(requested))

    @staticmethod
    def _retry_reason(verification: VerificationResult) -> str:
        """재호출된 ToolResult에 남길 사람이 읽을 수 있는 사유를 만든다."""

        critical_descriptions = [
            issue.description for issue in verification.issues if issue.severity == "critical"
        ]
        if critical_descriptions:
            return "검증 에이전트 재검사 요청: " + " | ".join(critical_descriptions)
        return "검증 에이전트가 추가 규제 툴 실행을 요청함"

