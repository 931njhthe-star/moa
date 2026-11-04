"""정규화 — 별칭 조회 키를 만드는 한 지점 (D-07 10절 → D-09).

규칙이 여러 곳에 흩어지면 적재할 때와 조회할 때가 달라지고,
별칭이 "있는데 안 잡히는" 상태가 된다. 시드도 이 규칙으로 저장돼 있다.
"""

import re

_DROP = re.compile(r"[\s\-_·,.!?~()\[\]'\"]+")

# 표기 변형 → 메뉴 DB 표기 (D-08 0.1 — 임베딩 대신 이 표로 고친다). 정규화 뒤(공백 제거 뒤)에 적용한다.
# 메뉴 이름 · 별칭도 같은 함수를 지나므로 저장 쪽과 조회 쪽이 함께 맞춰진다. 긴 것부터 바꾼다
_VARIANTS = (
    ("마끼아또", "마키아토"), ("마끼아토", "마키아토"), ("마키아또", "마키아토"),
    ("라테", "라떼"),
    ("프라프치노", "프라푸치노"), ("프라푸치나", "프라푸치노"),
    ("초콜렛", "초콜릿"), ("쵸코", "초코"),
)


def normalize(text: str) -> str:
    """소문자 · 공백 · 기호 제거 · 표기 변형 통일."""
    key = _DROP.sub("", (text or "").strip().lower())
    for variant, canonical in _VARIANTS:
        key = key.replace(variant, canonical)
    return key


# 수량 — 한글 수사와 숫자를 함께 본다
_KO_NUM = {
    "한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4,
    "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
}
_QTY_DIGIT = re.compile(r"(-?\d+)\s*(?:잔|개|컵)")
_QTY_KO = re.compile(r"(" + "|".join(_KO_NUM) + r")\s*(?:잔|개|컵)")


def parse_quantity(text: str) -> int:
    """"2잔" · "한 잔" → 수량. 못 찾으면 1.

    **읽은 값을 그대로 돌려준다** — 0 · 음수 · 지나치게 큰 값도 깎지 않는다.
    예전에는 1 ~ 20 으로 잘라 "50잔"이 조용히 20잔, "0잔"이 1잔이 됐다(금액까지 틀림).
    범위 판정과 확인 질문은 호출자(intake)가 한다.
    """
    found = _QTY_DIGIT.search(text or "")
    if found:
        return int(found.group(1))
    found = _QTY_KO.search(text or "")
    if found:
        return _KO_NUM[found.group(1)]
    return 1
