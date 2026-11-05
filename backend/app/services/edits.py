"""담당자 수정 — 확인 질문 답변 · 행 편집 · 채팅 해석 · 되돌리기.

네 경로가 모두 같은 일을 한다: 항목을 고치고 · 재검증하고 · 금액을 다시 재고 ·
변경 이력을 남기고 · 세션 version 을 올린다. 경로마다 따로 구현하면
한 곳을 빠뜨렸을 때 **그 경로에서만 조용히 깨진다** — 그래서 `_commit` 하나로 모은다.
"""

import json
import re

from app import config, db, logging_setup
from app.services import brand as brand_service
from app.services import changes, intake
from app.services import menu as menu_service
from app.services import questions, sessions, settlement, validation
from app.services.text_norm import normalize, parse_quantity


class Conflict(Exception):
    """If-Match 가 어긋났다 — 호출자가 409 를 돌려준다."""

    def __init__(self, current: int):
        super().__init__(current)
        self.current = current


class NotApplicable(Exception):
    """되돌릴 수 없다 · 고칠 수 없다 — 호출자가 422 를 돌려준다."""


def _guard(session: dict) -> None:
    """그래프 밖에서 항목을 바꾸는 곳(확인 질문 답 · 개별 바꾸기 · 되돌리기)도 **N-10 과 같은 함수**를 지난다.

    검사를 복사하지 않는다 — 같은 함수를 부른다(D-12 6.2). D-16 이 호출 지점 수를 센다.
    """
    from app.graph.nodes import guard_items

    guard_items(session)


def _revalidate(cur, session: dict, item_id: str) -> dict:
    """항목 1건을 다시 판정하고 금액을 다시 잰다. 수정 경로가 모두 이것을 부른다."""
    brand_id, menu_version = session["brand_id"], session["menu_version"]
    cur.execute(
        "SELECT i.*, m.name AS menu_name FROM app.order_item i "
        "  LEFT JOIN app.menu m ON m.menu_id = i.menu_id "
        " WHERE i.session_id = %s AND i.item_id = %s",
        (session["session_id"], item_id))
    row = cur.fetchone()
    if not row:
        raise NotApplicable(item_id)
    if row.get("removed"):
        # 빠진 항목은 판정 대상이 아니다 — 금액도 다시 재지 않는다("주문 아니에요"로 뺀 항목)
        return dict(row)

    verdict = validation.validate_item(
        {**row, "reference": False, "traits": [],
         "confirmed_by_person": True,       # 사람이 직접 고친 항목은 참조 사유가 해소된다
         "match_reason": None if row["menu_id"] else "unregistered_menu"},
        brand_id=brand_id, menu_version=menu_version)
    verdict = validation.apply_llm_review(verdict, row.get("llm_review_verdict"))
    unit, estimated = settlement.item_price(row, brand_id=brand_id, menu_version=menu_version)

    cur.execute(
        "UPDATE app.order_item SET validation_status = %s, rule_verdict = %s, "
        "       review_reason = %s, review_reason_text = %s, unit_price = %s, "
        "       estimated_price = %s, updated_at = NOW() "
        " WHERE session_id = %s AND item_id = %s",
        (verdict["validation_status"], verdict["rule_verdict"], verdict["review_reason"],
         verdict["review_reason_text"], unit, estimated, session["session_id"], item_id))
    return {**row, **verdict, "unit_price": unit, "estimated_price": estimated}


def _commit(cur, session: dict, *, expected_version: int | None) -> int:
    """세션 상태를 정리하고 version 을 올린다. 모든 수정 경로의 출구다."""
    session_id = session["session_id"]
    version = sessions.bump_version(cur, session_id, expected_version)
    if version is None:
        cur.execute("SELECT version FROM app.order_session WHERE session_id = %s",
                    (session_id,))
        raise Conflict(cur.fetchone()["version"])

    cur.execute(
        "SELECT COUNT(*) AS n FROM app.order_item "
        " WHERE session_id = %s AND removed = false AND validation_status <> 'passed'",
        (session_id,))
    pending = int(cur.fetchone()["n"])
    if session["status"] not in ("completed", "failed"):
        sessions.set_status(cur, session_id,
                            "needs_review" if pending else "awaiting_confirmation")

    cur.execute(
        "SELECT i.*, m.name AS menu_name FROM app.order_item i "
        "  LEFT JOIN app.menu m ON m.menu_id = i.menu_id "
        " WHERE i.session_id = %s AND i.removed = false", (session_id,))
    rows = cur.fetchall()
    settlement.save_lines(session_id, version, settlement.compute_lines(rows), cur=cur)
    return version


