"""파싱된 상품 신호를 규제 툴 선택 여부로 변환하는 안전 규칙."""

from dataclasses import dataclass

from .schemas import Product, ToolName


@dataclass(frozen=True)
class SelectionDecision:
    """툴 하나의 선택 여부와 추적 가능한 선택 사유."""

    selected: bool
    reason: str


class ToolSelector:
    """분석 에이전트의 툴 선택 규칙을 명시적으로 보여주는 프로토타입."""

    def select(self, product: Product) -> dict[ToolName, SelectionDecision]:
        """상품의 불리언 신호와 원문 키워드로 6개 툴을 모두 분류한다."""

        # 정형 필드가 누락되더라도 상품명·설명·추가 속성의 원문 신호를 보조로 쓴다.
        text = " ".join(
            filter(
                None,
                [
                    product.product_name,
                    product.category,
                    product.intended_use,
                    product.target_age,
                    *product.listing_text,
                    *(f"{item.name} {item.value}" for item in product.attributes),
                ],
            )
        ).lower()

        radio_signal = product.wireless is True or any(
            token in text for token in ("bluetooth", "블루투스", "wifi", "wi-fi", "무선", "2.4ghz")
        )
        electrical_signal = product.electrical_powered is True or product.battery_included is True
        food_drug_signal = any(
            value is True for value in (product.food_contact, product.medical_claim, product.cosmetic_claim)
        )
        child_signal = any(
            token in text for token in ("어린이", "유아", "아동", "완구", "개월", "세 이상", "세 미만")
        ) and "성인용" not in text
        ad_signal = bool(product.listing_text)

        # 통관은 기본 선택하고 나머지는 상품 신호가 있을 때만 선택한다.
        return {
            ToolName.CUSTOMS: SelectionDecision(True, "해외 사입 상품의 기본 통관 요건을 항상 확인"),
            ToolName.RADIO: SelectionDecision(radio_signal, "무선·주파수·통신 기능 신호 확인"),
            ToolName.FOOD_DRUG: SelectionDecision(
                food_drug_signal, "식품 접촉, 의료 효능 또는 화장품 표방 신호 확인"
            ),
            ToolName.ELECTRICAL: SelectionDecision(
                electrical_signal, "전기 사용 또는 배터리 포함 여부 확인"
            ),
            ToolName.CHILDREN: SelectionDecision(child_signal, "대상 연령 및 어린이·완구 표현 확인"),
            ToolName.LABEL_AD: SelectionDecision(ad_signal, "판매 상세페이지 문구가 있어 표시·광고 점검 가능"),
        }
