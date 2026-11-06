# SCR-006. O. 운영 대시보드 — URL `/ops`
#
# 출처: 정본 시안 `Moa_운영대시보드.svg`(24 승인 필요 · 25-1 주입 직후 · 25-2 복구 중 · 25-3 복구 완료 ·
#       26 정상 운영) · 05.리포트/운영대시보드_고도화안.md v0.2 (블록 A ~ F)
#
#   A 상태 배너      지금 괜찮은가 · 내가 할 일이 있는가 (승인 카드는 배너 안에서 펼친다)
#   B 핵심 수치 4칸  목표를 지키고 있는가 — 숫자 옆에 목표와 판정 글자
#   C 지금 요청 경로  게이트웨이 · 해석기 · 메뉴 저장소 신호등
#   D 장애 시험 결과  F-1 ~ F-6 × 회차 격자 (30초마다 다시 받는다)
#   E 최근 사건      행을 누르면 타임라인 막대 + 진단 · 전략 · 시도 · 검증
#   F 주문 처리 기록(접힘) · 장애 주입 도구줄(실습)
#
# 자료를 화면 자료로 바꾸는 일은 `moa/ops_view.py`(순수 함수)가 한다. 이 파일은 조회 · 버튼 · 펼침만 맡는다.
#
# 인증 — 화면 맨 앞에서 인증 플래그를 확인하고, 없으면 O-0 구성만 그리고 멈춘다.
# **사건 · 처리 기록 조회 API를 호출하지 않는다**(P-06 "운영 대시보드 인증 유지 · 차단").
import time

import streamlit as st

import api_client
from moa import api, components as c, copy, dialogs, icons, layout, mock, ops_view as ov, state

st.session_state["_page"] = "ops"
layout.page_setup()

# --- 미인증 직접 접근 — 대화상자 대신 같은 구성의 단독 화면 ------------------
if not st.session_state.get(state.OPS_AUTHED):
    layout.header(brand=None, ops_login=True)
    with st.container(key="moa_ops_login"):
        submitted, _, password = dialogs.ops_login_form("ops_login_standalone", with_cancel=False)
    if submitted:
        dialogs.try_ops_login(password)
        st.rerun()
    st.stop()   # 여기서 멈춘다 — 사건 조회 API 호출 0건

_ORDER_TONE = {"주문 확정": "green", "공유 완료": "green"}

TRIALS_EVERY_SEC = 30          # D 는 30초마다 — F-6(DB 장애) 시험 중 대시보드가 DB 를 두드리지 않게
_TRIALS_CACHE = "_ops_trials_cache"
_APPR_OPEN = "_ops_appr_open"
_ORD_LIST_OPEN = "_ops_orders_open"
_FAULT_ASK = "_fault_ask"
# 미리보기 전용 — [F-1] 을 누른 시각. 지난 초로 25-1 → 25-2 → 25-3 을 흉내 낸다
_PREVIEW_INJECT_AT = "_ops_preview_inject_at"
_PREVIEW_DETECT_SEC = 8
_PREVIEW_RECOVER_SEC = 41


# --- 미리보기 대역 (MOA_UI_PREVIEW=1) ------------------------------------------
def _preview_scene() -> dict:
    """정본 시안 상태 하나 — `_preview_case` 세션 값으로 고른다(화면 테스트가 쓴다)."""
    label = st.session_state.get("_preview_case") or "24 승인 필요"
    name = mock.OPS_PREVIEW_CASES.get(label, "approval")
    started = st.session_state.get(_PREVIEW_INJECT_AT)
    if started is None:
        return mock.ops_scene(name)
    sec = int(time.monotonic() - started)
    name = ("injected" if sec < _PREVIEW_DETECT_SEC
            else "recovering" if sec < _PREVIEW_RECOVER_SEC else "recovered")
    return mock.ops_scene(name, injected_sec=sec)


