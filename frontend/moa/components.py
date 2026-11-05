# 공통 컴포넌트 — 말풍선 · 진행 단계 · 주문서 패널 행 · 행 편집 · 묶음 목록 · 공유 카드
#
# 모양의 출처는 정본 시안 `Moa_전체화면.svg`이고 배치의 출처는 P-06 화면 상세다.
# 색 값 · px 크기를 여기에 쓰지 않는다 — 전부 `moa/tokens.py`의 클래스 · 변수를 쓴다.
import html
import re

import streamlit as st

from moa import copy, icons


def esc(text) -> str:
    return html.escape(str(text)) if text is not None else ""


def amount_text(value, *, prefix: str = "예상", unit: bool = False) -> str:
    """금액 표기 — 앞에 "예상" · 천 단위 쉼표.

    매장 기준과 무관하게 모든 금액에 "예상"을 붙인다(P-06 U-4).
    **"원"은 정본 시안에서 자리마다 다르다** — 행 · 묶음은 `예상 4,500`,
    주문서 패널 머리와 채팅 요약은 `예상 25,800원`이다. 그래서 기본값은 "원" 없음이다.
    `None`은 0원이 아니라 **미정**이므로 빈 문자열로 둔다(D-02 API-015).
    금액을 **계산**하지는 않는다 — 서버가 준 정수를 포맷하는 것까지가 화면의 일이다.
    """
    if value is None:
        return ""
    return f"{prefix} {value:,}원" if unit else f"{prefix} {value:,}"


def bold_numbers(text) -> str:
    """서버 문구 안의 금액 숫자만 굵게 — `예상 25,800원 · …` (시안 패널 머리). 글자는 바꾸지 않는다."""
    return re.sub(r"(\d[\d,]*)", r"<b>\1</b>", esc(text), count=1)


# --- 칩 · 기타 요청 ------------------------------------------------------------
def option_chips(options) -> str:
    """옵션 칩 — `사이즈 톨`. 모호한 원문 표현은 따옴표째 유지하고 주황으로 둔다(D-02 `ambiguous`)."""
    out = []
    for option in options or []:
        cls = "moa-chip moa-chip-amb" if option.get("ambiguous") else "moa-chip"
        out.append(f'<span class="{cls}"><i>{esc(option.get("label", ""))}</i>'
                   f'{esc(option.get("value", ""))}</span>')
    return "".join(out)


def custom_request_box(text) -> str:
    """기타 요청 — 메뉴판 옵션 데이터에 없는 요청. 금액에 반영하지 않는다. 원문을 따옴표째 보인다."""
    if not text:
        return ""
    return (f'<div class="moa-custom"><b>{esc(copy.S2_PANEL_CUSTOM_LABEL)}</b>'
            f'"{esc(text)}"</div>')


def pill(text: str, kind: str = "gray") -> str:
    return f'<span class="moa-pill moa-pill-{kind}">{esc(text)}</span>'


# --- 채팅 말풍선 (시안 케이스 08 ~ 17) ------------------------------------------
def bot(key: str):
    """Moa 말 — 왼쪽 아바타 + 흰 상자. `with c.bot("k"):` 안에서 상자 내용을 그린다."""
    row = st.container(key=f"bot_{key}", horizontal=True, vertical_alignment="top", gap=None)
    with row:
        st.html(f'<span class="moa-avatar">{icons.logo(18)}</span>')
    return row.container(key=f"bubble_{key}", width="content")


def bot_text(key: str, body_html: str) -> None:
    with bot(key):
        st.html(f'<div class="moa-bubble-text">{body_html}</div>')


def me(text: str) -> None:
    """내 말 — 오른쪽 연초록 상자. 아바타가 없다."""
    st.html(f'<div class="moa-me">{esc(text)}</div>')


