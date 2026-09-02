import unittest

from palgijeone.llm_agents import (
    LLMReviewResponse,
    LLMToolSelector,
    LLMVerificationAgent,
    ToolSelectionItem,
    ToolSelectionResponse,
)
from palgijeone.pipeline import CompliancePipeline
from palgijeone.regulatory_tools import build_default_tools
from palgijeone.sample_products import SAMPLE_PRODUCTS, get_sample_product
from palgijeone.schemas import (
    AdvertisingAssessment,
    ChildrenAssessment,
    CustomsAssessment,
    ElectricalAssessment,
    FinalVerificationStatus,
    FoodDrugAssessment,
    RadioAssessment,
    ToolName,
    ToolStatus,
    VerificationResult,
    VerificationStatus,
)
from palgijeone.selector import ToolSelector
from palgijeone.verifier import VerificationAgent


class FakeStructuredLLMClient:
    model_name = "fake-structured-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt, response_model):
        self.prompts.append(prompt)
        if response_model is ToolSelectionResponse:
            product = get_sample_product("adult_tshirt")
            decisions = ToolSelector().select(product)
            return ToolSelectionResponse(
                decisions=[
                    ToolSelectionItem(
                        tool_name=name,
                        selected=decision.selected,
                        reason=decision.reason,
                    )
                    for name, decision in decisions.items()
                ]
            )
        if response_model is LLMReviewResponse:
            return LLMReviewResponse(issues=[], review_summary="내부 일관성 검토 완료")
        raise AssertionError(f"예상하지 못한 응답 모델: {response_model}")


class FlakyTool:
    def __init__(self, delegate, failures: int) -> None:
        self.delegate = delegate
        self.name = delegate.name
        self.failures = failures
        self.calls = 0

    def execute(self, product, decision):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("테스트용 일시적 툴 오류")
        return self.delegate.execute(product, decision)


class AdditionalToolOnceVerifier(VerificationAgent):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def verify(self, draft):
        self.calls += 1
        if self.calls == 1:
            return VerificationResult(
                status=VerificationStatus.REVISION_REQUIRED,
                additional_tools_required=[ToolName.CUSTOMS],
                checked_finding_ids=[finding.finding_id for finding in draft.findings],
            )
        return super().verify(draft)


class CompliancePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = CompliancePipeline()

    def test_all_samples_produce_six_tool_results_and_final_output(self) -> None:
        for product in SAMPLE_PRODUCTS.values():
            with self.subTest(product=product.product_id):
                result = self.pipeline.run(product)
                completed_tools = [event for event in result.trace if event.action == "complete"]
                self.assertEqual(len(completed_tools), 6)
                self.assertEqual(set(event.component for event in completed_tools), {name.value for name in ToolName})
                self.assertTrue(result.assessment_id)
                self.assertTrue(result.trace)

    def test_wireless_rc_selects_expected_tools(self) -> None:
        result = self.pipeline.run(get_sample_product("wireless_rc_helicopter"))
        completed = {event.component: event.status for event in result.trace if event.action == "complete"}
        self.assertEqual(completed[ToolName.RADIO.value], ToolStatus.SUCCESS.value)
        self.assertEqual(completed[ToolName.ELECTRICAL.value], ToolStatus.SUCCESS.value)
        self.assertEqual(completed[ToolName.CHILDREN.value], ToolStatus.PARTIAL.value)
        self.assertEqual(completed[ToolName.FOOD_DRUG.value], ToolStatus.NOT_APPLICABLE.value)

    def test_each_selected_tool_returns_its_typed_assessment(self) -> None:
        expected_types = {
            ToolName.CUSTOMS: CustomsAssessment,
            ToolName.RADIO: RadioAssessment,
            ToolName.FOOD_DRUG: FoodDrugAssessment,
            ToolName.ELECTRICAL: ElectricalAssessment,
            ToolName.CHILDREN: ChildrenAssessment,
            ToolName.LABEL_AD: AdvertisingAssessment,
        }

        results_by_tool = {}
        for product in SAMPLE_PRODUCTS.values():
            result = self.pipeline.run(product)
            self.assertEqual(len(result.tool_results), 6)
            for tool_result in result.tool_results:
                if tool_result.selected:
                    results_by_tool.setdefault(tool_result.tool_name, tool_result)
                    self.assertIsInstance(tool_result.result, expected_types[tool_result.tool_name])
                else:
                    self.assertIsNone(tool_result.result)

        self.assertEqual(set(results_by_tool), set(ToolName))

    def test_final_schema_version_is_v0_3(self) -> None:
        result = self.pipeline.run(get_sample_product("adult_tshirt"))
        self.assertEqual(result.schema_version, "0.3.0")
        self.assertEqual(len(result.tool_results), 6)

    def test_adult_tshirt_skips_unrelated_tools(self) -> None:
        result = self.pipeline.run(get_sample_product("adult_tshirt"))
        completed = {event.component: event.status for event in result.trace if event.action == "complete"}
        self.assertEqual(completed[ToolName.CUSTOMS.value], ToolStatus.SUCCESS.value)
        self.assertEqual(completed[ToolName.LABEL_AD.value], ToolStatus.SUCCESS.value)
        self.assertEqual(completed[ToolName.RADIO.value], ToolStatus.NOT_APPLICABLE.value)
        self.assertEqual(completed[ToolName.CHILDREN.value], ToolStatus.NOT_APPLICABLE.value)
        self.assertEqual(result.verification_status, FinalVerificationStatus.VERIFIED)

    def test_missing_product_information_reaches_verifier(self) -> None:
        result = self.pipeline.run(get_sample_product("unknown_smart_device"))
        self.assertEqual(result.verification.status, VerificationStatus.USER_INPUT_REQUIRED)
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)
        self.assertTrue(result.follow_up_questions)
        self.assertTrue(result.verification.issues)
        self.assertEqual(result.verification_rounds, 1)
        self.assertEqual(result.remediation_history, [])

    def test_failed_tool_is_retried_then_reaggregated_and_reverified(self) -> None:
        tools = build_default_tools()
        flaky_customs = FlakyTool(tools[ToolName.CUSTOMS], failures=1)
        tools[ToolName.CUSTOMS] = flaky_customs

        result = CompliancePipeline(tools=tools).run(get_sample_product("adult_tshirt"))

        self.assertEqual(flaky_customs.calls, 2)
        self.assertEqual(result.verification_rounds, 2)
        self.assertEqual(len(result.remediation_history), 1)
        self.assertEqual(result.remediation_history[0].tools, [ToolName.CUSTOMS])
        self.assertEqual(len(result.tool_result_history), 7)
        customs = next(item for item in result.tool_results if item.tool_name == ToolName.CUSTOMS)
        self.assertEqual(customs.status, ToolStatus.SUCCESS)
        self.assertEqual(customs.attempt, 2)
        self.assertEqual(result.verification_status, FinalVerificationStatus.VERIFIED)

    def test_additional_tools_required_is_executed(self) -> None:
        tools = build_default_tools()
        counting_customs = FlakyTool(tools[ToolName.CUSTOMS], failures=0)
        tools[ToolName.CUSTOMS] = counting_customs
        verifier = AdditionalToolOnceVerifier()

        result = CompliancePipeline(tools=tools, verifier=verifier).run(
            get_sample_product("adult_tshirt")
        )

        self.assertEqual(counting_customs.calls, 2)
        self.assertEqual(verifier.calls, 2)
        self.assertEqual(result.verification_rounds, 2)

    def test_retry_loop_stops_at_configured_limit(self) -> None:
        tools = build_default_tools()
        always_failing_customs = FlakyTool(tools[ToolName.CUSTOMS], failures=99)
        tools[ToolName.CUSTOMS] = always_failing_customs

        result = CompliancePipeline(tools=tools, max_remediation_attempts=1).run(
            get_sample_product("adult_tshirt")
        )

        self.assertEqual(always_failing_customs.calls, 2)
        self.assertEqual(result.verification_rounds, 2)
        self.assertEqual(len(result.remediation_history), 1)
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)
        exhausted = [event for event in result.trace if event.status == "exhausted"]
        self.assertEqual(len(exhausted), 1)

    def test_llm_agents_use_two_structured_calls(self) -> None:
        client = FakeStructuredLLMClient()
        result = CompliancePipeline(
            selector=LLMToolSelector(client),
            verifier=LLMVerificationAgent(client),
        ).run(get_sample_product("adult_tshirt"))

        self.assertEqual(len(client.prompts), 2)
        self.assertEqual(result.verification_status, FinalVerificationStatus.VERIFIED)
        self.assertEqual(result.verification.review_summary, "내부 일관성 검토 완료")
        analysis_event = next(event for event in result.trace if event.action == "select_tools")
        verification_event = next(event for event in result.trace if event.action == "verify")
        self.assertIn("llm:fake-structured-model", analysis_event.detail)
        self.assertIn("llm:fake-structured-model+rules", verification_event.detail)


if __name__ == "__main__":
    unittest.main()