def _fill(data: dict, sample: dict, keys: tuple, label: str) -> dict:
    """서버 응답에 아직 없는 칸(G-1 · G-3 · G-4 등)을 미리보기에서만 견본으로 채운다.

    채웠다면 하단 개발 표시에 이름을 남긴다 — 화면이 동작하는 척하지 않게.
    미리보기가 아니면 채우지 않고 화면이 `미측정` · `상태 미수집` 으로 그린다.
    """
    if not mock.PREVIEW_ENABLED:
        return data
    missing = [k for k in keys if k not in data and k in sample]
    if not missing:
        return data
    api.preview_used().add(label)
    return {**data, **{k: sample[k] for k in missing}}


def _trials(ops_token, scene) -> dict | None:
    """D 장애 시험 결과 — 30초 묶음. 서버가 없으면 미리보기 견본, 그것도 없으면 None(빈 안내)."""
    cache = st.session_state.get(_TRIALS_CACHE)
    scene_key = scene["name"] if scene else None
    if cache and time.monotonic() - cache["at"] < TRIALS_EVERY_SEC and cache.get("scene") == scene_key:
        return cache["data"]
    try:
        data = api.get(lambda: api_client.ops_trials(ops_token=ops_token),
                       fallback=scene["trials"] if scene else None, label="ops_trials")
    except api_client.ApiError:
        data = None     # 시험 결과가 없어도 나머지 블록은 그린다
    st.session_state[_TRIALS_CACHE] = {"at": time.monotonic(), "data": data, "scene": scene_key}
    return data


def _drop_trials_cache() -> None:
    st.session_state.pop(_TRIALS_CACHE, None)


# --- A 상태 배너 ---------------------------------------------------------------
def _banner(b: dict, ops_token) -> None:
    approvals = b["approvals"]
    with st.container(key=f"moa_banner_{b['tone']}"):
        with st.container(key="moa_banrow", horizontal=True, horizontal_alignment="distribute",
                          vertical_alignment="center"):
            st.html(ov.banner_head_html(b))
            if approvals:
                opened = st.session_state.get(_APPR_OPEN, True)
                label = copy.OA_APPROVAL_TOGGLE.format(n=len(approvals))
                with st.container(key="card_appr_toggle", width="content"):
                    st.html(f'<div class="moa-ban-toggle{" moa-ban-toggle-open" if opened else ""}">'
                            f'{c.esc(label)}{icons.icon("chevron-down", 14)}</div>')
                    if st.button(label, key="hit_appr_toggle"):
                        st.session_state[_APPR_OPEN] = not opened
                        st.rerun()
            else:
                st.html(f'<div class="moa-ban-none">{c.esc(copy.OA_NO_APPROVAL)}</div>')

        if approvals and st.session_state.get(_APPR_OPEN, True):
            for approval in approvals:
                iid = approval["incident_id"]
                with st.container(key=f"moa_appr_{iid}", horizontal=True,
                                  horizontal_alignment="distribute", vertical_alignment="center"):
                    st.html(ov.approval_html(approval))
                    with st.container(key=f"appr_btns_{iid}", horizontal=True, width="content"):
                        if st.button(copy.O4_REJECT, key=f"rej_{iid}"):
                            _decide(iid, "reject", ops_token)
                        if st.button(copy.O4_APPROVE, key=f"apr_{iid}", type="primary"):
                            _decide(iid, "approve", ops_token)
        if b.get("alert"):
            st.html(ov.alert_html(b["alert"]))


def _decide(incident_id: str, decision: str, ops_token) -> None:
    """API-044 — 첫 결정만 반영된다. 이미 결정된 사건은 409다."""
    data = api.act(lambda: api_client.ops_decide(incident_id, decision, ops_token=ops_token),
                   fallback={"user_message": f'{incident_id} {"승인함" if decision == "approve" else "거부함"}'},
                   label="ops_decision")
    if mock.PREVIEW_ENABLED and not data.get("_error"):
        st.session_state["_preview_case"] = "26 정상 운영"
    _drop_trials_cache()
    st.toast(data.get("user_message", ""))
    st.rerun()