# --- API-021 확인 질문 답변 ---------------------------------------------------
def answer_question(session: dict, question_id: str, answer: str, *,
                    expected_version: int | None, extra_options: dict | None = None) -> dict:
    session_id = session["session_id"]

    with db.transaction() as cur:
        cur.execute(
            "SELECT * FROM app.review_question "
            " WHERE session_id = %s AND question_id = %s AND status = 'open'",
            (session_id, question_id))
        question = cur.fetchone()
        if not question:
            raise NotApplicable(question_id)

        cur.execute("SELECT * FROM app.order_item WHERE session_id = %s AND item_id = %s",
                    (session_id, question["item_id"]))
        before = cur.fetchone()
        before_text = _row_text(before, session)

        _apply_answer(cur, session, question, answer, extra_options)
        cur.execute("UPDATE app.review_question "
                    "   SET status = 'answered', chosen_value = %s, answered_at = NOW() "
                    " WHERE question_id = %s", (answer, question_id))

        after = _revalidate(cur, session, question["item_id"])
        _close_suggestion(cur, session_id, question_id, answer)
        _follow_up(cur, session, after)
        token = changes.record(cur, session_id, method="question_answer",
                               item_id=question["item_id"], who=before["person"],
                               before_text=before_text, after_text=_row_text(after, session),
                               before_json=_row_json(before), after_json=_row_json(after))
        version = _commit(cur, session, expected_version=expected_version)

    _guard(session)
    stats = questions.counts(session_id)
    return {
        "text": _applied_text(question, answer, before["person"]),
        "undo_token": token,
        "changed_item_ids": [question["item_id"]],
        "version": version,
        "remaining": stats["remaining"],
    }


def _close_suggestion(cur, session_id: str, question_id: str, answer: str) -> None:
    """답장 제안에서 올라온 질문을 답하면 그 제안도 결정된 것이다 (2026-11-05 3차 보고 7번).

    닫지 않으면 `pending` 으로 남아 공유 게이트가 계속 막는다 — 담당자에게는 풀 방법이 보이지 않는다.
    """
    cur.execute("UPDATE app.suggestion SET status = %s, decided_at = NOW() "
                " WHERE session_id = %s AND question_id = %s AND status = 'pending'",
                ("ignored" if answer == questions.TARGET_KEEP else "applied",
                 session_id, question_id))


def answer_from_text(session: dict, question_id: str, text: str, *,
                     expected_version: int | None) -> dict:
    """API-021 (text) — 질문이 열려 있을 때 채팅으로 친 말을 **그 질문의 답**으로 읽는다 (2026-11-04 사용자 보고 3 · 4).

    예전에는 질문이 떠 있어도 채팅이 채팅 수정(API-022)으로만 가서, "아이스아메리카노"처럼 사람 이름이 없는 말은
    "어느 주문을 말하는지 찾지 못했어요"가 됐고 질문은 그대로 남았다. 답으로 읽지 못하면 NotApplicable 을 올린다 —
    화면이 그때 채팅 수정으로 넘긴다. 반영은 버튼 답과 **같은 함수**(answer_question)를 지난다.
    """
    question = db.fetch_one(
        "SELECT q.*, i.person, i.ambiguous_options FROM app.review_question q "
        "  JOIN app.order_item i ON i.session_id = q.session_id AND i.item_id = q.item_id "
        " WHERE q.session_id = %s AND q.question_id = %s AND q.status = 'open'",
        (session["session_id"], question_id))
    if not question:
        raise NotApplicable(question_id)
    value = _text_answer(session, question, text)
    key = questions.spec_key(question["ambiguous_options"]) if question["reason"] == "ambiguous_spec" else None
    # 메뉴를 고르는 답이면 함께 적은 옵션(사이즈 · 얼음 등)도 받는다. 사이즈 · 수량 질문은 답 자체가 그 값이다
    extra = intake._options(text) if key is None and question["reason"] not in ("ambiguous_person",) else None
    result = answer_question(session, question_id, value, expected_version=expected_version,
                             extra_options=extra)
    label = next((o.get("label") for o in question["options"] or [] if str(o.get("value")) == value), value)
    return {**result, "answer": value, "answer_label": label}


_TARGET_KEEP_WORDS = re.compile(r"아니|그대로|놔\s*두|괜찮|안\s*바꿔")
_TARGET_APPLY_WORDS = re.compile(r"^\s*(?:네|넵|넹|예|응|어|ㅇㅇ|맞아|맞아요|맞습니다|그거|바꿔|반영)")


