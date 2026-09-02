from __future__ import annotations

from .aggregator import ResultAggregationTool
from .regulatory_tools import RegulatoryTool, build_default_tools
from .schemas import FinalAssessment, Product, ToolName, ToolResult, TraceEvent
from .schemas import PipelineState, RemediationRecord, ToolStatus, VerificationStatus
from .selector import SelectionDecision, ToolSelector
from .verifier import VerificationAgent


class CompliancePipeline:
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

        state = PipelineState(
            product=product,
            max_remediation_attempts=self.max_remediation_attempts,
            tool_results=tool_results,
            tool_result_history=list(tool_results),
        )

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

            state.verification = self.verifier.verify(state.draft)
            record(
                "verification",
                "verification_agent",
                "verify",
                state.verification.status.value,
                f"round={state.verification_round}; "
                f"agent={getattr(self.verifier, 'agent_name', 'rules')}; "
                f"issues={len(state.verification.issues)}",
            )

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
        final = self.verifier.finalize(state.draft, state.verification)
        final.tool_result_history = state.tool_result_history
        final.verification_rounds = state.verification_round
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
    def _retry_tools(draft, verification) -> list[ToolName]:
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
                if finding_id in finding_tools
            )

        return list(dict.fromkeys(requested))

    @staticmethod
    def _retry_reason(verification) -> str:
        critical_descriptions = [
            issue.description for issue in verification.issues if issue.severity == "critical"
        ]
        if critical_descriptions:
            return "검증 에이전트 재검사 요청: " + " | ".join(critical_descriptions)
        return "검증 에이전트가 추가 규제 툴 실행을 요청함"

