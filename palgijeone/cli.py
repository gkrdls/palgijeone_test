from __future__ import annotations

import argparse
import json

from .pipeline import CompliancePipeline
from .sample_products import SAMPLE_PRODUCTS, get_sample_product


def print_flow(result) -> None:
    print(f"\n상품: {result.product.product_name} ({result.product.product_id})")
    print("=" * 72)
    for event in result.trace:
        print(
            f"[{event.sequence:02d}] {event.stage:<12} | {event.component:<32} "
            f"| {event.status:<24} | {event.detail}"
        )
    print("-" * 72)
    print(f"종합 상태: {result.overall_status.value}")
    print(f"검증 상태: {result.verification_status.value}")
    print(f"판단 개수: {len(result.findings)}")
    print(f"필요 조치: {len(result.required_actions)}개")
    print(f"추가 질문: {len(result.follow_up_questions)}개")
    if result.verification.review_summary:
        print(f"검증 요약: {result.verification.review_summary}")
    if result.verification.issues:
        print("검증 이슈:")
        for issue in result.verification.issues:
            print(f"  - [{issue.severity}] {issue.description}")
    if result.follow_up_questions:
        for question in result.follow_up_questions:
            print(f"  - {question.question}")


def main() -> None:
    parser = argparse.ArgumentParser(description="팔기전에 규제 심사 흐름 프로토타입")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--product", choices=sorted(SAMPLE_PRODUCTS), help="실행할 테스트 상품 ID")
    group.add_argument("--all", action="store_true", help="모든 테스트 상품 실행")
    group.add_argument("--list", action="store_true", help="테스트 상품 목록")
    parser.add_argument("--json", action="store_true", help="최종 스키마 전체를 JSON으로 출력")
    parser.add_argument(
        "--agent-mode",
        choices=("rules", "llm"),
        default="rules",
        help="규칙 기반 또는 Gemini LLM 에이전트 사용",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash-lite",
        help="LLM 모드에서 사용할 Gemini 모델",
    )
    args = parser.parse_args()

    if args.list:
        for product_id, product in SAMPLE_PRODUCTS.items():
            print(f"{product_id:<26} {product.product_name}")
        return

    ids = list(SAMPLE_PRODUCTS) if args.all else [args.product or "wireless_rc_helicopter"]
    if args.agent_mode == "llm":
        from .llm_agents import GeminiStructuredClient, LLMToolSelector, LLMVerificationAgent

        try:
            client = GeminiStructuredClient(model_name=args.model)
        except RuntimeError as exc:
            parser.error(str(exc))
        pipeline = CompliancePipeline(
            selector=LLMToolSelector(client),
            verifier=LLMVerificationAgent(client),
        )
    else:
        pipeline = CompliancePipeline()
    results = [pipeline.run(get_sample_product(product_id)) for product_id in ids]

    if args.json:
        payload = results[0] if len(results) == 1 else results
        if isinstance(payload, list):
            print(json.dumps([item.model_dump(mode="json") for item in payload], ensure_ascii=False, indent=2))
        else:
            print(payload.model_dump_json(indent=2))
        return

    for result in results:
        print_flow(result)


if __name__ == "__main__":
    main()