def _text_answer(session: dict, question: dict, text: str) -> str:
    """채팅 문장 → 질문의 답 값(버튼 value 또는 메뉴 이름). 못 읽으면 NotApplicable."""
    brand_id, menu_version = session["brand_id"], session["menu_version"]
    said = (text or "").strip()
    options = question["options"] or []
    reason = question["reason"]
    if not said:
        raise NotApplicable(text)

    # 다른 사람 이름이 들어 있으면 이 질문의 답이 아니다 — "박서연 벤티로"는 박서연 주문 수정이다
    people = {r["person"] for r in db.fetch_all(
        "SELECT DISTINCT person FROM app.order_item WHERE session_id = %s AND removed = false",
        (session["session_id"],))}
    if any(p and p != question["person"] and p in said for p in people):
        raise NotApplicable(text)

    if reason == "ambiguous_person":
        names = [str(o["value"]) for o in options]
        hit = [n for n in names[:-1] if n in said]
        if len(hit) == 1:
            return hit[0]
        if names and _TARGET_KEEP_WORDS.search(said):
            return names[-1]
        raise NotApplicable(text)

    key = questions.spec_key(question["ambiguous_options"]) if reason == "ambiguous_spec" else None
    values = {str(o["value"]) for o in options}
    if key == "size":
        size = intake._options(said).get("size")
        if size and size in values:
            return size
    elif key == "quantity":
        digits = re.fullmatch(r"\s*(\d+)\s*(?:잔|개|컵)?\s*(?:이요|요|으로|로)?[.!~]*\s*", said)
        quantity = int(digits.group(1)) if digits else parse_quantity(said)
        if quantity > 0 and (digits or re.search(r"잔|개|컵", said)):
            return str(quantity)
        raise NotApplicable(text)
    elif key == "temperature":
        hint = intake.temperature_hint(said)
        picks = [o for o in options if hint and o["label"].startswith("아이스") == (hint == "ice")]
        if len(picks) == 1:
            return str(picks[0]["value"])
    elif reason == "ambiguous_target":
        if _TARGET_KEEP_WORDS.search(said) and questions.TARGET_KEEP in values:
            return questions.TARGET_KEEP
        if _TARGET_APPLY_WORDS.search(said) and questions.TARGET_APPLY in values:
            return questions.TARGET_APPLY

    if questions.NO_ORDER in values and re.search(r"주문\s*아니|아니에요|아닙니다|빼\s*주|뺄게|취소", said):
        return questions.NO_ORDER

    # 버튼 라벨을 그대로 친 경우 — 긴 라벨부터("아이스 카페 라떼"가 "카페 라떼"보다 먼저)
    said_key = normalize(said)
    for option in sorted(options, key=lambda o: -len(normalize(o.get("label") or ""))):
        label_key = normalize(option.get("label") or "")
        if len(label_key) >= 2 and label_key in said_key:
            return str(option["value"])
    if key in ("size", "quantity"):
        raise NotApplicable(text)

    # 메뉴 이름 — 채팅 수정과 같은 매칭(엄격 아님 · 되돌리기가 있다). 온도 단서로 아이스 · 따뜻한 판을 고른다.
    # 이름을 그대로 친 경우가 가장 흔하므로 이름 일치를 먼저 본다(별칭 충돌 회피 · 보고 2번)
    said_menu = intake._menu_text(said) or said
    hit = menu_service.by_name(brand_id, menu_version, said_menu)         or menu_service.match(brand_id, menu_version, said_menu)
    hit = menu_service.with_temperature(brand_id, menu_version, hit, intake.temperature_hint(said))
    if hit.get("menu_id"):
        return hit["name"]
    raise NotApplicable(text)


