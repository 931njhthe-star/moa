# 공통 레이아웃 — 담당자 화면 3종(SCR-001 · 002 · 005)과 운영 대시보드가 같은 함수를 쓴다
#
# 출처: P-06 "공통 레이아웃" · 정본 시안 `Moa_전체화면.svg`
#   헤더(로고 · 단계 표시 A/B/E · 매장 기준 근거 + 배지 · [운영 대시보드])
#   -> 상태 줄(둥근 상자 한 줄 · 닫기 없음)
#   -> 본문
#   -> 하단 고정 바(보조 + 주 버튼 하나)
#   -> 가격 기준 고지(맨 아래 한 줄)
import html

import streamlit as st

from moa import api, copy, dialogs, icons, mock, state


def _esc(text) -> str:
    return html.escape(str(text)) if text is not None else ""


def page_setup() -> None:
    """토큰 주입과 상태 초기화. 모든 화면이 맨 앞에서 부른다.

    `st.set_page_config`는 앱 실행마다 첫 Streamlit 명령이어야 하므로 `app.py`에 둔다.
    """
    from moa import tokens

    tokens.inject()
    state.init()


def _brandmark(extra: str = "") -> None:
    """왼쪽 위 로고 + (단계 표시 또는 운영 표시). 로고를 누르면 홈(SCR-001 `/`)으로 간다.

    `st.page_link`라 페이지를 새로 읽지 않는다 — 넣은 대화 · 정리 결과가 그대로 남는다(U-9).
    로고 그림은 CSS 배경(`--moa-logo-url`)으로 입히고 글자는 화면 읽기용으로만 남긴다.
    """
    from moa import nav

    with st.container(key="moa_brand", horizontal=True, vertical_alignment="center",
                      gap=None, width="content"):
        with st.container(key="moa_home", width="content"):
            st.page_link(nav.pages()["start"], label=f"{copy.LOGO_WORD} 홈")
        if extra:
            st.html(f'<div class="moa-brandmark">{extra}</div>')


def _tabs(page: str) -> str:
    """단계 표시 A · B · E — 지금 화면만 진하게. 누르는 탭이 아니다(P-06 U-2)."""
    parts = []
    for letter, label, name in copy.TABS:
        cls = "moa-tab moa-tab-on" if name == page else "moa-tab"
        parts.append(f'<span class="{cls}"><b>{letter}</b>{_esc(label)}</span>')
    return f'<span class="moa-logo-slash">/</span><span class="moa-tabs">{"".join(parts)}</span>'


def header(brand: dict | None = None, *, ops_mode: bool = False, show_ops_entry: bool = True,
           ops_login: bool = False, gate: bool = False) -> None:
    """헤더 — 왼쪽 로고 + 단계 표시, 오른쪽 매장 기준 근거 · 배지 · [운영 대시보드].

    매장 기준은 **텍스트와 배지로만** 보여준다. [변경] 버튼 · 브랜드 목록은 두지 않는다(F-024).
    바꾸는 법 한 줄은 상태 줄 아래에 둔다(`change_hint`) — 시안 케이스 08 ~ 17.
    `show_ops_entry=False`는 O-0 단독 화면용이다 — 이미 그 문을 열어 둔 화면이다.
    """
    page = st.session_state.get("_page", "")
    with st.container(key="moa_header", horizontal=True, horizontal_alignment="distribute",
                      vertical_alignment="center"):
        if gate:
            # 서비스 진입 게이트 — 로고만 둔다. 단계 표시 · [운영 대시보드]는 들어간 뒤에 나온다
            _brandmark()
            return
        if ops_login:
            # 미인증 `/ops` — 운영 머리만 둔다. 갱신 표시 · [나가기]는 들어간 뒤에 나온다
            _brandmark(f'<span class="moa-ops-word">{_esc(copy.OPS_ENTRY_BUTTON)}</span>')
            return
        if ops_mode:
            _brandmark(f'<span class="moa-ops-word">{_esc(copy.OPS_ENTRY_BUTTON)}</span>')
            with st.container(horizontal=True, horizontal_alignment="right",
                              vertical_alignment="center", gap="medium", width="content"):
                _ops_header_note()
                if st.button(copy.O6_LOGOUT, key="link_logout", icon=":material/logout:"):
                    dialogs.logout_ops()
            return

        _brandmark(_tabs(page))
        with st.container(horizontal=True, horizontal_alignment="right",
                          vertical_alignment="center", gap="small", width="content"):
            if brand:
                evidence = brand.get("evidence_text")
                st.html('<div class="moa-head-right">'
                        + (f'<span class="moa-evidence">{_esc(evidence)}</span>' if evidence else "")
                        + f'<span class="moa-brand-pill">{_esc(brand.get("label"))}</span></div>')
            if show_ops_entry:
                # 모든 담당자 화면 헤더 오른쪽 끝 · 모바일에서도 숨기지 않는다.
                # 주 버튼 1개 원칙(U-1)에 세지 않는 보조 버튼이다.
                if st.button(copy.OPS_ENTRY_BUTTON, key=f"ops_entry_{page}", icon=":material/lock:"):
                    dialogs.open_ops_login()


def _ops_header_note() -> None:
    status = st.session_state.get("_ops_status") or {}
    at = status.get("updated_at_text", "")
    env = status.get("environment_label", copy.O_ENV_BADGE)
    note = copy.O_REFRESH_NOTE.format(at=at) if at else ""
    st.html(f'<div class="moa-head-right"><span class="moa-evidence">{icons.icon("refresh", 13)} '
            f'{_esc(note)}</span><span class="moa-env-badge">{_esc(env)}</span></div>')


