import unittest

from palgijeone.llm_agents import (
    LLMReviewResponse,
    LLMToolSelector,
    LLMVerificationAgent,
    ToolSelectionItem,
    ToolSelectionResponse,
)
from palgijeone.pipeline import CompliancePipeline
from palgijeone.sample_products import SAMPLE_PRODUCTS, get_sample_product
from palgijeone.schemas import FinalVerificationStatus, ToolName, ToolStatus, VerificationStatus
from palgijeone.selector import ToolSelector


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