def _apply_answer(cur, session, question, answer: str, extra_options: dict | None = None) -> None:
    """답이 사이즈인가 메뉴인가에 따라 다른 컬럼을 고친다."""
    brand_id, menu_version = session["brand_id"], session["menu_version"]
    item_id = question["item_id"]

    if question["reason"] == "ambiguous_person":
        # 대리 주문 주문자 — 질문 버튼에 있던 이름만 받는다(후보 참여자 · "그대로 둘게요"의 원래 표현)
        allowed = {str(o.get("value")) for o in question.get("options") or []}
        if str(answer) not in allowed:
            raise NotApplicable(answer)
        cur.execute("UPDATE app.order_item SET person = %s, person_check = NULL, updated_at = NOW() "
                    " WHERE session_id = %s AND item_id = %s", (answer, session["session_id"], item_id))
        return

    if answer == questions.NO_ORDER:
        # [주문 아니에요, 뺄게요] — 메뉴를 알아듣지 못한 항목을 뺀다(보고 2번). 지우지 않고 removed 로 둔다
        cur.execute("UPDATE app.order_item SET removed = true, updated_at = NOW() "
                    " WHERE session_id = %s AND item_id = %s", (session["session_id"], item_id))
        questions.void_for_item(session["session_id"], item_id, cur=cur)
        return

    if question["reason"] == "ambiguous_target" and answer in (questions.TARGET_APPLY, questions.TARGET_KEEP):
        # [네, 바꿔 주세요] — 질문이 들고 있는 변경 문장을 이 항목에 반영한다(채팅 수정과 같은 함수).
        # [그대로 둘게요] — 고칠 것 없이 확인만 끝낸다(재검증이 대상 모호 사유를 지운다)
        change = next((o.get("change_text") for o in question.get("options") or []
                       if o.get("value") == questions.TARGET_APPLY), None)
        if answer == questions.TARGET_APPLY and change:
            cur.execute("SELECT * FROM app.order_item WHERE session_id = %s AND item_id = %s",
                        (session["session_id"], item_id))
            _apply_text_change(cur, session, cur.fetchone(), change)
        return

    cur.execute("SELECT options, ambiguous_options, custom_request FROM app.order_item "
                " WHERE session_id = %s AND item_id = %s", (session["session_id"], item_id))
    current = cur.fetchone()
    options = dict(current["options"] or {})
    ambiguous = dict(current["ambiguous_options"] or {})
    key = questions.spec_key(ambiguous) if question["reason"] == "ambiguous_spec" else None

    def save(**columns):
        # 답한 사양만 지운다 — 통째로 비우면 남은 모호 사양(수량 등)이 조용히 확정된다
        sets = ", ".join(f"{name} = %s" for name in columns)
        values = [json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v
                  for v in columns.values()]
        cur.execute(f"UPDATE app.order_item SET {sets} WHERE session_id = %s AND item_id = %s",
                    (*values, session["session_id"], item_id))

    if key == "size":
        # 답은 사이즈 라벨("그란데")이다 → option_value 로 되돌린다
        value = _option_value(brand_id, menu_version, "size", answer)
        if value is None:
            raise NotApplicable(answer)
        ambiguous.pop("size")
        save(options={**options, "size": value}, ambiguous_options=ambiguous)
        return

    if key == "quantity":
        try:
            quantity = int(str(answer).replace("잔", "").strip())
        except ValueError:
            raise NotApplicable(answer)
        if quantity <= 0:
            raise NotApplicable(answer)
        ambiguous.pop("quantity")
        save(quantity=quantity, ambiguous_options=ambiguous)
        return

    # 메뉴를 고른 경우(온도 확인 포함) — **이름을 먼저** 본다(2026-11-05 2차 보고 2번).
    # 버튼 라벨은 메뉴 이름인데, 그 이름이 다른 메뉴의 별칭이기도 하면 match() 가 후보 2개로 보고 거부한다
    # ("카라멜 마키아또" → 카라멜 마키아또 · 아이스 카라멜 마키아또). 메뉴 이름이 온도를 품으므로 온도도 정해진다
    matched = menu_service.by_name(brand_id, menu_version, answer)         or menu_service.match(brand_id, menu_version, answer)
    if not matched.get("menu_id"):
        raise NotApplicable(answer)
    ambiguous.pop("temperature", None)
    # 채팅으로 답하며 함께 적은 옵션("아이스 아메리카노 그란데로") — 고른 메뉴에 있는 값만 받는다
    for group, value in (extra_options or {}).items():
        if menu_service.is_valid_option(brand_id, menu_version, group, value, menu_id=matched["menu_id"]):
            options[group] = value
            ambiguous.pop(group, None)
    # 고른 메뉴에 그 종류가 없는 옵션은 기타 요청으로 옮긴다 — 분석 경로(sessions._spec_checks)와 같은 규칙
    options, moved = menu_service.split_unoffered(brand_id, menu_version, options, matched["menu_id"])
    if moved:
        save(custom_request=intake.move_to_custom(current.get("custom_request"), moved))
    options = fit_size(brand_id, menu_version, options, matched["menu_id"])
    # 메뉴가 정해지면 기본 사이즈를 채운다 — 분석 경로(graph.nodes.match_one)와 같은 규칙이다.
    # 채우지 않으면 사이즈 칩 없이 금액만 나와, 매장에 보여 줄 주문서가 불완전해진다
    # (최유나 · 정하준 행에 사이즈가 비어 있었다 — 2026-11-03 확인)
    if "size" not in options and not ambiguous.get("size"):
        default_size = menu_service.default_option(brand_id, menu_version, "size",
                                                   menu_id=matched["menu_id"])
        if default_size:
            options = {**options, "size": default_size}
    save(menu_id=matched["menu_id"], menu_text=matched["name"], options=options,
         ambiguous_options=ambiguous)


