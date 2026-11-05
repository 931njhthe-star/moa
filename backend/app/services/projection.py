"""DB → 화면 응답 투영.

화면에 보일 문구는 **전부 여기서 완성형으로** 만든다. 화면이 금액을 계산하거나
공유 가능 조건을 판정하지 않는다는 원칙(P-06)의 서버 쪽 짝이다.

개인별 금액은 투영하지 않는다 — 저장하되 미노출이다 (D-07 D-5 · D-02 2.4).
"""

from app import db
from app.services import brand as brand_service
from app.services.chat_parse import UNNAMED as _UNNAMED_PERSON
from app.services import menu as menu_service
from app.services import settlement

OPTION_LABEL = {"size": "사이즈", "ice": "얼음", "shot": "샷", "bean": "원두", "cup": "개인컵",
                "syrup": "시럽", "milk": "우유",
                # 확인 질문으로만 생기는 칸 — 메뉴판 옵션이 아니다
                "quantity": "수량", "temperature": "온도"}

AI_NOTICE_REVIEW = "AI가 정리한 결과예요 · 행을 누르면 고칠 수 있어요"
AI_NOTICE_SHEET = "AI가 정리한 결과예요 · 이름을 누르면 고칠 수 있어요"

# P-03 4.2 상태 → 상태 줄 (tone · text). 서버가 문구를 정한다
STATUS_LINE = {
    "pending": ("info", "대화를 정리하고 있어요. 금방 끝나요"),
    "running": ("info", "대화를 정리하고 있어요. 금방 끝나요"),
    "recovering": ("warning", "잠깐 멈췄다가 다시 하고 있어요. 입력한 내용은 그대로 있어요"),
    "failed": ("danger", "잠시 멈춰 있어요. 입력한 내용은 그대로 있어요. "
                         "조금 뒤 이 링크로 다시 와 주세요"),
    "completed": ("success", "주문서를 공유했어요! 매장에 보여 주며 주문해 주세요"),
}

STEP_LABELS = [
    ("read_chat", "대화 읽기", "intake"),
    ("match_menu", "메뉴판과 맞춰 보기", "menu"),
    ("check_changes", "바뀐 주문 · 빠진 정보 확인", "validation"),
    ("done", "정리 완료", None),
]

# order_session.checkpoint → 진행 단계 몇 개가 끝났는가
CHECKPOINT_DONE = {None: 0, "created": 0, "chat_read": 1, "menu_matched": 2,
                   "validated": 3, "settled": 4}


def options_block(brand_id: str, menu_version: str, options: dict,
                  ambiguous: dict) -> list[dict]:
    """화면이 그리는 옵션 칩. 모호한 값은 따옴표째 유지하고 표시를 달리한다."""
    block = []
    # 저장 순서가 아니라 고정 순서로 — 공유 문구가 "개인컵 사용 얼음 적게 벤티"처럼 뒤집혀 나갔다(2026-11-04)
    for group, value in sorted((options or {}).items(), key=lambda kv: _rank(_GROUP_ORDER, kv[0])):
        block.append({"label": OPTION_LABEL.get(group, group),
                      "value": menu_service.option_label(brand_id, menu_version, group, value)})
    for group, value in (ambiguous or {}).items():
        block.append({"label": OPTION_LABEL.get(group, group), "value": value,
                      "ambiguous": True})
    return block


_GROUP_ORDER = ["size", "ice", "shot", "bean", "cup", "syrup", "milk"]
_VALUE_ORDER = ["short", "tall", "regular", "grande", "large", "venti",
                "none", "less", "normal", "more", "base", "extra",
                "signature", "blonde", "decaf", "half_decaf", "personal", "add", "oat", "soy"]


def _rank(order: list[str], value: str) -> int:
    return order.index(value) if value in order else len(order)


def option_choices(brand_id: str, menu_version: str, row: dict) -> list[dict]:
    """행 편집 버튼 묶음 — 해당 메뉴에 적용되는 그룹만 펼친다 (P-06).

    메뉴가 안 정해진 행은 옵션을 펼치지 않는다 — 옵션은 메뉴마다 다르다(스타벅스 5종 · 2026-11-04).
    메뉴를 먼저 고르면(메뉴 바꾸기 · 확인 질문) 그 메뉴의 옵션이 뜬다.
    `choices` 는 저장용 값이다 — 화면은 라벨을 보여 주고 API-023 에는 `{option_group: value}` 를 보낸다(D-02).
    """
    if not row.get("menu_id"):
        return []
    groups = menu_service.option_groups(brand_id, menu_version, row.get("menu_id"))
    current = row.get("options") or {}
    ambiguous = row.get("ambiguous_options") or {}
    out = []
    # 그룹 · 값 순서를 고정한다 — DB 는 추가금 순으로 주므로 추가금이 같은 얼음 값(없이 · 적게 · 보통 · 많이)이 뒤섞였다
    groups = sorted(groups, key=lambda g: _rank(_GROUP_ORDER, g["option_group"]))
    for group in groups:
        group = {**group, "values": sorted(group["values"], key=lambda o: _rank(_VALUE_ORDER, o["option_value"]))}
        key = group["option_group"]
        chosen = current.get(key)
        # 행에 값이 없는 묶음(얼음 · 샷 · 원두 · 컵 등)은 **메뉴의 기본값이 골라진 상태**로 보여 준다 (2026-11-04).
        # 화면은 current 와 같은 값을 다시 보내지 않으므로(components.option_change) 기본값이 칩으로 쌓이지 않는다.
        # 모호한 값(사이즈 "큰 거")은 기본값으로 채우지 않는다 — 고른 것이 아니다
        if not chosen and key not in ambiguous:
            chosen = menu_service.default_option(brand_id, menu_version, key, menu_id=row.get("menu_id")) or None
        out.append({
            "label": OPTION_LABEL.get(key, key),
            "option_group": key,
            "values": [o["value_label"] for o in group["values"]],
            "choices": [{"value": o["option_value"], "label": o["value_label"]} for o in group["values"]],
            # 모호한 값은 고른 것이 아니다 — current 를 None 으로 둬서 화면이 빈 상태로 그린다
            "current": (menu_service.option_label(brand_id, menu_version, key, chosen)
                        if chosen and key not in ambiguous else None),
        })
    return out