# --- 진행 단계 (P-06 SCR-002 요소 4) ---------------------------------------------
def steps_summary(step_list) -> str:
    """접힌 진행 말풍선 옆 한 줄 — `대화 읽기 · 메뉴판과 맞춰 보기 · 바뀐 주문 확인`.

    정본 시안 케이스 11 ~ 17이 접힌 상태에 이 줄을 함께 둔다. 마지막 단계(정리 완료)는 빼고,
    세 번째 단계는 짧은 이름으로 줄인다.
    """
    labels = [st_.get("label", "") for st_ in (step_list or []) if st_.get("key") != "done"]
    short = {"바뀐 주문 · 빠진 정보 확인": "바뀐 주문 확인"}
    return " · ".join(short.get(label, label) for label in labels)


def _step_icon(state_: str) -> str:
    if state_ == "done":
        return f'<span class="moa-step-ico">{icons.icon("check", 13, width=3)}</span>'
    if state_ == "failed":
        return f'<span class="moa-step-ico moa-step-ico-failed">{icons.icon("x", 12, width=3)}</span>'
    if state_ == "running":
        return '<span class="moa-step-ico moa-step-ico-running"></span>'
    return '<span class="moa-step-ico moa-step-ico-pending"></span>'


def steps_html(step_list) -> str:
    """단계 목록. 진행 막대(`st.progress`)는 쓰지 않는다(U-2).

    끝난 단계는 `done`을 유지한다 — 복구 중에 처음부터 다시 하는 것처럼 보이면 안 된다.
    """
    rows = []
    for step in step_list or []:
        state_ = step.get("state", "pending")
        note = step.get("note_text")
        note_html = (f'<div class="moa-step-note">{esc(note)}</div>'
                     if note and state_ != "pending" else "")
        if step.get("warn_text") and state_ == "running":
            # 복구 중 — 끝난 단계는 그대로 두고 지금 단계에만 주황 한 줄 (시안 케이스 09)
            note_html += f'<div class="moa-step-note moa-step-note-warn">{esc(step["warn_text"])}</div>'
        rows.append(f'<div class="moa-step moa-step-{esc(state_)}">{_step_icon(state_)}'
                    f'<div><div class="moa-step-label">{esc(step.get("label"))}</div>{note_html}</div></div>')
    return f'<div class="moa-steps">{"".join(rows)}</div>'


def progress_line(collapsed_text: str, step_list) -> str:
    return (f'<div class="moa-progress-line">{_step_icon("done")}<b>{esc(collapsed_text)}</b>'
            f'<span>{esc(steps_summary(step_list))}</span></div>')


# --- 주문서 패널 (P-06 SCR-002 요소 5) ------------------------------------------
def order_panel_head(summary: dict) -> None:
    """머리 — 인원 · 잔 수가 가장 큰 글자. 금액은 작은 회색 한 줄(U-4)."""
    review = summary.get("review_count") or 0
    badge = pill(copy.S2_REVIEW_BADGE.format(n=review), "amber") if review else ""
    st.html(f'<div class="moa-panel-title">{esc(copy.S2_PANEL_TITLE)}{badge}</div>'
            f'<div class="moa-panel-big moa-num">{esc(summary.get("people", 0))}명 · '
            f'{esc(summary.get("cups", 0))}잔</div>'
            f'<div class="moa-panel-amount moa-num">{bold_numbers(summary.get("amount_notice", ""))}</div>')


def panel_skeleton() -> None:
    """정리 중 · 복구 중 · 지연 — 빈 자리만 보인다(시안 케이스 08 ~ 10)."""
    st.html(f'<div class="moa-panel-title">{esc(copy.S2_PANEL_TITLE)}</div>'
            f'<div class="moa-panel-empty">{esc(copy.S2_PANEL_EMPTY)}</div>'
            + '<div class="moa-skel"></div>' * 4)


