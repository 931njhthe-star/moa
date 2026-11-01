# 검사기 단위 테스트 — CI가 매 푸시마다 실행한다 (LLM 호출 없음: 빠르고 공짜)
from app.services.checker import check_rules

PRODUCT = {"name": "숲속 캠핑 의자", "price": "29,900원"}

GOOD_TEXT = (
    "숲속 캠핑 의자는 가벼워서 휴대하기 편합니다. "
    "접이식 디자인과 컵홀더를 갖췄으며 가격은 29,900원입니다. "
    "지금 만나보세요."
)


def test_correct_text_passes():
    assert check_rules(GOOD_TEXT, PRODUCT) == []


def test_missing_price_detected():
    text = GOOD_TEXT.replace(" 가격은 29,900원입니다.", "니다.")
    violations = check_rules(text, PRODUCT)
    assert any("R3" in v for v in violations)


def test_banned_word_detected():
    text = GOOD_TEXT.replace("가벼워서", "혁신적으로 가벼워서")
    violations = check_rules(text, PRODUCT)
    assert any("R4" in v for v in violations)


def test_sentence_count_detected():
    text = GOOD_TEXT.replace("편합니다. ", "편하고 ")
    violations = check_rules(text, PRODUCT)
    assert any("R1" in v for v in violations)


def test_missing_name_detected():
    text = GOOD_TEXT.replace("숲속 캠핑 의자는", "이 의자는")
    violations = check_rules(text, PRODUCT)
    assert any("R2" in v for v in violations)


def test_banned_punctuation_detected():
    text = GOOD_TEXT.replace("편합니다.", "편합니다!")
    violations = check_rules(text, PRODUCT)
    assert any("R5" in v for v in violations)


def test_comma_outside_price_detected():
    text = GOOD_TEXT.replace("가벼워서", "가볍고, 튼튼해서")
    violations = check_rules(text, PRODUCT)
    assert any("R6" in v for v in violations)


def test_wrong_ending_detected():
    text = GOOD_TEXT.replace("지금 만나보세요.", "지금 구매하세요.")
    violations = check_rules(text, PRODUCT)
    assert any("R7" in v for v in violations)


def test_digit_outside_price_detected():
    text = GOOD_TEXT.replace("컵홀더를", "컵홀더 2개를")
    violations = check_rules(text, PRODUCT)
    assert any("R8" in v for v in violations)
