"""매장 기준 판별 — 규칙만 쓴다. LLM 호출 0건 (FR-030 · F-024).

판별 순서 (PRD 2.4.1)
  1. 요청 한 줄(마지막 줄)에 매장 이름이 있으면 그것이 우선이다
  2. 대화 본문에서 찾는다
  3. 지원 매장 1종 + 미지원/일반 표현이 함께 나오면 **되묻는다**
  4. 미지원 브랜드만 나오면 묻지 않고 generic + 안내 문구
  5. 아무것도 없으면 generic + "매장 이름이 없어" 문구

같은 매장의 별칭은 1종으로 센다 — resolved_brand_id 가 같으면 한 종류다.
"""

import re

from app import db
from app.services.text_norm import normalize

BRAND_LABEL = {"starbucks": "스타벅스 메뉴 기준", "generic": "일반 카페 메뉴 기준"}

CHANGE_HINT = {
    "starbucks": "다른 기준이면 채팅으로 '일반 카페로 해줘'라고 보내 주세요",
    "generic": "다른 기준이면 채팅으로 '스타벅스로 해줘'라고 보내 주세요",
}

BRAND_QUESTION_BASE = {
    "guide_text": "하나만 골라 주세요. 고르면 바로 정리를 시작해요",
    "cancel_text": "대화로 돌아가기",
}


def _dictionary() -> list[dict]:
    """brand_alias 전체. 긴 별칭을 먼저 본다 — '메가커피'가 '메가'보다 먼저 잡혀야 한다."""
    rows = db.fetch_all(
        "SELECT alias, resolved_brand_id, kind, display_name FROM app.brand_alias")
    for row in rows:
        row["_key"] = normalize(row["alias"])
    return sorted(rows, key=lambda r: -len(r["_key"]))


# 매장 별칭 "카페"를 품은 메뉴 · 옵션 낱말 — 매장 이름으로 세지 않는다 (2026-11-04 전체 흐름 확인).
#   "스타벅스 … 아이스 카페 라떼"가 매장 2종(스타벅스 · 카페)으로 읽혀 쓸데없는 매장 되묻기가 떴고,
#   채팅 "디카페인으로 바꿔줘"가 매장 기준 바꾸기("일반 카페로 새로 정리할까요?")로 읽혔다. 정규화된 글자에 적용한다
_MENU_WORDS = re.compile(r"디카페인?|카페(?=인|라떼|라테|모카|아메리카노|브레베|오레|콘파나)")


def _find(text: str, dictionary: list[dict]) -> list[dict]:
    """텍스트에서 찾은 별칭. 이미 잡힌 구간은 다시 세지 않는다."""
    haystack = _MENU_WORDS.sub("", normalize(text))
    hits, consumed = [], []
    for row in dictionary:
        key = row["_key"]
        if not key or key not in haystack:
            continue
        if any(key in other for other in consumed):
            continue    # '메가'가 '메가커피'에 삼켜진 경우
        consumed.append(key)
        hits.append(row)
    return hits


def _distinct_stores(hits: list[dict]) -> list[dict]:
    """같은 매장은 1종. display_name 기준으로 묶는다."""
    seen, out = set(), []
    for row in hits:
        if row["display_name"] in seen:
            continue
        seen.add(row["display_name"])
        out.append(row)
    return out


def resolve(raw_text: str) -> dict:
    """판별 결과.

    돌려주는 값
      {"needs_ask": True, "question": {...}}                       되묻기
      {"needs_ask": False, "brand_id", "source", "evidence_text",
       "store_name"}                                               확정
    """
    dictionary = _dictionary()
    lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]

    # 1 요청 한 줄 — 마지막 줄이 `[이름] 메시지` 형식이 아니면 요청 문장으로 본다
    if lines and not (lines[-1].startswith("[") and "]" in lines[-1]):
        request_line = lines[-1]
        hits = _distinct_stores(_find(request_line, dictionary))
        if hits:
            return _decide(hits, source="request", evidence=request_line)

    # 2 대화 본문
    hits = _distinct_stores(_find(raw_text, dictionary))
    if not hits:
        return {
            "needs_ask": False, "brand_id": "generic", "source": "default",
            "evidence_text": "매장 이름이 없어 일반 카페 메뉴로 정리했어요",
            "store_name": None,
        }
    return _decide(hits, source="chat", evidence=None)


def _decide(hits: list[dict], *, source: str, evidence: str | None) -> dict:
    supported = [h for h in hits if h["kind"] == "supported"]
    others = [h for h in hits if h["kind"] != "supported"]

    # 3 지원 매장과 다른 매장이 함께 나왔다 → 분석 전 1회 되묻는다 (오류가 아니다)
    if supported and others:
        names = " · ".join(h["display_name"] for h in hits)
        return {
            "needs_ask": True,
            "question": {
                **BRAND_QUESTION_BASE,
                "question_text": f"{names}가 함께 나와요. 어디 기준으로 정리할까요?",
                "options": [
                    {"value": "starbucks", "label": "스타벅스"},
                    {"value": "generic", "label": "일반 카페"},
                    {"value": "other", "label": "기타", "needs_store_name": True,
                     "hint_text": "메뉴가 아직 없는 매장이면 일반 카페 메뉴로 정리하고 "
                                  "예상 금액으로 보여줘요"},
                ],
            },
        }

    if supported:
        hit = supported[0]
        text = (f"'{evidence}'에서 찾았어요" if evidence
                else f"대화에서 '{hit['display_name']}'를 찾았어요")
        return {"needs_ask": False, "brand_id": hit["resolved_brand_id"],
                "source": source, "evidence_text": text, "store_name": None}

    # 4 미지원 · 일반 표현만 — 묻지 않는다
    hit = others[0]
    if hit["kind"] == "unsupported":
        return {"needs_ask": False, "brand_id": "generic", "source": "unsupported",
                "evidence_text": f"{hit['display_name']} 메뉴는 아직 없어 일반 카페 메뉴로 정리했어요",
                "store_name": hit["display_name"]}
    return {"needs_ask": False, "brand_id": "generic", "source": source,
            "evidence_text": f"'{hit['display_name']}' 기준으로 정리했어요", "store_name": None}


def projection(brand_id: str, source: str, evidence_text: str | None) -> dict:
    """화면이 그대로 쓰는 brand 블록 (D-02 2.4 — 화면이 조립하지 않는다)."""
    return {
        "id": brand_id,
        "label": BRAND_LABEL.get(brand_id, BRAND_LABEL["generic"]),
        "source": source,
        "evidence_text": evidence_text,
        "change_hint_text": CHANGE_HINT.get(brand_id, CHANGE_HINT["generic"]),
    }


# --- 채팅으로 매장 바꾸기 (API-022 → brand_change_ask) -----------------------
_CHANGE_VERB = ("로 해", "로해", "기준", "로 바꿔", "로바꿔", "으로 해", "으로 바꿔")


def detect_change_request(text: str) -> str | None:
    """"일반 카페로 해줘" → 'generic'. 아니면 None."""
    if not any(verb in (text or "") for verb in _CHANGE_VERB):
        return None
    hits = _find(text, _dictionary())
    if not hits:
        return None
    return hits[0]["resolved_brand_id"]