def row_html(row: dict) -> str:
    """사람별 행 한 줄 — 메뉴 견본 · 이름 · 금액(또는 확인 필요) · 메뉴 · 옵션 칩 · 기타 요청."""
    review = row.get("needs_review")
    # 메뉴가 아직 정해지지 않은 행 — 원문 조각을 따옴표째 보이는 행이다(P-06). 견본도 회색
    unknown = bool(review) and str(row.get("menu_text", "")).startswith('"')
    right = (pill(copy.S2_ROW_REVIEW, "amber") if review
             else f'<span class="moa-row-amount moa-num">{esc(amount_text(row.get("estimated_price")))}</span>')
    menu_cls = "moa-row-menu moa-row-menu-amb" if unknown else "moa-row-menu"
    changed = '<span class="moa-row-changed"></span>' if row.get("changed") else ""
    swatch = icons.swatch(row.get("menu_text"), 36, unknown=unknown)
    # 한 사람이 여러 잔을 시켰으면 몇 번째 잔인지 붙인다 — 같은 이름이 연달아 나와 헷갈렸다
    # (2026-11-05 3차 보고 3번). 화면이 세지 않는다 — 넘겨받은 값을 쓴다
    seq = row.get("person_seq")
    seq_html = f'<span class="moa-row-seq">{esc(seq)}</span>' if seq else ""
    return (f'{changed}<div class="moa-row">{swatch}<div class="moa-row-body">'
            f'<div class="moa-row-top"><span class="moa-row-person">{esc(row.get("person"))}'
            f'{seq_html}</span>{right}</div>'
            f'<div class="{menu_cls}">{esc(row.get("menu_text"))}</div>'
            f'<div>{option_chips(row.get("options"))}</div>'
            f'{custom_request_box(row.get("custom_request"))}</div></div>')


def by_person(rows: list[dict]) -> list[dict]:
    """같은 사람의 잔을 붙여 놓고 순번을 단다 (2026-11-05 3차 보고 3번).

    사람 순서는 **처음 나온 순서**를 지킨다 — 이름순으로 다시 세우면 대화 순서와 어긋나 찾기 어렵다.
    한 잔뿐인 사람에게는 순번을 달지 않는다.
    """
    order, grouped = [], {}
    for row in rows or []:
        person = row.get("person") or ""
        if person not in grouped:
            order.append(person)
            grouped[person] = []
        grouped[person].append(row)
    out = []
    for person in order:
        mine = grouped[person]
        for index, row in enumerate(mine, start=1):
            out.append({**row, "person_seq": f"{index}/{len(mine)}" if len(mine) > 1 else None})
    return out


def order_row(row: dict, *, on_open, opened: bool, editor) -> None:
    """누르면 그 자리에서 고치는 행. 바뀐 행은 연한 노란색으로 강조한다(U-14)."""
    item_id = row["item_id"]
    with st.container(key=f"card_row_{item_id}"):
        st.html(row_html(row))
        # 열려 있으면 같은 머리를 다시 눌러 닫는다
        if st.button(f"{row.get('person')} {'닫기' if opened else '고치기'}", key=f"hit_row_{item_id}"):
            on_open(None if opened else item_id)
    if opened:
        with st.container(key=f"moa_editor_{item_id}"):
            editor()


def option_editor(choices, *, key: str, title_html: str | None = None,
                  custom_value: str | None = None) -> tuple[dict, str]:
    """옵션 버튼 묶음 — 메뉴판 옵션 데이터에 있는 항목만 펼친다. 그 밖의 요청은 기타 요청 칸.

    고를 수 있는 값은 **서버가 준다** — 화면이 메뉴별 옵션을 지어내지 않는다.
    돌려주는 값: (바꾼 옵션 `{option_group: value}`, 기타 요청 문구)

    버튼에는 라벨("그란데")을 보여 주지만 API-023 에는 `{"size": "grande"}`를 보낸다(D-02) — 라벨 그대로 보내면
    서버가 "unknown options"로 거절해 행 편집 저장이 되지 않았다(2026-11-04). 고르지 않았거나 지금 값과 같은
    묶음은 보내지 않는다 — 기본값(얼음 보통 · 개인컵 미사용 등)이 주문서 칩으로 쌓이지 않게.
    """
    if title_html:
        st.html(title_html)
    picked = {}
    for group in choices or []:
        label = group.get("label", "")
        values = group.get("values") or []
        if not values:
            continue
        current = group.get("current")
        with st.container(key=f"optrow_{key}_{label}", horizontal=True, vertical_alignment="center"):
            st.html(f'<span class="moa-opt-label">{esc(label)}</span>')
            chosen = st.pills(label, values, default=current if current in values else None,
                              key=f"opt_{key}_{label}", label_visibility="collapsed")
        change = option_change(group, chosen)
        if change:
            picked.update(change)
    with st.container(key=f"optrow_{key}_custom", horizontal=True, vertical_alignment="center"):
        st.html(f'<span class="moa-opt-label">{esc(copy.S2_PANEL_CUSTOM_LABEL)}</span>')
        custom = st.text_input(copy.S2_PANEL_CUSTOM_LABEL, value=custom_value or "",
                               key=f"custom_{key}", label_visibility="collapsed")
    return picked, custom


