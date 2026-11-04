# SCR-001. A. 주문 시작 (대화 입력) — URL `/`
#
# 출처: P-06 SCR-001 · 정본 시안 `Moa_전체화면.svg` 케이스 01 ~ 07
#   01 입력 전 · 02 예시 대화 채움 · 03 사진 입력 안내 · 04 · 05 O-0 비밀번호 ·
#   06 매장 되묻기 · 07 기타 · 매장 직접 입력
#
# 배치 — 가운데 760px 한 열: 배너 → Moa 소개 카드 → (대화 미리보기) → 입력 바 → 안내 한 줄
#
# 이 화면이 하지 않는 것
#   - 브랜드 선택 UI를 두지 않는다 (PRD 2.4.1 · FR-001)
#   - 이미지를 받지 않는다 (범위 밖 — PRD 2.3). 안내만 하고 입력은 유지한다
#   - 파일 형식을 판정하지 않는다. 내용을 읽어 입력창에 채우는 데까지만 한다
#   - 미리보기는 형식 파싱 결과 표시일 뿐 판정이 아니다
import streamlit as st

import api_client
from moa import api, components as c, copy, dialogs, icons, layout, mock, nav, state

st.session_state["_page"] = "start"
layout.page_setup()

# --- 1 헤더 — 로고 · 단계 표시. 매장 기준은 판별 전이므로 표시하지 않는다 ------
layout.header(brand=None)

# --- 2 상태 줄 — 늘 같은 한 줄이다 -------------------------------------------
# 받지 않은 입력(사진 · 지원하지 않는 파일) 안내는 **입력 바 바로 위**에 띄우고
# 상태 줄은 그대로 둔다 (정본 시안 케이스 03 — 상태 줄 문구가 바뀌지 않는다).
layout.status_line({"tone": "info", "text": copy.S1_STATUS})


def _fill_sample() -> None:
    """API-010 — 기준 입력을 **미리보기 묶음에만** 채운다. 입력창은 비워 둔다."""
    try:
        data = api.get(lambda: api_client.get_sample_conversation(),
                       fallback=mock.SAMPLE_CONVERSATION, label="sample")
    except api_client.ApiError as err:
        st.session_state[state.NOTICE] = err.user_message or copy.NETWORK_FAILED
        return
    st.session_state[state.PREVIEW] = {
        "messages": data.get("messages", []),
        "summary_text": data.get("summary_text"),
        "unreadable_lines": [],
        "can_proceed": True,
    }
    st.session_state[state.PREVIEW_IS_SAMPLE] = True
    st.session_state[state.SAMPLE_RAW] = data.get("raw_text", "")
    st.session_state[state.NOTICE] = None


# 입력창 위젯 키에 판 번호를 붙인다.
# 왜: `.txt`를 읽어 입력창을 채우는 일은 **입력창이 이미 그려진 뒤**에 일어난다.
# 그때 위젯 키에 값을 쓰면 Streamlit이 "이미 만들어진 위젯은 못 바꾼다"고 막는다.
# 판 번호를 올려 **다음 재실행에서 새 위젯으로 그리면** 채운 값이 그대로 들어간다.
def _input_key() -> str:
    return f"raw_input_{st.session_state.get('_input_rev', 0)}"


def _reset_input(text: str) -> None:
    st.session_state[state.RAW_TEXT] = text
    st.session_state["_input_rev"] = st.session_state.get("_input_rev", 0) + 1


def _clear_preview() -> None:
    st.session_state[state.PREVIEW] = None
    st.session_state[state.PREVIEW_IS_SAMPLE] = False
    st.session_state[state.SAMPLE_RAW] = ""
    _reset_input("")
    st.rerun()