def _follow_up(cur, session: dict, row: dict) -> None:
    """답한 뒤에도 모호한 사양이 남으면 다음 질문을 하나 더 만든다.

    질문은 항목당 하나씩 만들어 두므로, 사양 두 개(사이즈 + 수량)가 모호한 항목은
    첫 답 뒤 **물을 질문이 없어 확인 필요로 영원히 남는다** — 공유가 막힌다.
    """
    # 사양이 남았거나 주문자 확인이 남았으면 묻는다 — 주문자 확인은 사유 우선순위 맨 뒤라 앞 답 뒤에야 차례가 온다
    if row.get("removed"):
        return
    if row.get("validation_status") != "needs_review" or not (
            questions.spec_key(row.get("ambiguous_options")) or row.get("review_reason") == "ambiguous_person"):
        return
    # 되묻기 상한 (D-12 7절 · CLAUDE.md 협상 불가) — 항목당 질문 MAX_REASK 개. 넘으면 더 묻지 않고
    # 확인 필요로 둔 채 개별 바꾸기로 넘긴다. 없으면 답이 새 모호함을 낳을 때 질문이 끝없이 이어진다
    cur.execute("SELECT COUNT(*) AS n FROM app.review_question "
                " WHERE session_id = %s AND item_id = %s", (session["session_id"], row["item_id"]))
    if cur.fetchone()["n"] >= config.MAX_REASK:
        logging_setup.log("route_decision", session_id=session["session_id"], source="answer",
                          item_id=row["item_id"], reask_limit=config.MAX_REASK)
        return
    cur.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM app.review_question "
                " WHERE session_id = %s", (session["session_id"],))
    seq = cur.fetchone()["seq"]
    built = questions.build({**row, "candidates": []}, session_id=session["session_id"],
                            brand_id=session["brand_id"], menu_version=session["menu_version"],
                            seq=seq)
    questions.insert(session["session_id"], [built], cur=cur)


def fit_size(brand_id: str, menu_version: str, options: dict, menu_id: str) -> dict:
    """메뉴를 바꾼 뒤 지금 사이즈가 새 메뉴에 없으면 새 메뉴의 기본 사이즈로 맞춘다 (2026-11-04 전체 흐름 확인).

    아이스 아메리카노(톨)를 망고 바나나 블렌디드(그란데만)로 바꾸면 "톨"이 남아 옵션 오류("옵션을 다시 골라 주세요")가
    됐다. 사이즈 종류가 아예 없는 메뉴(에스프레소)는 사이즈를 뺀다. 사이즈를 정하지 않은 행은 건드리지 않는다.
    """
    size = (options or {}).get("size")
    if not size or menu_service.is_valid_option(brand_id, menu_version, "size", size, menu_id=menu_id):
        return options
    out = {k: v for k, v in options.items() if k != "size"}
    default = menu_service.default_option(brand_id, menu_version, "size", menu_id=menu_id)
    return {**out, "size": default} if default else out


def _option_value(brand_id, menu_version, group, label) -> str | None:
    catalog = menu_service.catalog(brand_id, menu_version)
    for opt in catalog["options"]:
        if opt["option_group"] == group and (opt["value_label"] == label
                                             or opt["option_value"] == label):
            return opt["option_value"]
    return None


def _applied_text(question: dict, answer: str, person: str) -> str:
    """"전 → 후" 안내 — 서버가 완성형으로 준다.

    **버튼의 표시 이름(label)을 쓴다.** 값(value)을 쓰면 "tall로 했어요"처럼 내부 값이 담당자 화면에
    뜬다(F-013 — D-05 확인 2026-11-03). 질문 행에 버튼 목록이 저장돼 있으므로 거기서 찾는다.
    """
    if question.get("reason") == "ambiguous_person":
        return f"{answer} 님 주문으로 정했어요."
    if answer == questions.TARGET_APPLY:
        return f"{person} 님 주문에 반영했어요."
    if answer == questions.TARGET_KEEP:
        return f"{person} 님 주문을 그대로 뒀어요."
    if answer == questions.NO_ORDER:
        return f"{person} 님 주문을 뺐어요."
    label = next((option.get("label") for option in (question.get("options") or [])
                  if str(option.get("value")) == str(answer)), None) or answer
    return f"{person} 님 주문을 {label}{_ro(label)} 했어요."


def _ro(word: str) -> str:
    """조사 '로/으로' — 받침이 없거나 ㄹ 받침이면 '로'(톨로 · 그란데로), 그 밖은 '으로'(3잔으로)."""
    last = (word or "").strip().rstrip(")]」'\" ")[-1:]      # "아이스 카페 라떼 (톨)" 은 톨을 본다
    if not last or not ("가" <= last <= "힣"):
        return "로"
    jong = (ord(last) - 0xAC00) % 28
    return "로" if jong in (0, 8) else "으로"


# --- API-023 행 편집 ----------------------------------------------------------
ALLOWED_CHANGES = {"options", "custom_request", "menu_id", "menu_name", "quantity", "removed"}