# --- E 최근 사건 -----------------------------------------------------------------
def _incidents(incidents: dict, ops_token, scene) -> None:
    with st.container(key="moa_inc_card"):
        st.html(f'<div class="moa-ops-title"><b>{c.esc(copy.OE_TITLE)}</b>'
                f'<span>{c.esc(copy.OE_HINT)}</span></div>')
        rows = ov.incident_rows(incidents)
        if not rows:
            st.html(f'<div class="moa-ops-empty">{c.esc(copy.OE_EMPTY)}</div>')
        opened = st.session_state.get(state.OPS_INCIDENT_OPEN)
        for row in rows:
            iid = row["id"]
            with st.container(key=f"card_inc_{iid}"):
                st.html(ov.incident_row_html(row, opened == iid))
                if st.button(f"{iid} 자세히 보기", key=f"hit_inc_{iid}"):
                    st.session_state[state.OPS_INCIDENT_OPEN] = None if opened == iid else iid
                    st.rerun()
            if opened == iid:
                sample = (scene or {}).get("details", {}).get(iid) or mock.OPS_INCIDENT_DETAIL.get(iid)
                detail = api.get(lambda: api_client.ops_incident(iid, ops_token=ops_token),
                                 fallback=sample, label="ops_incident")
                st.html(ov.incident_detail_html(detail) if detail else
                        f'<div class="moa-ops-empty">{c.esc(copy.OE_DETAIL_PENDING)}</div>')


# --- F 주문 처리 기록 (접힘) ------------------------------------------------------
def _order_detail(order_id: str, detail: dict) -> str:
    """케이스 23 — 시각 · 누구 · 전 → 후 · 방법. 전은 회색, 후는 진하게."""
    head = "".join(f'<span>{c.esc(col)}</span>' for col in copy.O6_DETAIL_COLUMNS)
    rows = []
    for ch in detail.get("changes", []):
        before, sep, after = str(ch.get("before_after", "")).partition(" → ")
        change = (f'<span class="moa-det-before">{c.esc(before)}</span> → '
                  f'<span class="moa-det-after">{c.esc(after)}</span>' if sep else c.esc(before))
        rows.append(f'<div class="moa-tr moa-det-grid"><span class="moa-td moa-num">{c.esc(ch.get("at_text"))}</span>'
                    f'<span class="moa-det-who">{c.esc(ch.get("who"))}</span>'
                    f'<span class="moa-td">{change}</span>'
                    f'<span><span class="moa-method">{c.esc(ch.get("method_text"))}</span></span></div>')
    shares = detail.get("share_history") or []
    share_html = ""
    if shares:
        # API-048 share_history — 언제 어떻게 공유(= 완료)했는가
        share_html = (f'<div class="moa-step-note" style="padding:8px 0">{c.esc(copy.O6_SHARE_LABEL)} · '
                      + " · ".join(f'{c.esc(sh.get("at_text"))} {c.esc(sh.get("method_text"))}' for sh in shares)
                      + "</div>")
    # 관리 링크 · 토큰 · 원문 대화 전문은 보여주지 않는다 (NFR-003)
    return (f'<div class="moa-detail"><div class="moa-detail-title">{c.esc(order_id)} 상세</div>'
            f'<div class="moa-tr moa-th moa-det-grid">{head}</div>{"".join(rows)}{share_html}</div>')


def _orders_toggle(orders: dict) -> None:
    opened = st.session_state.get(_ORD_LIST_OPEN, False)
    count = len(orders.get("orders") or [])
    with st.container(key="moa_ord_card"):
        with st.container(key="card_ord_toggle"):
            st.html(f'<div class="moa-ord-toggle"><b>{c.esc(copy.O6_TITLE)}</b>'
                    f'<span>{c.esc(copy.OF_ORDERS_COUNT.format(n=count))}</span>'
                    f'<i class="moa-chev{" moa-chev-up" if opened else ""}">{icons.icon("chevron-down", 16)}</i></div>')
            if st.button(f"{copy.O6_TITLE} 펼치기", key="hit_ord_toggle"):
                st.session_state[_ORD_LIST_OPEN] = not opened
                st.rerun()