_TONE_ICON = {"info": "info", "success": "check-circle", "warning": "alert", "danger": "alert"}


def status_line(line: dict | None) -> None:
    """상태 줄 — 고정 한 줄 · 닫기 버튼을 두지 않는다(F-013).

    `tone`은 info · warning · danger · success 네 가지다. 색만으로 구분하지 않도록
    아이콘을 함께 둔다(U-8). 문구는 서버가 만든 것만 쓴다.
    """
    if not line:
        return
    tone = line.get("tone", "info")
    st.html(f'<div class="moa-status moa-status-{_esc(tone)}">'
            f'{icons.icon(_TONE_ICON.get(tone, "info"), 16)}'
            f'<span>{_esc(line.get("text", ""))}</span></div>')


def change_hint(brand: dict | None) -> None:
    """매장 기준 바꾸는 법 — 상태 줄 바로 아래 작은 회색 한 줄. 채팅이 있는 SCR-002에만 둔다."""
    if brand and brand.get("change_hint_text"):
        st.html(f'<div class="moa-subhint">{_esc(brand["change_hint_text"])}</div>')


def bottom_bar(*, back_label: str | None, back_key: str, primary_label: str,
               primary_key: str, primary_enabled: bool, blocked_reason: str | None = None,
               primary_icon: str | None = None, warn: bool = False, primary_slot=None,
               blocked_action=None):
    """하단 고정 바 — 왼쪽 보조 버튼 + 오른쪽 (이유 한 줄 + 주 버튼 하나)(U-1).

    주 버튼이 비활성이면 **이유를 버튼 왼쪽에 한 줄** 적는다. 그 문구도 서버가 만든다.
    `primary_slot`을 주면 주 버튼 대신 그 함수를 부른다(SCR-005 공유하기처럼 버튼이 대화상자를 여는 경우).
    `blocked_action`을 주면 막는 이유가 **누를 수 있는 버튼**이 되고, 누르면 그 함수를 부른다.
    돌려주는 값: (뒤로 눌림, 주 버튼 눌림)
    """
    back_clicked = primary_clicked = False
    with st.container(key="moa_bar", horizontal=True, horizontal_alignment="distribute",
                      vertical_alignment="center"):
        if back_label:
            back_clicked = st.button(back_label, key=back_key, icon=":material/chevron_left:")
        else:
            st.html("<span></span>")
        with st.container(key="moa_bar_right", horizontal=True, horizontal_alignment="right",
                          vertical_alignment="center", width="content"):
            if not primary_enabled and blocked_reason:
                cls = "moa-barhint moa-barhint-warn" if warn else "moa-barhint"
                if blocked_action:
                    # 막는 이유를 누르면 그것을 처리할 수 있는 화면으로 간다 (2026-11-05 3차 보고 7번).
                    # 이유만 적어 두면 담당자는 어디서 풀어야 하는지 알 수 없다
                    with st.container(key=f"{primary_key}_blocked"):
                        if st.button(blocked_reason, key=f"{primary_key}_blockedgo",
                                     icon=":material/arrow_forward:", icon_position="right"):
                            blocked_action()
                else:
                    st.html(f'<div class="{cls}">{_esc(blocked_reason)}</div>')
            if primary_slot is not None:
                primary_slot()
            else:
                primary_clicked = st.button(primary_label, key=primary_key, type="primary",
                                            disabled=not primary_enabled, icon=primary_icon)
    return back_clicked, primary_clicked


def fetch_failed(err, *, brand: dict | None = None, ops_mode: bool = False) -> None:
    """화면을 그릴 자료를 받지 못했을 때 — 오류 추적 대신 서버가 준 한 줄과 [다시 불러오기]만 보인다.

    기술 문구(`detail`)는 보여주지 않는다(D-02 2.2). 넣은 대화 · 정리 결과는 그대로 둔다(U-9).
    """
    if ops_mode:
        header(brand=None, ops_login=True)
    else:
        header(brand=brand)
    status_line({"tone": "danger", "text": getattr(err, "user_message", None) or copy.NETWORK_FAILED})
    with st.container(key="moa_retry"):
        if st.button(copy.RETRY_FETCH, key="retry_fetch", icon=":material/refresh:"):
            st.rerun()
    footnote()
    st.stop()


def footnote() -> None:
    """가격 기준 고지 — 모든 담당자 화면 맨 아래 한 줄.

    문구는 API-002 `price_notice`를 그대로 쓴다. 기준일이 바뀌어도 화면 코드를 고치지 않는다.
    """
    try:
        notice = api.meta().get("price_notice") or copy.PRICE_NOTICE_FALLBACK
    except Exception:  # 서버에 닿지 못했을 때도 고지는 비우지 않는다
        notice = copy.PRICE_NOTICE_FALLBACK
    st.html(f'<div class="moa-footnote">{_esc(notice)}</div>')
    _preview_notice()


def _preview_notice() -> None:
    """모의 응답을 쓴 구간이 있으면 알린다 — 화면이 동작하는 척하지 않게 하기 위해서다.

    담당자용 문구가 아니라 **개발 중 표시**이며, `MOA_UI_PREVIEW=0`이면 사라진다.
    서버가 그 구간에 응답하기 시작하면 자동으로 없어진다.
    """
    used = api.preview_used()
    if not (mock.PREVIEW_ENABLED and used):
        return
    st.html(f'<div class="moa-devnote">화면 미리보기 — 서버가 아직 응답하지 않는 구간을 예시값으로 '
            f'채웠습니다 ({_esc(", ".join(sorted(used)))}). MOA_UI_PREVIEW=0 으로 끌 수 있습니다.</div>')
