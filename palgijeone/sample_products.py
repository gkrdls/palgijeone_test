"""규제 신호와 누락 정보 분기를 확인하기 위한 결정론적 테스트 상품."""

from .schemas import Attribute, Product


SAMPLE_PRODUCTS: dict[str, Product] = {
    "wireless_rc_helicopter": Product(
        product_id="wireless_rc_helicopter",
        product_name="2.4GHz 무선 RC 헬리콥터",
        category="완구/무선조종",
        intended_use="무선 조종 비행 완구",
        target_age="만 14세 이상",
        wireless=True,
        battery_included=True,
        electrical_powered=True,
        food_contact=False,
        medical_claim=False,
        cosmetic_claim=False,
        listing_text=["강력한 2.4GHz 조종", "어린이날 최고의 선물", "KC 인증 확인 필요"],
        attributes=[
            Attribute(name="주파수", value="2.4GHz", source_text="2.4GHz 무선 조종"),
            Attribute(name="배터리", value="리튬폴리머 배터리 포함"),
        ],
        source_url="https://example.com/products/rc-helicopter",
    ),
    "cosmetic_serum": Product(
        product_id="cosmetic_serum",
        product_name="비타민C 브라이트닝 세럼",
        category="화장품/세럼",
        intended_use="피부 미용",
        target_age="성인용",
        wireless=False,
        battery_included=False,
        electrical_powered=False,
        food_contact=False,
        medical_claim=False,
        cosmetic_claim=True,
        listing_text=["7일 만에 기미 완전 제거", "피부톤 개선에 도움", "순수 비타민C 함유"],
        attributes=[Attribute(name="용량", value="30ml"), Attribute(name="제형", value="세럼")],
        source_url="https://example.com/products/vitamin-serum",
    ),
    "stainless_tumbler": Product(
        product_id="stainless_tumbler",
        product_name="스테인리스 보온 텀블러",
        category="주방용품/텀블러",
        intended_use="음료 보관 및 음용",
        target_age="전 연령",
        wireless=False,
        battery_included=False,
        electrical_powered=False,
        food_contact=True,
        medical_claim=False,
        cosmetic_claim=False,
        listing_text=["하루 종일 완벽한 보온", "식품용 스테인리스 사용"],
        attributes=[Attribute(name="재질", value="스테인리스 304"), Attribute(name="용량", value="500ml")],
        source_url="https://example.com/products/tumbler",
    ),
    "adult_tshirt": Product(
        product_id="adult_tshirt",
        product_name="성인용 면 반팔 티셔츠",
        category="의류/티셔츠",
        intended_use="성인 의류",
        target_age="성인용",
        wireless=False,
        battery_included=False,
        electrical_powered=False,
        food_contact=False,
        medical_claim=False,
        cosmetic_claim=False,
        listing_text=["100% 순면", "국내 최저가"],
        attributes=[Attribute(name="소재", value="면 100%"), Attribute(name="제조국", value="중국")],
        source_url="https://example.com/products/tshirt",
    ),
    "unknown_smart_device": Product(
        product_id="unknown_smart_device",
        product_name="스마트 케어 디바이스",
        category=None,
        intended_use=None,
        target_age=None,
        wireless=True,
        battery_included=None,
        electrical_powered=True,
        food_contact=None,
        medical_claim=True,
        cosmetic_claim=None,
        listing_text=["통증을 치료하는 스마트 기기", "블루투스 앱 연동"],
        attributes=[Attribute(name="통신", value="Bluetooth")],
        source_url="https://example.com/products/unknown-device",
    ),
}


def get_sample_product(product_id: str) -> Product:
    """공유 테스트 데이터가 변경되지 않도록 선택한 상품의 깊은 복사본을 반환한다."""

    try:
        return SAMPLE_PRODUCTS[product_id].model_copy(deep=True)
    except KeyError as exc:
        choices = ", ".join(SAMPLE_PRODUCTS)
        raise KeyError(f"알 수 없는 상품 ID: {product_id}. 선택 가능: {choices}") from exc