def patch_item(session: dict, item_id: str, payload: dict, *,
               expected_version: int | None) -> dict:
    """사양 · 옵션 · 기타 요청 · 메뉴 바꾸기 · 빼기.

    옵션은 **화이트리스트에 있는 키만** 받는다. 없는 키는 거른다 (API-023).
    """
    session_id = session["session_id"]
    brand_id, menu_version = session["brand_id"], session["menu_version"]

    unknown = set(payload) - ALLOWED_CHANGES
    if unknown:
        raise NotApplicable(f"unknown fields: {sorted(unknown)}")

    options = payload.get("options")
    if options:
        # 바꿀 메뉴가 있으면 그 메뉴, 없으면 지금 메뉴 기준으로 본다 — 메뉴 이름으로 바꾸는 경우는
        # 반영 뒤 재검증(_revalidate → validate_item)이 같은 규칙으로 다시 거른다
        menu_id = payload.get("menu_id") or (db.fetch_one(
            "SELECT menu_id FROM app.order_item WHERE session_id = %s AND item_id = %s",
            (session["session_id"], item_id)) or {}).get("menu_id")
        bad = [f"{g}={v}" for g, v in options.items()
               if not menu_service.is_valid_option(brand_id, menu_version, g, v, menu_id=menu_id)]
        if bad:
            raise NotApplicable(f"unknown options: {bad}")

    with db.transaction() as cur:
        cur.execute(
            "SELECT i.*, m.name AS menu_name FROM app.order_item i "
            "  LEFT JOIN app.menu m ON m.menu_id = i.menu_id "
            " WHERE i.session_id = %s AND i.item_id = %s", (session_id, item_id))
        before = cur.fetchone()
        if not before:
            raise NotApplicable(item_id)
        before_text = _row_text(before, session)

        sets, params = [], []
        # 고친 사양의 모호 표시만 지운다 (사이즈를 골랐다고 수량 확인까지 사라지면 안 된다)
        ambiguous = dict(before["ambiguous_options"] or {})
        resolved = set(options or {}) | ({"quantity"} if "quantity" in payload else set())             | ({"temperature"} if payload.get("menu_name") or payload.get("menu_id") else set())
        new_menu = None
        if payload.get("menu_name"):
            new_menu = menu_service.match(brand_id, menu_version, payload["menu_name"])
            if not new_menu.get("menu_id"):
                raise NotApplicable(payload["menu_name"])
        elif payload.get("menu_id"):
            new_menu = {"menu_id": payload["menu_id"]}

        merged = {**(before["options"] or {}), **options} if options is not None else None
        custom_changed = "custom_request" in payload
        custom = payload.get("custom_request") if custom_changed else before.get("custom_request")
        if new_menu:
            # 바꾼 메뉴에 그 종류가 없는 옵션은 기타 요청으로 옮긴다 — 분석 경로와 같은 규칙(sessions._spec_checks)
            kept, moved = menu_service.split_unoffered(
                brand_id, menu_version, merged if merged is not None else (before["options"] or {}),
                new_menu["menu_id"])
            if moved:
                merged, custom, custom_changed = kept, intake.move_to_custom(custom, moved), True
            fitted = fit_size(brand_id, menu_version, kept, new_menu["menu_id"])
            if fitted != kept:
                merged = fitted

        if merged is not None:
            sets.append("options = %s")
            params.append(json.dumps(merged, ensure_ascii=False))
        if resolved & set(ambiguous):
            sets.append("ambiguous_options = %s")
            params.append(json.dumps({k: v for k, v in ambiguous.items() if k not in resolved},
                                     ensure_ascii=False))
        if custom_changed:
            sets.append("custom_request = %s")
            params.append(custom or None)
        if "quantity" in payload:
            sets.append("quantity = %s")
            params.append(max(1, int(payload["quantity"])))
        if payload.get("menu_name"):
            sets += ["menu_id = %s", "menu_text = %s"]
            params += [new_menu["menu_id"], new_menu["name"]]
        elif payload.get("menu_id"):
            sets += ["menu_id = %s"]
            params += [payload["menu_id"]]
        if payload.get("removed"):
            sets.append("removed = true")

        if sets:
            cur.execute(
                f"UPDATE app.order_item SET {', '.join(sets)}, updated_at = NOW() "
                f" WHERE session_id = %s AND item_id = %s", (*params, session_id, item_id))

        if payload.get("removed"):
            questions.void_for_item(session_id, item_id, cur=cur)
            after = {**before, "removed": True}
            after_text = "빼기"
        else:
            after = _revalidate(cur, session, item_id)
            after_text = _row_text(after, session)

        token = changes.record(cur, session_id, method="question_answer", item_id=item_id,
                               who=before["person"], before_text=before_text,
                               after_text=after_text, before_json=_row_json(before),
                               after_json=_row_json(after))
        version = _commit(cur, session, expected_version=expected_version)

    _guard(session)
    return {"user_message": f'{before["person"]} 님 주문을 고쳤어요.', "undo_token": token,
            "changed_item_ids": [item_id], "version": version}