def _orders_body(orders: dict, ops_token) -> None:
    """펼치면 기존 O-6 표 그대로 — 조회 전용이라 주 버튼이 없다."""
    with st.container(key="moa_ord_body"):
        with st.container(key="moa_ord_head", horizontal=True, horizontal_alignment="distribute",
                          vertical_alignment="center"):
            st.html(f'<div class="moa-ops-title"><b>{c.esc(copy.O6_TITLE)}</b></div>')
            query = st.text_input(copy.O6_SEARCH_HINT, placeholder=copy.O6_SEARCH_HINT,
                                  key="ops_order_q", label_visibility="collapsed", width=300,
                                  icon=":material/search:")
        head = "".join(f"<span>{c.esc(col)}</span>" for col in copy.O6_COLUMNS) + "<span></span>"
        st.html(f'<div class="moa-tr moa-th moa-ord-grid">{head}</div>')
        # 찾기는 받은 목록을 글자로 거르는 것까지다 — 조회 조건을 화면이 만들지 않는다
        order_rows = [o for o in orders.get("orders") or []
                      if not query or query in " ".join(str(v) for v in o.values())]
        opened_order = st.session_state.get(state.OPS_ORDER_OPEN)
        for o in order_rows:
            oid = o["order_id"]
            state_text = o.get("state_text", "")
            with st.container(key=f"card_ord_{oid}"):
                st.html(f'<div class="moa-tr moa-ord-grid"><span class="moa-td-id">{c.esc(oid)}</span>'
                        f'<span class="moa-td moa-td-plain">{c.esc(o.get("brand_label"))}</span>'
                        f'<span>{c.pill(state_text, _ORDER_TONE.get(state_text, "gray"))}</span>'
                        f'<span class="moa-td moa-td-plain moa-num">{c.esc(o.get("confirmed_at_text"))}</span>'
                        f'<span class="moa-td moa-td-plain">{c.esc(o.get("change_count_text"))}</span>'
                        f'<span class="moa-td moa-td-plain">{c.esc(o.get("recovery_count_text"))}</span>'
                        f'<span class="moa-chev">{icons.icon("chevron-down", 16)}</span></div>')
                if st.button(f"{oid} 자세히 보기", key=f"hit_ord_{oid}"):
                    st.session_state[state.OPS_ORDER_OPEN] = None if opened_order == oid else oid
                    st.rerun()
            if opened_order == oid:
                detail = api.get(lambda: api_client.ops_order(oid, ops_token=ops_token),
                                 fallback=mock.OPS_ORDER_DETAIL.get(oid, {"changes": []}),
                                 label="ops_order")
                st.html(_order_detail(oid, detail))


# --- F 장애 주입 도구줄 (실습 전용) ----------------------------------------------
def _fault_bar(status: dict) -> None:
    active = (status.get("active_injection") or {}).get("code")
    with st.container(key="moa_fault", horizontal=True, vertical_alignment="center", width="content"):
        st.html(f'<div class="moa-fault-title">{c.esc(copy.OF_FAULT_TITLE)}</div>')
        with st.container(horizontal=True, width="content", gap="small"):
            for code in copy.O5_FAULT_CODES:
                # 지금 주입 중인 유형은 검게 채운다(시안 25-1 · 25-2)
                if st.button(code, key=f"fault_{code}_on" if code == active else f"fault_{code}"):
                    st.session_state[_FAULT_ASK] = code
                    st.rerun()
            if st.button(copy.O5_FAULT_CLEAR, key="fault_clear"):
                st.session_state[_FAULT_ASK] = "clear"
                st.rerun()


