# 서버 호출과 모의 응답을 잇는 한 지점
#
# 화면 코드는 `api.get(...)` 하나만 쓰고, **응답이 실제인지 모의인지 모른다**.
# 모의 전환을 화면마다 분기하면 그 분기가 화면 코드에 번지고, 서버가 붙은 뒤에
# 지워야 할 곳을 찾지 못한다.
#
#   서버가 응답했다           -> 그 응답을 쓴다
#   서버가 응답하지 못했고     -> 미리보기 모드면 모의 응답을 쓰고, 썼다는 사실을 기록한다
#   미리보기 모드가 아니다     -> ApiError를 그대로 올려 화면이 `user_message`를 보여준다
import time

import streamlit as st

import api_client
from moa import mock

PREVIEW_USED = "_preview_used"
DOWN_UNTIL = "_backend_down_until"

# 서버에 닿지 못한 직후에는 잠깐 다시 걸지 않는다.
#
# 왜 필요한가: 한 화면이 7 ~ 9개 엔드포인트를 부르고, 운영 대시보드는 5초마다 다시 그린다.
# 서버가 없으면 매 재실행이 연결 실패를 그 수만큼 다시 겪어 **화면이 끝까지 그려지기 전에
# 다음 갱신이 시작된다**(실측: 운영 대시보드가 영영 완성되지 않았다).
# 아래 간격만큼은 바로 모의 응답으로 넘어가고, 그 뒤에는 다시 서버를 시험한다 —
# 서버가 올라오면 이 간격 안에 알아서 붙는다.
RETRY_AFTER_SEC = 5.0


def preview_used() -> set:
    if PREVIEW_USED not in st.session_state:
        st.session_state[PREVIEW_USED] = set()
    return st.session_state[PREVIEW_USED]


def get(call, *, fallback=None, label=None):
    """`call`은 인자가 묶인 호출식(람다)이다.

    `fallback`이 없으면 미리보기 모드에서도 모의로 대신하지 않는다 —
    모의 데이터가 없는 구간을 조용히 비워 두지 않기 위해서다.
    """
    can_fall_back = mock.PREVIEW_ENABLED and fallback is not None
    if can_fall_back and time.monotonic() < st.session_state.get(DOWN_UNTIL, 0.0):
        preview_used().add(label or "unknown")
        return fallback
    try:
        return call()
    except api_client.ApiUnreachable as err:
        st.session_state[DOWN_UNTIL] = time.monotonic() + RETRY_AFTER_SEC
        if can_fall_back:
            preview_used().add(label or "unknown")
            return fallback
        raise err
    except api_client.ApiError as err:
        # 서버가 답은 했다(업무 오류). 연결은 살아 있으므로 다시 거는 것을 막지 않는다
        if can_fall_back:
            preview_used().add(label or "unknown")
            return fallback
        raise err


def act(call, *, fallback=None, label=None) -> dict:
    """쓰기 호출(채팅 · 질문 답 · 행 편집 · 되돌리기 · 답장 · 공유) — 실패를 **화면 예외로 올리지 않는다.**

    실패하면 `{"_error": True, "text": user_message, "user_message": user_message}` 를 돌려준다.
    호출부는 `_error` 면 성공일 때만 하는 상태 변경(제안 표시 · 되돌리기 버튼 지우기 등)을 건너뛴다.
    기술 문구는 보여주지 않는다 — `user_message` 만(D-02 2.2).
    """
    try:
        return get(call, fallback=fallback, label=label)
    except api_client.ApiError as err:
        message = err.user_message or "잠시 후 다시 눌러 주세요"
        return {"_error": True, "text": message, "user_message": message, "code": err.code}


def meta() -> dict:
    """API-002 — 가격 기준 고지 문구는 서버가 완성형으로 준다."""
    from moa import state

    if st.session_state.get(state.META) is None:
        st.session_state[state.META] = get(
            lambda: api_client.get_meta(), fallback=mock.META, label="meta")
    return st.session_state[state.META]