def _quoted(text: str | None) -> str:
    """메뉴가 안 정해진 행의 원문 조각 — 이미 따옴표가 있으면 덧붙이지 않는다."""
    value = (text or "").strip()
    if not value:
        return ""
    return value if value.startswith('"') else f'"{value}"'


def item_rows(session: dict, rows: list[dict]) -> list[dict]:
    """주문서 패널의 행 목록 (API-015 rows)."""
    brand_id, menu_version = session["brand_id"], session["menu_version"]
    out = []
    for row in rows:
        if row.get("removed"):
            continue
        out.append({
            "item_id": row["item_id"],
            "person": row["person"],
            # 메뉴가 정해지지 않은 행은 **원문 조각을 따옴표째** 보낸다 — 화면이 그 따옴표로
            # "미정" 행(회색 견본 · 흐린 글자)을 가린다(P-06 · components.row_html).
            # 따옴표 없이 보내면 담당자 눈에는 원문이 메뉴 이름처럼 보인다(2026-11-03 확인)
            "menu_text": row.get("menu_name") or _quoted(row.get("menu_text")),
            "options": options_block(brand_id, menu_version, row.get("options"),
                                     row.get("ambiguous_options")),
            "custom_request": row.get("custom_request"),
            "quantity": int(row.get("quantity") or 1),
            "estimated_price": row.get("estimated_price"),
            # 규칙 실패(failed · 옵션 오류)도 담당자가 고칠 행이다 — 공유는 이미 막는데(review_count) 행 표시가 빠져
            # 어느 행 때문에 막혔는지 보이지 않았다(2026-11-04 전체 흐름 확인)
            "needs_review": row.get("validation_status") in ("needs_review", "failed"),
            "review_reason_text": row.get("review_reason_text"),
            "changed": bool(row.get("changed")),
            "option_choices": option_choices(brand_id, menu_version, row),
        })
    return out


def session_view(session: dict, rows: list[dict], *, review_count: int,
                 chat: list[dict] | None = None) -> dict:
    """API-015 — 분석 결과 조회."""
    summary = settlement.totals(rows)
    return {
        "session_id": session["session_id"],
        "status": session["status"],
        "version": session["version"],
        "brand": brand_service.projection(session["brand_id"], session["brand_source"],
                                          session.get("brand_evidence_text")),
        "summary": {
            "people": summary["people"],
            "cups": summary["cups"],
            "review_count": review_count,
            "estimated_total": summary["estimated_total"],
            "amount_notice": settlement.amount_notice(summary["estimated_total"]),
        },
        "rows": item_rows(session, rows),
        "input_summary": _input_summary(session["session_id"]),
        "ai_notice": AI_NOTICE_REVIEW,
        "chat": chat or [],
    }


def _input_summary(session_id: str) -> dict:
    row = db.fetch_one(
        "SELECT COALESCE(SUM(message_count), 0) AS n FROM app.snapshot WHERE session_id = %s",
        (session_id,))
    count = int(row["n"]) if row else 0
    return {"message_count": count, "label_text": f"넣은 대화 {count}개"}


def pending_suggestions(session_id: str) -> int:
    """아직 결정하지 않은 답장 제안 수 — 질문으로 올린 것은 빼고 센다(공유 게이트와 같은 기준)."""
    row = db.fetch_one(
        "SELECT COUNT(*) AS n FROM app.suggestion "
        " WHERE session_id = %s AND status = 'pending' AND question_id IS NULL", (session_id,))
    return int(row["n"]) if row else 0


