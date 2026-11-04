"""주문 검증 — 규칙이 판정하고, LLM 은 **보조 검토**다 (PRD 5.1 · P-01 REQ-004 ①).

협상 불가 규칙
  `validation_status='passed'` 는 `rule_verdict='passed'` 일 때만 나올 수 있다.
  LLM 의견만으로 통과한 항목은 **0건이어야 한다** — D-07 4.5 의 금지 조합이고
  Q-01 이 그 질의로 REQ-004 ① 을 판정한다. 이 모듈이 그 불변식을 지키는 지점이다.
"""

from app.services import menu as menu_service

# P-03 2.2 확인 필요 사유 — Q-02 가 사유별로 채점하므로 문자열을 바꾸지 않는다
REVIEW_REASON_TEXT = {
    "ambiguous_spec": "사이즈를 확인해 주세요",
    "trait_expression": "메뉴를 골라 주세요",
    "reference_menu": "메뉴를 확인해 주세요",
    "unregistered_menu": "메뉴를 확인해 주세요",
    "ambiguous_target": "어느 주문인지 확인해 주세요",
    # 대리 주문 주문자 — "서연이"가 참여자 박서연인지 담당자가 확인한다(2026-11-04 · INT-002)
    "ambiguous_person": "누구 주문인지 확인해 주세요",
}


SPEC_REASON_TEXT = {
    "temperature": "따뜻한 것인지 아이스인지 확인해 주세요",
    "size": "사이즈를 확인해 주세요",
    "quantity": "수량을 확인해 주세요",
}


def validate_item(item: dict, *, brand_id: str, menu_version: str) -> dict:
    """항목 1건의 규칙 판정.

    돌려주는 값에 `rule_verdict` · `validation_status` · `review_reason` 이 들어간다.
    LLM 보조 검토는 `rule_verdict == 'undecided'` 인 항목에만 요청한다.
    """
    reasons: list[str] = []

    # 1 메뉴가 정해졌는가
    if not item.get("menu_id"):
        reasons.append(item.get("match_reason") or "unregistered_menu")

    # 2 참조 주문("그걸로") — 사람이 확인해야 한다.
    #   단 **메뉴가 그 메시지 자체로 확정된 항목은 뺀다.** 참조 표현이 섞여 있어도
    #   ("나도 아아 톨") 별칭으로 메뉴를 맞춘 항목은 다른 주문과 똑같이 자립한다. 그런데도
    #   물으면 왼쪽 패널에는 아이스 아메리카노가 들어가 있는데 질문은 앞선 대화 후보를 들고
    #   "메뉴를 골라 주세요"가 되어 화면이 서로 어긋난다(2026-11-03). 진짜 참조는 메뉴가
    #   정해지지 않아 위 규칙 1이 `match_reason='reference_menu'` 로 잡는다
    if item.get("reference") and not item.get("menu_id") and not item.get("confirmed_by_person"):
        reasons.append("reference_menu")

    # 3 모호한 사양 표현이 남아 있는가
    if item.get("ambiguous_options"):
        reasons.append("ambiguous_spec")

    # 3-1 대리 주문 주문자를 아직 확인하지 않았는가 — 후보가 있어도 사람이 맞다고 하기 전에는 잇지 않는다
    if item.get("person_check"):
        reasons.append("ambiguous_person")

    # 4 특성 표현만 있고 메뉴가 안 정해졌는가
    if item.get("traits") and not item.get("menu_id"):
        reasons.append("trait_expression")

    # 5 옵션이 화이트리스트에 있는가 — 없는 키는 규칙 실패다 (통과가 아니다)
    invalid = [
        f"{group}={value}"
        for group, value in (item.get("options") or {}).items()
        if not menu_service.is_valid_option(brand_id, menu_version, group, value,
                                            menu_id=item.get("menu_id"))
    ]

    # 6 수량
    quantity_bad = int(item.get("quantity") or 1) <= 0

    if invalid or quantity_bad:
        return {
            "rule_verdict": "failed",
            "validation_status": "failed",
            "review_reason": "ambiguous_spec" if invalid else None,
            "review_reason_text": "옵션을 다시 골라 주세요" if invalid else "수량을 확인해 주세요",
            "rule_notes": invalid or ["quantity<=0"],
        }

    if reasons:
        reason = _primary(reasons)
        text = REVIEW_REASON_TEXT.get(reason, "확인해 주세요")
        if reason == "ambiguous_spec":
            # 사유는 하나(P-03)지만 화면 문구는 무엇이 모호한지 말한다
            from app.services.questions import spec_key
            text = SPEC_REASON_TEXT.get(spec_key(item.get("ambiguous_options")), text)
        return {
            "rule_verdict": "undecided",
            "validation_status": "needs_review",
            "review_reason": reason,
            "review_reason_text": text,
            "rule_notes": reasons,
        }

    return {
        "rule_verdict": "passed",
        "validation_status": "passed",
        "review_reason": None,
        "review_reason_text": None,
        "rule_notes": [],
    }


def _primary(reasons: list[str]) -> str:
    """사유가 여러 개면 담당자에게 물을 것 하나를 고른다. 순서가 규칙이다."""
    # 특성 표현이 먼저다 — "달달한 걸로"는 메뉴 이름이 없어 미등록으로도 걸리는데, 미등록 질문은
    # 후보가 0개라 담당자가 고를 것이 없다. 특성 후보(trait_tags 정렬)를 띄워야 답할 수 있다(D-16 INT-011)
    # 주문자 확인은 맨 뒤다 — 메뉴 · 사양을 먼저 정하고, 그 답 뒤의 후속 질문(edits._follow_up)으로 묻는다
    for reason in ("trait_expression", "unregistered_menu", "reference_menu",
                   "ambiguous_spec", "ambiguous_target", "ambiguous_person"):
        if reason in reasons:
            return reason
    return reasons[0]


def apply_llm_review(verdict: dict, llm_verdict: str | None) -> dict:
    """LLM 보조 검토 결과를 얹는다.

    `agree` · `disagree` · `unavailable` 중 무엇이 와도 **통과로 올리지 않는다.**
    보조 검토는 문구를 다듬고 사유를 바꿀 수 있을 뿐, 판정 권한이 없다.
    `unavailable`(호출 실패)이어도 규칙 판정으로 그대로 진행한다 (PRD 5.1).
    """
    out = {**verdict, "llm_review_verdict": llm_verdict}
    if verdict["rule_verdict"] != "passed":
        out["validation_status"] = (
            "failed" if verdict["rule_verdict"] == "failed" else "needs_review")
    return out


def assert_invariant(rows: list[dict]) -> list[str]:
    """금지 조합 검사 — 0건이어야 한다 (D-07 4.5 · REQ-004 ①).

    돌려주는 값: 위반한 item_id 목록. 비어 있어야 정상이다.
    """
    return [
        row["item_id"] for row in rows
        if not row.get("removed")
        and row.get("validation_status") == "passed"
        and row.get("rule_verdict") != "passed"
    ]
