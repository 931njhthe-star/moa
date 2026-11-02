# 상품 소개문 규칙 검사기 — M1 Day 1에서 만든 것을 서비스 부품으로 재사용
import re

BANNED = ["최고", "완벽", "혁신", "프리미엄", "특별"]


def check_rules(text, product):
    """상품 소개문이 작성 규칙을 지켰는지 검사한다.

    반환값: 위반이 없으면 빈 리스트 [], 있으면 위반 내용 리스트
    """
    violations = []
    name = product["name"]
    price = product["price"]
    text = text.strip()

    if text.count(".") != 3:
        violations.append(f"R1 문장 수 위반: 마침표가 {text.count('.')}개입니다.")
    if name not in text:
        violations.append(f'R2 제품명 누락: "{name}"이 없습니다.')
    if price not in text:
        violations.append(f'R3 가격 누락: "{price}"이 없습니다.')
    used = [w for w in BANNED if w in text]
    if used:
        violations.append(f"R4 금지 단어 사용: {used}")
    marks = [m for m in ["!", "?"] if m in text]
    if marks:
        violations.append(f"R5 금지 문장부호 사용: {marks}")
    text_without_price = text.replace(price, "")
    if "," in text_without_price:
        violations.append("R6 가격 외의 쉼표 사용")
    if not text.endswith("지금 만나보세요."):
        violations.append('R7 마지막 문장은 "지금 만나보세요."여야 합니다.')
    if re.search(r"\d", text_without_price):
        violations.append("R8 가격 외의 숫자 사용")
    return violations