def _refresh_preview(text: str) -> None:
    """API-011 — 붙여넣은 대화를 형식만 파싱해 미리보기를 만든다. LLM 호출 0건."""
    try:
        data = api.get(lambda: api_client.preview_conversation(raw_text=text),
                       fallback=mock.preview_from(text), label="preview")
    except api_client.ApiError as err:
        # 미리보기를 못 받아도 넣은 대화는 그대로 두고 [정리하기]도 막지 않는다 — 판정은 서버가 한다
        st.session_state[state.PREVIEW] = None
        st.session_state[state.NOTICE] = err.user_message or copy.NETWORK_FAILED
        return
    st.session_state[state.PREVIEW] = data
    st.session_state[state.PREVIEW_IS_SAMPLE] = False


def _intro_html() -> str:
    what = c.esc(copy.S1_WHAT).replace("**[정리하기]**", "<b>[정리하기]</b>")
    what = what.replace("**", "")
    tiles = "".join(
        f'<div class="moa-step-tile"><span class="moa-step-no{" moa-step-no-on" if i == 1 else ""}">'
        f'{i}</span>{c.esc(text)}</div>' for i, text in enumerate(copy.S1_STEPS, start=1))
    examples = []
    for line in copy.S1_FORMAT_EXAMPLES:
        name, _, text = line.partition("]")
        examples.append(f"<div><b>{c.esc(name)}]</b>{c.esc(text.strip())}</div>")
    return (f'<div class="moa-intro-title">{c.esc(copy.S1_GREETING)}</div>'
            f'<div class="moa-intro-desc">{what}</div>'
            f'<div class="moa-intro-label">{c.esc(copy.S1_STEPS_TITLE)}</div>'
            f'<div class="moa-steps-grid">{tiles}</div>'
            f'<div class="moa-intro-label">{c.esc(copy.S1_FORMAT_TITLE)}</div>'
            f'<div class="moa-format-box">{"".join(examples)}</div>')


def _preview_rows(preview: dict) -> str:
    rows = "".join(
        f'<span class="moa-preview-name">{c.esc(m.get("sender"))}</span>'
        f'<span class="moa-preview-text">{c.esc(m.get("text"))}</span>'
        for m in preview.get("messages", []))
    unreadable = preview.get("unreadable_lines") or []
    rows += "".join(
        f'<span class="moa-preview-name moa-preview-bad">{c.esc(copy.S1_UNREADABLE_LABEL)}</span>'
        f'<span class="moa-preview-text moa-preview-bad">{c.esc(line.get("text"))}</span>'
        for line in unreadable)
    # 읽지 못한 줄이 있어도 나머지로 계속 진행할 수 있다 — 글자로 알린다(U-8)
    warns = "".join(f'<span class="moa-warn">{c.esc(line.get("notice_text"))}</span>'
                    for line in unreadable)
    return (f'<div class="moa-preview-rows">{rows}</div>'
            f'<div class="moa-preview-foot">{icons.icon("users", 14)}'
            f'{c.esc(preview.get("summary_text"))}{warns}</div>')


preview = st.session_state.get(state.PREVIEW)