def _fault_ask(ops_token) -> None:
    asking = st.session_state.get(_FAULT_ASK)
    if not asking:
        return
    # 누르면 확인을 거쳐 주입 시각을 기록한다 (P-06 SCR-006 요소 5)
    clearing = asking == "clear"
    with st.container(key="moa_fault_ask", horizontal=True, vertical_alignment="center"):
        ask = "주입한 장애를 모두 해제할까요?" if clearing else f"{asking} 장애를 주입할까요?"
        st.html(f'<div class="moa-sugg-ask">{c.esc(ask)} 실습 환경에서만 쓰는 기능이에요</div>')
        if st.button("실행", key="fault_yes", type="primary"):
            label = copy.O5_FAULT_CLEAR if clearing else asking
            data = api.act(
                lambda: api_client.ops_fault(None if clearing else asking,
                                             "clear" if clearing else "inject", ops_token=ops_token),
                fallback={"user_message": f"{label} 처리했어요"}, label="ops_fault")
            if mock.PREVIEW_ENABLED and not data.get("_error"):
                if clearing:
                    st.session_state.pop(_PREVIEW_INJECT_AT, None)
                    st.session_state["_preview_case"] = "26 정상 운영"
                elif asking == "F-1":
                    st.session_state[_PREVIEW_INJECT_AT] = time.monotonic()
            st.session_state[_FAULT_ASK] = None
            _drop_trials_cache()
            st.toast(data.get("user_message", ""))
            st.rerun()
        if st.button("그만두기", key="fault_no"):
            st.session_state[_FAULT_ASK] = None
            st.rerun()


# --- 5초 주기 부분 갱신 (P-06 Streamlit 구현 대응 "운영 대시보드 자동 갱신") ---
# 조회 · 렌더를 한 조각(fragment)에 담아 5초마다 이 부분만 다시 그린다. D 만 30초 묶음이다.
@st.fragment(run_every=5)
def dashboard() -> None:
    ops_token = st.session_state.get(state.OPS_TOKEN)
    scene = _preview_scene() if mock.PREVIEW_ENABLED else None
    sample = scene or mock.ops_scene("approval")

    try:
        status = api.get(lambda: api_client.ops_status(ops_token=ops_token),
                         fallback=sample["status"], label="ops_status")
        incidents = api.get(lambda: api_client.ops_incidents(ops_token=ops_token),
                            fallback=sample["incidents"], label="ops_incidents")
        metrics = api.get(lambda: api_client.ops_metrics(ops_token=ops_token),
                          fallback=sample["metrics"], label="ops_metrics")
        orders = api.get(lambda: api_client.ops_orders(ops_token=ops_token),
                         fallback=mock.OPS_ORDERS, label="ops_orders")
    except api_client.ApiError as err:
        # 5초마다 다시 묻는 조각이다 — 서버가 돌아오면 다음 갱신에서 저절로 채워진다
        layout.fetch_failed(err, ops_mode=True)

    # 서버에 아직 없는 칸 — 고도화안 9절 G-1(복제본) · 무결성 · 주입 진행 · 추세 경보
    status = _fill(status, sample["status"], ("replicas", "active_injection", "alerts", "probe_need"),
                   "ops_status+")
    detail = _fill(metrics.get("detail") or {}, sample["metrics"]["detail"],
                   ("integrity_issue_count", "mttr_max_sec"), "ops_metrics+")
    metrics = {**metrics, "detail": detail}
    st.session_state["_ops_status"] = status
    trial_sum = ov.trial_summary(_trials(ops_token, scene))

    # --- 헤더 — 갱신 표시 · 실습 환경 배지 · 오른쪽 끝 [나가기] ------------------
    layout.header(brand=None, ops_mode=True)

    with st.container(key="moa_ops"):
        _banner(ov.banner(status, incidents), ops_token)                  # A
        st.html(ov.kpis_html(ov.kpis(metrics, trial_sum)))                 # B
        with st.container(key="moa_ops_mid", horizontal=True):
            with st.container(key="moa_route_card"):                       # C
                st.html(ov.route_html(ov.route(status)))
            with st.container(key="moa_trial_card"):                       # D
                st.html(ov.trials_html(trial_sum))
        _incidents(incidents, ops_token, scene)                            # E
        with st.container(key="moa_ops_foot", horizontal=True, vertical_alignment="center"):
            _orders_toggle(orders)                                         # F
            _fault_bar(status)
        _fault_ask(ops_token)
        if st.session_state.get(_ORD_LIST_OPEN, False):
            _orders_body(orders, ops_token)

    layout._preview_notice()


dashboard()
