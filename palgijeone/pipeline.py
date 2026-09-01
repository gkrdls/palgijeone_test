from __future__ import annotations

from .aggregator import ResultAggregationTool
from .regulatory_tools import RegulatoryTool, build_default_tools
from .schemas import FinalAssessment, Product, ToolName, ToolResult, TraceEvent
from .selector import ToolSelector
from .verifier import VerificationAgent


class CompliancePipeline:
    def __init__(
        self,
        tools: dict[ToolName, RegulatoryTool] | None = None,
        selector: ToolSelector | None = None,
        aggregator: ResultAggregationTool | None = None,
        verifier: VerificationAgent | None = None,
    ) -> None:
        self.tools = tools or build_default_tools()
        self.selector = selector or ToolSelector()
        self.aggregator = aggregator or ResultAggregationTool()
        self.verifier = verifier or VerificationAgent(self.selector)

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
        record("analysis", "analysis_agent", "select_tools", "completed", ", ".join(selected))

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
                    status="failed",
                    selected=decision.selected,
                    selection_reason=decision.reason,
                    query={"product_id": product.product_id},
                    error=str(exc),
                )
            tool_results.append(result)
            record("tool", name.value, "complete", result.status.value, f"findings={len(result.findings)}")

        draft = self.aggregator.run(product, tool_results)
        record(
            "aggregation",
            "result_aggregation_tool",
            "aggregate",
            "completed",
            f"findings={len(draft.findings)}, status={draft.overall_status.value}",
        )

        verification = self.verifier.verify(draft)
        record(
            "verification",
            "verification_agent",
            "verify",
            verification.status.value,
            f"issues={len(verification.issues)}",
        )

        final = self.verifier.finalize(draft, verification)
        record(
            "output",
            "verification_agent",
            "finalize",
            final.verification_status.value,
            final.overall_status.value,
        )
        final.trace = trace
        return final