with st.container(key="moa_s1"):
    # --- 배너 ---------------------------------------------------------------------
    st.html(f'<div class="moa-hero"><div><div class="moa-hero-kicker">{c.esc(copy.S1_HERO_KICKER)}</div>'
            f'<div class="moa-hero-title">{"<br>".join(c.esc(t) for t in copy.S1_HERO_TITLE)}</div></div>'
            f'{icons.cup_badge()}</div>')

    # --- 3 서비스 소개 — Moa 카드 하나 + 빠른 버튼 ---------------------------------
    with st.container(key="moa_says_intro", horizontal=True):
        st.html(f'<span class="moa-avatar moa-avatar-lg">{icons.logo(20)}</span>')
        with st.container(key="moa_intro"):
            st.html(_intro_html())
            if not preview:
                # 이미 넣은 대화가 있으면 바꿀 것인지 먼저 알린다 (P-06 SCR-001 요소 3)
                label = copy.S1_QUICK_SAMPLE
                if st.session_state.get(state.RAW_TEXT):
                    label = f"{copy.S1_QUICK_SAMPLE} · {copy.S1_SAMPLE_REPLACE_ASK}"
                if st.button(label, key="link_sample", icon=":material/description:"):
                    _fill_sample()
                    st.rerun()

    # --- 4 대화 미리보기 묶음 ------------------------------------------------------
    if preview:
        is_sample = st.session_state[state.PREVIEW_IS_SAMPLE]
        title = copy.S1_PREVIEW_TITLE_SAMPLE if is_sample else copy.S1_PREVIEW_TITLE_PASTE
        badge = c.pill(copy.S1_PREVIEW_BADGE_SAMPLE, "gray") if is_sample else ""
        with st.container(key="moa_says_preview", horizontal=True):
            st.html("<span></span>")
            with st.container(key="moa_preview"):
                with st.container(key="moa_preview_head", horizontal=True,
                                  horizontal_alignment="distribute", vertical_alignment="center"):
                    st.html(f'<div class="moa-preview-title">{icons.icon("file", 16)}'
                            f'{c.esc(title)}{badge}</div>')
                    if st.button(copy.S1_PREVIEW_CLEAR, key="link_mute_clear"):
                        _clear_preview()
                st.html(_preview_rows(preview))

    # --- 받지 않은 입력 안내 — 입력 바 바로 위 (케이스 03) -------------------------
    notice = st.session_state.get(state.NOTICE)
    if notice:
        st.html(f'<div class="moa-toast-pill">{icons.icon("alert", 16)}{c.esc(notice)}</div>')

    # --- 6 [+] 파일 불러오기 · 7 대화 입력창 · 8 정리하기 ---------------------------
    # Streamlit은 드래그 상태를 감지해 입력창 자리표시를 바꿀 수 없다 → [+]가 파일 고르기다
    # (P-06 Streamlit 구현 대응). 업로더 자체도 끌어다 놓기를 받는다.
    with st.container(key="moa_inputbar", horizontal=True, vertical_alignment="center"):
        with st.container(key="moa_upload", width="content"):
            uploaded = st.file_uploader(copy.S1_FILE_LABEL, key="conv_file",
                                        label_visibility="collapsed")
        raw_text = st.text_area(
            copy.S1_INPUT_PLACEHOLDER, value=st.session_state.get(state.RAW_TEXT, ""),
            placeholder=copy.S1_INPUT_PLACEHOLDER, height=68, key=_input_key(),
            label_visibility="collapsed", help=None)
        submit_slot = st.container(width="content")

# 넣은 대화 — **입력창의 지금 값**이 먼저다 (2026-11-05 3차 보고 1번).
#
# 예전에는 입력이 바뀌면 여기서 바로 `st.rerun()` 을 걸어 미리보기를 새로 그렸다. 그런데 [정리하기]를
# 누르면 입력창이 blur 되어 **값 변경과 버튼 클릭이 같은 재실행에 함께 도착한다** — 그때 여기서 재실행을
# 걸면 버튼 처리 코드에 닿기도 전에 run 이 끊겨, 첫 클릭은 "값만 들어가고" 아무 일도 일어나지 않았다.
# 그래서 입력 반영은 **버튼 처리 뒤로** 미루고(파일 끝), 여기서는 값만 읽는다.
changed_text = raw_text != st.session_state.get(state.RAW_TEXT)
pending_raw = raw_text or st.session_state.get(state.SAMPLE_RAW) or ""
has_conversation = bool(pending_raw.strip())


def _submit() -> None:
    """API-012 — 분석 요청. 매장 기준 판별은 서버가 규칙으로 한다(LLM 전)."""
    if not pending_raw.strip():
        # 빈 채로 눌렀다 — 서버를 부르지 않고 무엇을 해야 하는지 알린다(3차 보고 1번)
        st.session_state[state.NOTICE] = copy.S1_SUBMIT_DISABLED_REASON
        st.rerun()
        return
    source = "sample" if st.session_state.get(state.PREVIEW_IS_SAMPLE) else "paste"
    try:
        data = api.get(lambda: api_client.create_session(pending_raw, source=source),
                       fallback=mock.create_session(pending_raw), label="analyze")
    except api_client.ApiError as err:
        # 입력은 유지하고 서버가 준 문구만 보여준다 (U-9 · D-02 2.2)
        st.session_state[state.NOTICE] = err.user_message
        st.rerun()
        return

    state.remember_session(data)
    if data.get("brand_question"):
        # 되묻기는 오류가 아니다 — 정리 전에 한 번 묻는다 (F-024)
        st.session_state[state.BRAND_QUESTION] = data["brand_question"]
        st.rerun()
        return
    if data.get("user_notice"):
        st.session_state[state.NOTICE] = data["user_notice"]
    st.session_state[state.CHAT] = []
    nav.go("review")


