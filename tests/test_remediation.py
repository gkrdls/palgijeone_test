import unittest

from palgijeone.llm_agents import LLMReviewIssue, LLMReviewResponse, LLMVerificationAgent
from palgijeone.pipeline import CompliancePipeline
from palgijeone.regulatory_tools import build_default_tools
from palgijeone.sample_products import get_sample_product
from palgijeone.schemas import (
    FinalAssessment,
    FinalVerificationStatus,
    ToolName,
    ToolStatus,
    VerificationIssueType,
    VerificationResult,
    VerificationStatus,
)
from palgijeone.verifier import VerificationAgent


class ScriptedReviewClient:
    model_name = "offline-test"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, prompt, response_model):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response_model.model_validate(response)


class MissingEvidenceOnceTool:
    def __init__(self, delegate):
        self.delegate = delegate
        self.name = delegate.name
        self.calls = 0

    def execute(self, product, decision):
        self.calls += 1
        result = self.delegate.execute(product, decision)
        if self.calls == 1:
            for finding in result.findings:
                finding.legal_sources = []
        return result


class RemediationRegressionTest(unittest.TestCase):
    def run_reviews(self, *responses, **kwargs):
        client = ScriptedReviewClient(responses)
        result = CompliancePipeline(
            verifier=LLMVerificationAgent(client), **kwargs
        ).run(get_sample_product("adult_tshirt"))
        return result, client

    def test_llm_additional_tool_without_critical_is_executed(self):
        result, client = self.run_reviews(
            LLMReviewResponse(
                additional_tools_required=[ToolName.RADIO, ToolName.RADIO],
                review_summary="Check radio",
            ),
            LLMReviewResponse(review_summary="Complete"),
        )
        self.assertEqual(client.calls, 2)
        self.assertEqual(result.verification_status, FinalVerificationStatus.VERIFIED)
        self.assertEqual(result.remediation_history[0].tools, [ToolName.RADIO])
        radio = next(r for r in result.tool_results if r.tool_name == ToolName.RADIO)
        self.assertTrue(radio.selected)
        self.assertEqual(radio.status, ToolStatus.SUCCESS)
        self.assertEqual(result.tool_result_history[1].status, ToolStatus.NOT_APPLICABLE)
        self.assertEqual(len(result.tool_result_history), 7)
        self.assertEqual(result.verification_history[0].status, VerificationStatus.REVISION_REQUIRED)
        self.assertEqual(result.verification_history[-1].status, VerificationStatus.APPROVED)
        restored = FinalAssessment.model_validate_json(result.model_dump_json())
        self.assertEqual(len(restored.verification_history), 2)

    def test_additional_request_at_zero_budget_cannot_be_approved(self):
        result, client = self.run_reviews(
            LLMReviewResponse(additional_tools_required=[ToolName.RADIO], review_summary="Check radio"),
            max_remediation_attempts=0,
        )
        self.assertEqual(client.calls, 1)
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)
        self.assertEqual(result.verification.additional_tools_required, [ToolName.RADIO])
        self.assertTrue(any(e.status == "exhausted" for e in result.trace))

    def test_pipeline_rejects_approval_with_pending_request_from_custom_verifier(self):
        class InconsistentVerifier(VerificationAgent):
            def verify(self, draft):
                return VerificationResult(
                    status=VerificationStatus.APPROVED_WITH_WARNINGS,
                    additional_tools_required=[ToolName.RADIO],
                )

        result = CompliancePipeline(
            verifier=InconsistentVerifier(), max_remediation_attempts=0
        ).run(get_sample_product("adult_tshirt"))
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)

    def test_unknown_finding_id_is_explicit_verification_error(self):
        result, client = self.run_reviews(LLMReviewResponse(
            issues=[LLMReviewIssue(
                severity="critical",
                issue_type=VerificationIssueType.MISSING_EVIDENCE,
                description="Fix evidence",
                related_finding_ids=["invented-id"],
            )],
            review_summary="Needs correction",
        ))
        self.assertEqual(client.calls, 1)
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)
        self.assertEqual(result.verification.issues[0].issue_type,
                         VerificationIssueType.INVALID_VERIFICATION_RESPONSE)
        self.assertEqual(result.remediation_history, [])
        self.assertEqual(result.verification.checked_finding_ids, [])
        self.assertTrue(any(e.status == "verification_failed" for e in result.trace))
        self.assertFalse(any(e.status == "no_action_available" for e in result.trace))

    def test_unknown_checked_finding_id_is_rejected(self):
        class InvalidCheckedIdsVerifier(VerificationAgent):
            def verify(self, draft):
                return VerificationResult(
                    status=VerificationStatus.APPROVED,
                    checked_finding_ids=["invented-id"],
                )

        result = CompliancePipeline(verifier=InvalidCheckedIdsVerifier()).run(
            get_sample_product("adult_tshirt")
        )
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)
        self.assertEqual(result.verification.issues[0].issue_type,
                         VerificationIssueType.INVALID_VERIFICATION_RESPONSE)

    def test_valid_critical_reference_still_retries_and_preserves_history(self):
        tools = build_default_tools()
        tools[ToolName.CUSTOMS] = MissingEvidenceOnceTool(tools[ToolName.CUSTOMS])
        result = CompliancePipeline(tools=tools).run(get_sample_product("adult_tshirt"))
        self.assertEqual(result.verification_status, FinalVerificationStatus.VERIFIED)
        self.assertEqual(tools[ToolName.CUSTOMS].calls, 2)
        first = result.verification_history[0]
        self.assertEqual(first.issues[0].issue_type, VerificationIssueType.MISSING_EVIDENCE)
        self.assertEqual(first.issues[0].related_finding_ids,
                         [result.tool_result_history[0].findings[0].finding_id])
        self.assertEqual(result.verification_history[-1].issues, [])

    def test_first_verification_failure_returns_incomplete_with_tools(self):
        result, client = self.run_reviews(TimeoutError("sensitive-request-data"))
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)
        self.assertEqual(client.calls, 1)
        self.assertEqual(len(result.tool_results), 6)
        self.assertEqual(len(result.tool_result_history), 6)
        self.assertEqual(len(result.verification_history), 1)
        self.assertEqual(result.verification.issues[0].issue_type,
                         VerificationIssueType.VERIFICATION_FAILURE)
        self.assertIn("TimeoutError", result.verification.issues[0].description)
        self.assertNotIn("sensitive-request-data", result.model_dump_json())
        self.assertEqual(result.trace[-1].action, "finalize")

    def test_second_verification_failure_keeps_previous_review_and_retry(self):
        result, client = self.run_reviews(
            LLMReviewResponse(additional_tools_required=[ToolName.CUSTOMS], review_summary="Recheck"),
            TimeoutError("sensitive-request-data"),
        )
        self.assertEqual(client.calls, 2)
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)
        self.assertEqual(result.verification_rounds, 2)
        self.assertEqual(len(result.verification_history), 2)
        self.assertEqual(result.verification_history[0].review_summary, "Recheck")
        self.assertEqual(len(result.remediation_history), 1)
        self.assertEqual(len(result.tool_result_history), 7)
        self.assertEqual(result.tool_result_history[-1].attempt, 2)
        self.assertEqual(result.verification.checked_finding_ids, [])

    def test_malformed_llm_response_is_not_treated_as_approval(self):
        result, _ = self.run_reviews({"issues": "not-an-array", "review_summary": "Bad"})
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)
        self.assertIn("ValidationError", result.verification.issues[0].description)

    def test_failure_preserves_questions_for_missing_product_data(self):
        client = ScriptedReviewClient([TimeoutError("offline")])
        result = CompliancePipeline(verifier=LLMVerificationAgent(client)).run(
            get_sample_product("unknown_smart_device")
        )
        self.assertEqual(result.verification_status, FinalVerificationStatus.INCOMPLETE)
        self.assertTrue(result.follow_up_questions)
        self.assertTrue(result.missing_information)


if __name__ == "__main__":
    unittest.main()