def option_change(group: dict, chosen: str | None) -> dict:
    """고른 라벨 → API-023 옵션 `{option_group: value}`. 안 골랐거나 지금 값 그대로면 빈 dict.

    서버가 `choices`(값 · 라벨 짝)를 주지 않는 미리보기 데이터는 라벨을 키 · 값으로 그대로 쓴다.
    """
    if not chosen or chosen == group.get("current"):
        return {}
    value = next((c["value"] for c in group.get("choices") or [] if c.get("label") == chosen), chosen)
    return {group.get("option_group") or group.get("label", ""): value}


def editor_actions(*, key: str, remove_label: str, on_menu, on_remove, on_save) -> None:
    """[메뉴 바꾸기] [빼기] ………… [저장]"""
    with st.container(key=f"edit_actions_{key}", horizontal=True, horizontal_alignment="distribute",
                      vertical_alignment="center"):
        with st.container(horizontal=True, vertical_alignment="center", width="content", gap="small"):
            if st.button(copy.S2_PANEL_EDIT_MENU, key=f"menu_{key}"):
                on_menu()
            if st.button(remove_label, key=f"link_red_remove_{key}"):
                on_remove()
        if st.button(copy.S2_PANEL_EDIT_SAVE, key=f"save_{key}", type="primary"):
            on_save()


# --- 묶음 목록 (P-06 SCR-005 요소 4) ----------------------------------------------
NAMES_FOLD_AT = 7   # 한 묶음이 7명 이상이면 앞의 5명과 `+N명 더 보기`로 접는다
NAMES_SHOWN = 5


def group_html(group: dict) -> str:
    """같은 메뉴 · 옵션 · 기타 요청끼리 묶어 수량(크게)과 묶음 예상 금액(작은 회색)을 보여준다.

    **개인별 금액은 표시하지 않는다**(PRD v1.5 FR-010 · D-02 2.4 마지막 행).
    """
    return (f'<div class="moa-group">{icons.swatch(group.get("menu_text"), 38)}'
            f'<div class="moa-group-body"><div class="moa-group-menu">{esc(group.get("menu_text"))}</div>'
            f'<div>{option_chips(group.get("options"))}</div>'
            f'{custom_request_box(group.get("custom_request"))}</div>'
            f'<div class="moa-group-right"><div class="moa-qty moa-num"><i>×</i>{esc(group.get("quantity"))}</div>'
            f'<div class="moa-group-amount moa-num">{esc(amount_text(group.get("estimated_amount")))}</div>'
            f'</div></div>')