with submit_slot:
    # 화면의 유일한 주 버튼 (U-1). **붙여넣자마자 누를 수 있다** (2026-11-05 3차 보고 1번).
    #
    # 왜 비활성으로 두지 않는가: Streamlit 의 입력창은 **바깥을 누르거나 Ctrl+Enter 를 해야** 값이 서버로
    # 간다. 넣은 대화가 있어야 활성으로 두면, 붙여넣은 직후에는 버튼이 회색이라 "먹통"으로 보인다
    # (활성화까지 담당자가 한 번 더 클릭해야 했다 — 실측: 바깥을 누른 뒤에는 244ms).
    # 버튼을 누르면 입력창이 먼저 blur 되어 **같은 재실행에서 값이 함께 도착한다** — 그 값으로 분석한다.
    # 그래도 비어 있으면 서버를 부르지 않고 안내만 한다(아래 `_submit`).
    if st.button(copy.S1_SUBMIT, key="submit_analyze", type="primary",
                 disabled=bool(st.session_state.get(state.BRAND_QUESTION)),
                 help=None if has_conversation else copy.S1_SUBMIT_DISABLED_REASON):
        with st.spinner(""):     # 문구 없이 돌아가는 표시만 (중복 클릭 방지는 그대로)
            _submit()

# --- 입력 반영 — 버튼을 처리한 뒤에 한다(위 주석) -----------------------------
if changed_text:
    st.session_state[state.RAW_TEXT] = raw_text
    st.session_state[state.SAMPLE_RAW] = ""
    st.session_state[state.NOTICE] = None
    if raw_text.strip():
        _refresh_preview(raw_text)
    else:
        st.session_state[state.PREVIEW] = None
    st.rerun()

if uploaded is not None and st.session_state.get("_last_file") != uploaded.file_id:
    st.session_state["_last_file"] = uploaded.file_id
    payload = uploaded.getvalue()
    try:
        # 확장자 제한을 걸지 않는다 — 걸면 설계 문구가 아니라 Streamlit 오류가 뜬다
        data = api.get(lambda: api_client.preview_conversation(file=(uploaded.name, payload)),
                       fallback=None, label="preview_file")
        st.session_state[state.PREVIEW] = data
        st.session_state[state.PREVIEW_IS_SAMPLE] = False
        _reset_input(data.get("raw_text", st.session_state[state.RAW_TEXT]))
    except api_client.ApiError as err:
        if mock.PREVIEW_ENABLED and isinstance(err, api_client.ApiUnreachable):
            api.preview_used().add("preview_file")
            text, code = mock.judge_file(uploaded.name, payload)
            if code:
                # 받지 않고 안내만 한다. 입력한 대화는 유지한다 (U-9 · PRD 8.1 #27)
                st.session_state[state.NOTICE] = mock.FILE_ERRORS[code]
            else:
                _reset_input(text)
                _refresh_preview(text)
        else:
            st.session_state[state.NOTICE] = err.user_message
    st.rerun()

# --- 5 매장 요청 안내 — 별도 요청 칸을 두지 않는다 ---------------------------
with st.container(key="moa_s1_under"):
    st.html(f'<div class="moa-under">{c.esc(copy.S1_STORE_CAPTION)}</div>')

# --- 매장 되묻기 모달 (케이스 06 · 07) --------------------------------------
if st.session_state.get(state.BRAND_QUESTION):
    dialogs.brand_dialog()

# --- 9 가격 기준 고지 ---------------------------------------------------------
layout.footnote()