def progress_view(session: dict, *, review_count: int, step_notes: dict | None = None) -> dict:
    """API-014 — 진행 4단계. 끝난 단계는 복구 중에도 done 을 유지한다."""
    status = session["status"]
    done = CHECKPOINT_DONE.get(session.get("checkpoint"), 0)
    states = []
    for index in range(4):
        if index < done:
            states.append("done")
        elif index == done:
            states.append({"failed": "failed", "recovering": "running"}.get(status, "running")
                          if status not in ("needs_review", "awaiting_confirmation", "completed")
                          else "done")
        else:
            states.append("pending" if status not in ("needs_review", "awaiting_confirmation",
                                                      "completed") else "done")

    notes = step_notes or {}
    steps = [{"key": key, "label": label, "state": states[i], "agent": agent,
              "note_text": notes.get(key)}
             for i, (key, label, agent) in enumerate(STEP_LABELS)]

    tone, text = _status_line(status, review_count)
    if status in ("pending", "running") and _stalled(session):
        # 단계가 오래 멈춰 보이면 — 시간을 숫자로 약속하지 않는다(P-06 상태 표)
        text = SLOW_TEXT
    collapsed = ("정리했어요" if status in ("needs_review", "awaiting_confirmation", "completed")
                 else None)
    return {
        "session_id": session["session_id"],
        "status": status,
        "status_line": {"tone": tone, "text": text},
        "steps": steps,
        "collapsed_text": collapsed,
        "review_count": review_count if status in ("needs_review", "awaiting_confirmation")
        else None,
        # 아직 정하지 않은 답장 제안 — 화면이 [주문서 보기]를 막는 근거다(2026-11-05 3차 보고 7번).
        # 주문서에서야 "반영할지 정하지 않은 제안이 N건 있어요"를 만나면 거기서는 풀 수단이 없다
        "pending_suggestions": pending_suggestions(session["session_id"]),
        "trace_id": session.get("trace_id"),
    }


SLOW_TEXT = "조금 더 걸리고 있어요. 입력한 내용은 그대로 있어요"


def _stalled(session: dict) -> bool:
    """마지막 진행(체크포인트 · 세션 갱신)에서 config.SLOW_NOTICE_SEC 가 지났는가."""
    import datetime

    from app import config

    marks = [t for t in (session.get("checkpoint_at"), session.get("updated_at")) if t]
    if not marks:
        return False
    elapsed = datetime.datetime.now(datetime.timezone.utc) - max(marks)
    return elapsed.total_seconds() >= config.SLOW_NOTICE_SEC


def _status_line(status: str, review_count: int) -> tuple[str, str]:
    if status == "needs_review":
        return "info", f"{review_count}건만 답해 주시면 돼요"
    if status == "awaiting_confirmation":
        return "info", "확인이 필요한 주문이 없어요. 주문서를 만들 수 있어요"
    return STATUS_LINE.get(status, STATUS_LINE["running"])


def step_notes(session: dict, parsed_counts: dict) -> dict:
    """단계 옆 메모 — 서버가 만든 완성 문구."""
    return {
        "read_chat": (f"{parsed_counts.get('person_count', 0)}명 · "
                      f"메시지 {parsed_counts.get('message_count', 0)}개"),
        "match_menu": brand_service.BRAND_LABEL.get(session["brand_id"]),
    }


# 관리 링크 안내 말풍선은 **두지 않는다**(2026-11-03 요청). 화면이 새 브라우저에서 `?s=` 만으로
# 세션을 열지 못해 "돌아올 수 있다"는 약속을 지킬 수 없었고, 남은 "공유하지 마세요" 한 줄은
# 담당자가 할 일이 없는 경고였다. 토큰 → 세션 조회 경로가 생기면 그때 다시 검토한다.


def chat_intro(session: dict, rows: list[dict], *, review_count: int) -> list[dict]:
    """화면 B 의 첫 말풍선 — 서버가 문구를 만든다.

    화면이 "5명 · 5잔으로 정리했어요"를 조립하면 숫자를 세는 규칙이 화면에 생긴다.
    """
    summary = settlement.totals(rows)
    # 이름 없는 대화는 몇 명인지 모른다 — "1명"으로 말하지 않는다 (2026-11-05 보고 1번)
    nameless = bool(rows) and all(r.get("person") == _UNNAMED_PERSON for r in rows)
    head = f'{summary["cups"]}잔' if nameless else f'{summary["people"]}명 · {summary["cups"]}잔'
    messages: list[dict] = []
    if session["status"] in ("needs_review", "awaiting_confirmation", "completed"):
        tail = ("왼쪽 주문서에서 확인하고 고칠 수 있어요" if not review_count
                else f"{review_count}건만 답해 주시면 돼요")
        messages.append({
            "role": "assistant", "kind": "summary",
            "text": f'{head}으로 정리했어요. {tail}',
        })
    return messages


def session_created_view(session: dict, *, session_token: str) -> dict:
    """API-012 성공 응답 — 화면이 관리 링크와 폴링 주소를 받는다."""
    return {
        "session_id": session["session_id"],
        "session_token": session_token,
        "status": session["status"],
        "version": session["version"],
        "brand": brand_service.projection(session["brand_id"], session["brand_source"],
                                          session.get("brand_evidence_text")),
        "menu_version": session["menu_version"],
        "progress_url": f'/api/sessions/{session["session_id"]}/progress',
    }