def names_row(group: dict, *, editable: bool, editing_index: int | None, on_pick) -> None:
    """이름 칩 — 공유 전에는 눌러 그 자리에서 고친다(케이스 19). 7명 이상이면 접는다.

    칩은 **이름이 아니라 순번**으로 가른다 — 한 사람이 같은 메뉴를 두 잔 시키면 한 묶음에 이름이 두 번 들어온다.
    이름으로 키를 만들면 StreamlitDuplicateElementKey 로 주문서 화면이 멈췄다(정하준 · 2026-11-04 사용자 보고).
    on_pick 에는 순번을 넘긴다 — 순번이 group["item_ids"] 의 같은 자리 항목이다.
    """
    people = group.get("people") or []
    gid = group.get("group_id")
    # 인원 수를 키에 넣는다 — 같은 묶음의 인원이 바뀌면 접힘 기본값도 다시 정한다
    folded_key = f"_names_folded_{gid}_{len(people)}"
    if folded_key not in st.session_state:
        st.session_state[folded_key] = len(people) >= NAMES_FOLD_AT
    folded = st.session_state[folded_key]
    shown = people[:NAMES_SHOWN] if folded else people
    with st.container(key=f"names_{gid}", horizontal=True, vertical_alignment="center", gap=None):
        if editable:
            for index, person in enumerate(shown):
                active = index == editing_index
                if st.button(person, key=f"name_{gid}_{index}", type="primary" if active else "secondary"):
                    on_pick(group, None if active else index)
        else:
            st.html("".join(f'<span class="moa-name-chip">{esc(p)}</span>' for p in shown))
        if len(people) >= NAMES_FOLD_AT:
            label = (f"+{copy.S5_NAMES_MORE.format(n=len(people) - NAMES_SHOWN)}" if folded
                     else copy.S5_NAMES_FOLD)
            if st.button(label, key=f"link_names_{gid}"):
                st.session_state[folded_key] = not folded
                st.rerun()


def order_totals(totals: dict) -> None:
    """합계 — 굵게 한 줄 + 참고용 금액 안내."""
    total = totals.get("estimated_total")
    # 금액 표기는 한 곳에서만 만든다 — 여기서 따로 조립했더니 "예상 24,900 원"처럼
    # 다른 자리("예상 24,900원")와 띄어쓰기가 어긋났다(2026-11-03 확인)
    amount = amount_text(total, unit=True)
    st.html(f'<div class="moa-total"><div class="moa-total-top"><b>{esc(copy.S5_TOTAL_LABEL)}</b>'
            f'<span class="moa-num">{esc(totals.get("cups", 0))}잔 · {esc(amount)}</span></div>'
            f'<div class="moa-total-note">{esc(totals.get("notice", ""))}</div></div>')


# --- 공유 카드 (1종) ---------------------------------------------------------------
def share_card_html(card: dict) -> str:
    """미리보기. **내용은 서버가 만든다** — 화면이 조립하지 않는다.

    관리 링크 · 토큰 · QR · 브랜드 로고를 넣지 않는다(NFR-003).
    """
    lines = []
    for line in card.get("lines", []):
        color = icons.swatch_color(line.get("menu_text"))
        req = (f'<div class="moa-share-req">요청: {esc(line.get("custom_request"))}</div>'
               if line.get("custom_request") else "")
        lines.append(
            f'<div class="moa-share-line"><div class="moa-share-top"><span>'
            f'<i class="moa-share-dot" style="background:{color}"></i>{esc(line.get("menu_text"))}</span>'
            f'<span class="moa-num">×{esc(line.get("quantity"))}</span></div>'
            + (f'<div class="moa-share-people">{esc(" · ".join(line["people"]))}</div>'
               if line.get("people") else "")     # 이름 없이 공유하면 이름 줄을 그리지 않는다
            + f'{req}</div>')
    total = card.get("total_text", "")
    label, _, value = total.partition(" ")
    dots = "".join(f'<i style="background:{c}"></i>' for c in ("#3B2A20", "#E9D9B8", "#A9D3BE"))
    return (f'<div class="moa-share-card"><div class="moa-share-head"><div><b>{esc(card.get("head"))}</b>'
            f'<span class="moa-num">{esc(card.get("sub"))}</span></div><div class="moa-share-dots">{dots}</div></div>'
            f'<div class="moa-share-body">{"".join(lines)}'
            f'<div class="moa-share-total"><div class="moa-share-top"><span>{esc(label)}</span>'
            f'<span class="moa-num">{esc(value)}</span></div>'
            f'<div class="moa-share-note">{esc(card.get("notice"))}</div></div>'
            f'<div class="moa-share-foot">{esc(card.get("foot", copy.S5_CARD_FOOT))}</div></div></div>')


def ai_notice(text) -> str:
    """AI 고지 — 에이전트 화면 필수 요소(P-06 "에이전트 화면의 필수 요소")."""
    return esc(text) if text else ""