# --- API-022 채팅 입력 해석 ---------------------------------------------------
def interpret_message(session: dict, text: str, *, expected_version: int | None) -> dict:
    """해석은 서버가 한다 — 화면은 받은 안내만 그린다 (P-06).

    3분기: 매장 기준 바꾸기 되묻기 · 바로 반영 · 바꿀 것 없음.
    매장 기준 바꾸기는 그래프 앞의 세션 설정이다(P-03 4절 — 경로가 아니다).
    """

    # 1 매장 기준 바꾸기 — 결과를 새로 만들므로 이때만 한 번 묻는다 (U-5)
    target_brand = brand_service.detect_change_request(text)
    if target_brand and target_brand != session["brand_id"]:
        label = brand_service.BRAND_LABEL[target_brand]
        return {"kind": "brand_change_ask", "brand_id": target_brand,
                "text": f"{label}으로 새로 정리할까요?",
                "options": [{"value": "apply", "label": "새로 정리"},
                            {"value": "cancel", "label": "아니요"}]}

    # 2 · 3 — 해석 · 대상 연결 · 반영은 그래프가 한다(D-12 source=chat). 출력 가드도 거기서 지난다
    from app import graph

    return graph.run("chat", session, text=text, expected_version=expected_version)["result"]


def apply_chat_event(session: dict, text: str, event_type: str, target: dict | None, *,
                     expected_version: int | None) -> dict:
    """D-12 N-09 (source=chat) — 담당자 입력은 되묻지 않고 바로 반영한다(되돌리기 제공)."""
    session_id = session["session_id"]
    if event_type == "ignore":
        return {"kind": "no_change", "text": "주문에서 바꿀 것을 찾지 못했어요",
                "undo_token": None}
    if target is None:
        return {"kind": "no_change", "text": "어느 주문을 말하는지 찾지 못했어요",
                "undo_token": None}

    with db.transaction() as cur:
        cur.execute(
            "SELECT i.*, m.name AS menu_name FROM app.order_item i "
            "  LEFT JOIN app.menu m ON m.menu_id = i.menu_id "
            " WHERE i.session_id = %s AND i.item_id = %s", (session_id, target["item_id"]))
        before = cur.fetchone()
        before_text = _row_text(before, session)

        if event_type == "cancel":
            cur.execute("UPDATE app.order_item SET removed = true, updated_at = NOW() "
                        " WHERE session_id = %s AND item_id = %s",
                        (session_id, target["item_id"]))
            questions.void_for_item(session_id, target["item_id"], cur=cur)
            after_text = "취소"
            message = f'{before["person"]} 님 주문을 취소했어요.'
            after = {**before, "removed": True}
        else:
            changed = _apply_text_change(cur, session, before, text)
            if not changed:
                raise NotApplicable(text)
            after = _revalidate(cur, session, target["item_id"])
            after_text = _row_text(after, session)
            message = (f'{before["person"]} 님 주문을 {before_text}에서 '
                       f'{after_text}{_ro(after_text)} 바꿨어요.')

        token = changes.record(cur, session_id, method="chat_edit", item_id=target["item_id"],
                               who=before["person"], before_text=before_text,
                               after_text=after_text, before_json=_row_json(before),
                               after_json=_row_json(after))
        version = _commit(cur, session, expected_version=expected_version)

    return {"kind": "applied", "text": message, "undo_token": token,
            "changed_item_ids": [target["item_id"]], "version": version}


def _find_target(session_id: str, text: str) -> dict | None:
    """문장에서 사람 이름 · 메뉴 이름으로 대상을 찾는다.

    못 찾으면 **임의로 고르지 않는다** — 담당자에게 "찾지 못했어요"를 돌려준다.
    아무 행이나 고치면 담당자가 모르는 채로 틀린 주문을 공유한다.
    """
    rows = db.fetch_all(
        "SELECT i.item_id, i.person, i.menu_text, m.name AS menu_name "
        "  FROM app.order_item i LEFT JOIN app.menu m ON m.menu_id = i.menu_id "
        " WHERE i.session_id = %s AND i.removed = false ORDER BY i.item_id",
        (session_id,))
    by_person = [r for r in rows if r["person"] and r["person"] in text]
    if len(by_person) == 1:
        return by_person[0]
    pool = by_person or rows
    by_menu = [r for r in pool
               if (r["menu_name"] and r["menu_name"] in text)
               or (r["menu_text"] and r["menu_text"] in text)]
    if len(by_menu) == 1:
        return by_menu[0]
    if len(pool) == 1:
        return pool[0]
    return None


def _apply_text_change(cur, session, before: dict, text: str) -> bool:
    """문장에서 읽은 옵션 · 메뉴를 반영한다. 반영한 것이 없으면 False."""
    brand_id, menu_version = session["brand_id"], session["menu_version"]
    options = intake._options(text)
    applied = False

    if options:
        merged = {**(before["options"] or {}), **options}
        ambiguous = {k: v for k, v in (before["ambiguous_options"] or {}).items()
                     if k not in options}
        cur.execute("UPDATE app.order_item SET options = %s, ambiguous_options = %s, "
                    "       updated_at = NOW() WHERE item_id = %s",
                    (json.dumps(merged, ensure_ascii=False),
                     json.dumps(ambiguous, ensure_ascii=False), before["item_id"]))
        applied = True

    # "아이스 라떼로 바꿔줘" — 바꿀 메뉴 이름이 문장에 있는가
    stripped = intake._menu_text(text)
    if stripped:
        matched = menu_service.match(brand_id, menu_version, stripped)
        if matched.get("menu_id") and matched["menu_id"] != before["menu_id"]:
            cur.execute("UPDATE app.order_item SET menu_id = %s, menu_text = %s, "
                        "       updated_at = NOW() WHERE item_id = %s",
                        (matched["menu_id"], matched["name"], before["item_id"]))
            applied = True
    return applied


# --- API-024 되돌리기 ---------------------------------------------------------
def undo(session: dict, undo_token: str) -> dict:
    session_id = session["session_id"]
    row = changes.find_undoable(session_id, undo_token)
    if not row:
        raise NotApplicable("UNDO_UNAVAILABLE")

    with db.transaction() as cur:
        before = row["before_json"] or {}
        if row["item_id"] and before:
            cur.execute(
                "UPDATE app.order_item "
                "   SET menu_id = %s, menu_text = %s, options = %s, "
                "       ambiguous_options = %s, custom_request = %s, quantity = %s, "
                "       removed = %s, person = COALESCE(%s, person), "
                "       person_check = CASE WHEN %s THEN %s::jsonb ELSE person_check END, updated_at = NOW() "
                " WHERE session_id = %s AND item_id = %s",
                (before.get("menu_id"), before.get("menu_text"),
                 json.dumps(before.get("options") or {}, ensure_ascii=False),
                 json.dumps(before.get("ambiguous_options") or {}, ensure_ascii=False),
                 before.get("custom_request"), before.get("quantity") or 1,
                 bool(before.get("removed")), before.get("person"),
                 # 예전 기록(person_check 키 없음)은 그 칸을 건드리지 않는다
                 "person_check" in before,
                 json.dumps(before["person_check"], ensure_ascii=False) if before.get("person_check") else None,
                 session_id, row["item_id"]))
            _revalidate(cur, session, row["item_id"])
        if row["method"] == "question_answer" and row["item_id"]:
            # 답을 되돌리면 그 질문도 다시 묻는 상태로 돌아간다 (U-5) — 항목만 되돌리면
            # 확인 필요로 남은 항목을 물을 질문이 없어 공유까지 막힌다
            questions.reopen_last_answered(cur, session_id, row["item_id"])
        changes.mark_undone(cur, row["change_id"])
        version = _commit(cur, session, expected_version=None)

    _guard(session)
    return {"user_message": "되돌렸어요", "changed_item_ids": [row["item_id"]],
            "version": version}


# --- 공통 표시 문구 ------------------------------------------------------------
def _row_text(row: dict, session: dict | None = None) -> str:
    """O-6 · 안내 문구에 쓰는 짧은 조각. 원문 전문을 넣지 않는다 (D-07 4.7).

    옵션은 화면 라벨로 쓴다(venti → 벤티) — 내부 값이 담당자 화면에 나가지 않게(P-06).
    """
    if not row:
        return "-"
    name = row.get("menu_name") or row.get("menu_text") or "주문"
    options = row.get("options") or {}
    if session:
        spec = " ".join(menu_service.option_label(session["brand_id"], session["menu_version"], g, v)
                        for g, v in options.items())
    else:
        spec = " ".join(str(v) for v in options.values())
    quantity = int(row.get("quantity") or 1)
    tail = f" {quantity}잔" if quantity > 1 else ""
    return f"{name} {spec}".strip() + tail


def _row_json(row: dict) -> dict:
    """되돌리기가 복원하는 실제 값."""
    if not row:
        return {}
    return {k: row.get(k) for k in ("menu_id", "menu_text", "options", "ambiguous_options",
                                    "custom_request", "quantity", "removed", "person", "person_check")}
