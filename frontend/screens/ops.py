# SCR-006. O. 운영 대시보드 — URL `/ops`
#
# 출처: P-06 SCR-006 · 정본 시안 `Moa_전체화면.svg` 케이스 04 · 05(O-0) · 22(O-1 ~ O-6) · 23(O-6 상세 펼침)
#
# 담당자 화면 원칙 중 U-1 · U-8만 같이 적용한다. 공통 진행 표시는 두지 않는다.
#
# 인증 — 화면 맨 앞에서 인증 플래그를 확인하고, 없으면 O-0 구성만 그리고 멈춘다.
# **사건 · 처리 기록 조회 API를 호출하지 않는다**(P-06 "운영 대시보드 인증 유지 · 차단").
import streamlit as st

import api_client
from moa import api, components as c, copy, dialogs, icons, layout, mock, state

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

# 상태 배지 색 — 승인 대기 주황 · 복구 성공 초록 · 실패 빨강 · 그 밖 회색 (시안 케이스 22)
_INCIDENT_TONE = {"awaiting_approval": "amber", "recovered": "green", "failed": "red",
                  "manual_check": "amber", "recovering": "gray", "detected": "gray"}
_ORDER_TONE = {"주문 확정": "green", "공유 완료": "green"}


def _incident_detail(detail: dict) -> str:
    """O-2 사건 상세 — 타임라인 + 항목(P-06 SCR-006 "O-2 사건 상세").

    주입 -> 탐지 -> 복구 시작 -> 정상화(또는 최종 실패) 시각과 진단 근거 · 선택 전략 ·
    시도 번호 · 대기시간 · 검증 결과를 항목별로 보여준다. **원시 JSON을 그대로 쏟지 않는다.**
    장애 코드 · 지표 이름은 운영자 화면이라 그대로 쓴다(D-02 3.1 — 담당자 화면에는 0건).
    """
    timeline = detail.get("timeline") or {}
    detection = detail.get("detection") or {}
    diagnosis = detail.get("diagnosis") or {}
    recovery = detail.get("recovery") or {}
    verification = detail.get("verification") or {}
    circuit = recovery.get("circuit") or {}
    tools = " · ".join(f'{t.get("tool")}({t.get("args")}) -> {t.get("result")}'
                       for t in recovery.get("tool_calls", []))
    attempts = " · ".join(f'{a.get("no")}회 {a.get("action")} {a.get("wait_ms")}ms {a.get("result")}'
                          for a in recovery.get("attempts") or [])
    checks = " · ".join(f'{ch.get("name")} {ch.get("result")}' for ch in verification.get("checks") or [])
    items = [
        ("시각", " → ".join(f"{label} {at or '-'}" for label, at in (
            ("주입", timeline.get("injected_at")), ("탐지", timeline.get("detected_at")),
            ("복구 시작", timeline.get("recovery_started_at")),
            ("정상화", timeline.get("resolved_at") or timeline.get("failed_at"))))),
        ("탐지 근거", f'{detection.get("metric", "")} · {detection.get("evidence", "")}'
                     f' (기준 {detection.get("threshold", "")})'),
        ("진단", f'{diagnosis.get("reason", "")} ({diagnosis.get("source", "")})'),
        ("선택 전략", recovery.get("strategy", "")),
        ("복구 시도", attempts or "-"),
        ("회로", f'{circuit.get("state", "-")} · 시험까지 {circuit.get("retry_probe_in_sec", "-")}초'),
        # 복구 도구 호출 인자를 남긴다(PRD 7.2)
        ("복구 도구", tools or "-"),
        # 사건 종료의 유일한 근거는 검증 판정이다(D-02 API-043)
        ("검증 판정", (verification.get("verdict") or "아직 검증하지 않음") + (f" · {checks}" if checks else "")),
        ("걸린 시간", f'{detail.get("elapsed_sec", "-")}초'),
    ]
    rows = "".join(f"<span>{c.esc(k)}</span><div>{c.esc(v)}</div>" for k, v in items)
    return (f'<div class="moa-detail"><div class="moa-detail-title"><span class="moa-mono">'
            f'{c.esc(detail.get("incident_id"))}</span> 상세 · {c.esc(detail.get("fault_code"))}</div>'
            f'<div class="moa-inc-detail" style="padding-bottom:10px">{rows}</div></div>')


def _order_detail(order_id: str, detail: dict) -> str:
    """케이스 23 — 시각 · 누구 · 전 → 후 · 방법. 전은 회색, 후는 진하게."""
    head = "".join(f'<span>{c.esc(col)}</span>' for col in copy.O6_DETAIL_COLUMNS)
    rows = []
    for ch in detail.get("changes", []):
        before, sep, after = str(ch.get("before_after", "")).partition(" → ")
        change = (f'<span class="moa-det-before">{c.esc(before)}</span> → '
                  f'<span class="moa-det-after">{c.esc(after)}</span>' if sep else c.esc(before))
        method = ch.get("method_text")
        rows.append(f'<div class="moa-tr moa-det-grid"><span class="moa-td moa-num">{c.esc(ch.get("at_text"))}</span>'
                    f'<span class="moa-det-who">{c.esc(ch.get("who"))}</span>'
                    f'<span class="moa-td">{change}</span>'
                    f'<span><span class="moa-method">{c.esc(method)}</span></span></div>')
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


# --- 5초 주기 부분 갱신 (P-06 Streamlit 구현 대응 "운영 대시보드 자동 갱신") ---
# 조회 · 렌더를 한 조각(fragment)에 담아 5초마다 이 부분만 다시 그린다.
@st.fragment(run_every=5)
def dashboard() -> None:
    ops_token = st.session_state.get(state.OPS_TOKEN)

    try:
        status = api.get(lambda: api_client.ops_status(ops_token=ops_token),
                         fallback=mock.OPS_STATUS, label="ops_status")
        st.session_state["_ops_status"] = status
        incidents = api.get(lambda: api_client.ops_incidents(ops_token=ops_token),
                            fallback={**mock.OPS_INCIDENTS, **mock.OPS_APPROVALS}, label="ops_incidents")
        metrics = api.get(lambda: api_client.ops_metrics(ops_token=ops_token),
                          fallback=mock.OPS_METRICS, label="ops_metrics")
        orders = api.get(lambda: api_client.ops_orders(ops_token=ops_token),
                         fallback=mock.OPS_ORDERS, label="ops_orders")
    except api_client.ApiError as err:
        # 5초마다 다시 묻는 조각이다 — 서버가 돌아오면 다음 갱신에서 저절로 채워진다
        layout.fetch_failed(err, ops_mode=True)

    # --- 헤더 — 갱신 표시 · 실습 환경 배지 · 오른쪽 끝 [나가기] ------------------
    layout.header(brand=None, ops_mode=True)

    with st.container(key="moa_ops"):
        # --- 1 O-4 승인 필요 — 상단 고정. 0건이어도 영역을 유지한다 -------------
        approvals = incidents.get("approvals") or []

        def _decide(incident_id, decision):
            """API-044 — 첫 결정만 반영된다. 이미 결정된 사건은 409다."""
            data = api.get(
                lambda: api_client.ops_decide(incident_id, decision, ops_token=ops_token),
                fallback={"user_message": f'{incident_id} {"승인함" if decision == "approve" else "거부함"}'},
                label="ops_decision")
            st.toast(data.get("user_message", ""))
            st.rerun()

        for approval in approvals:
            iid = approval["incident_id"]
            with st.container(key=f"moa_approval_{iid}", horizontal=True,
                              horizontal_alignment="distribute", vertical_alignment="center"):
                st.html(f'<div><div class="moa-appr-top">{c.esc(copy.O4_TITLE.format(n=len(approvals)))}'
                        f'<span class="moa-appr-id">{c.esc(iid)}</span>'
                        f'{c.pill(approval.get("waiting_text", ""), "strong")}</div>'
                        f'<div class="moa-appr-title">{c.esc(approval.get("summary"))}</div>'
                        f'<div class="moa-appr-reco">{c.esc(approval.get("recommendation_text"))}</div></div>')
                with st.container(key=f"appr_btns_{iid}", horizontal=True, width="content"):
                    if st.button(copy.O4_REJECT, key=f"rej_{iid}"):
                        _decide(iid, "reject")
                    if st.button(copy.O4_APPROVE, key=f"apr_{iid}", type="primary"):
                        _decide(iid, "approve")
        if not approvals:
            # 0건이어도 영역을 유지한다 (P-06 SCR-006 요소 1)
            with st.container(key="moa_approval_none"):
                st.html(f'<div class="moa-appr-top" style="color:var(--moa-muted-2)">'
                        f'{c.esc(copy.O4_EMPTY)}</div>')

        # --- 2 O-3 지금 상태 · 4 O-5 지표 -----------------------------------------
        with st.container(key="moa_ops_row2", horizontal=True):
            with st.container(key="moa_status_card"):
                svc = "".join(
                    f'<div class="moa-svc{" moa-svc-bad" if s.get("state") not in ("up",) else ""}">'
                    f'<span class="moa-svc-dot"></span><span class="moa-svc-name">{c.esc(s.get("name"))}</span>'
                    f'<span class="moa-svc-state">{c.esc(s.get("state_text"))}</span></div>'
                    for s in status.get("services", []))
                st.html(f'<div class="moa-card-title">{c.esc(copy.O3_TITLE)}</div>{svc}')
            with st.container(key="moa_metric_card"):
                tiles = "".join(f'<div class="moa-metric"><span>{c.esc(m.get("label"))}</span>'
                                f'<b class="moa-num">{c.esc(m.get("value_text"))}</b></div>'
                                for m in metrics.get("metrics", []))
                st.html(f'<div class="moa-card-title">{c.esc(copy.O5_TITLE)}</div>'
                        f'<div class="moa-metrics">{tiles}</div>')

        # --- 3 O-1 사건 목록 — 행을 누르면 O-2 사건 상세 --------------------------
        with st.container(key="moa_inc_card"):
            head = "".join(f"<span>{c.esc(col)}</span>" for col in copy.O1_COLUMNS)
            st.html(f'<div class="moa-card-title">{c.esc(copy.O1_TITLE)}</div>'
                    f'<div class="moa-tr moa-th moa-inc-grid">{head}</div>')
            rows = incidents.get("incidents") or []
            if not rows:
                st.html(f'<div class="moa-step-note" style="padding:12px 4px">{c.esc(copy.O1_EMPTY)}</div>')
            opened_inc = st.session_state.get(state.OPS_INCIDENT_OPEN)
            for r in rows:
                iid = r["incident_id"]
                with st.container(key=f"card_inc_{iid}"):
                    st.html(f'<div class="moa-tr moa-inc-grid"><span class="moa-td-id">{c.esc(iid)}</span>'
                            f'<span class="moa-td-code">{c.esc(r.get("fault_code"))}</span>'
                            f'<span>{c.pill(r.get("state_text", ""), _INCIDENT_TONE.get(r.get("state"), "gray"))}</span>'
                            f'<span class="moa-td moa-num">{c.esc(r.get("detected_at_text"))}</span>'
                            f'<span class="moa-td moa-num">{c.esc(r.get("resolved_at_text"))}</span></div>')
                    if st.button(f"{iid} 자세히 보기", key=f"hit_inc_{iid}"):
                        st.session_state[state.OPS_INCIDENT_OPEN] = None if opened_inc == iid else iid
                        st.rerun()
                if opened_inc == iid:
                    detail = api.get(lambda: api_client.ops_incident(iid, ops_token=ops_token),
                                     fallback=mock.OPS_INCIDENT_DETAIL.get(iid), label="ops_incident")
                    st.html(_incident_detail(detail) if detail else
                            '<div class="moa-step-note">사건 상세는 서버가 응답한 뒤에 보여 드립니다</div>')

        # --- 7 O-6 주문 처리 기록 — 조회 전용이라 주 버튼이 없다 ------------------
        with st.container(key="moa_ord_card"):
            with st.container(key="moa_ord_head", horizontal=True, horizontal_alignment="distribute",
                              vertical_alignment="center"):
                st.html(f'<div class="moa-card-title">{c.esc(copy.O6_TITLE)}</div>')
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

        # --- 5 O-5 장애 주입 (실습 전용) ----------------------------------------
        with st.container(key="moa_fault", horizontal=True, horizontal_alignment="distribute",
                          vertical_alignment="center"):
            st.html(f'<div class="moa-fault-title">{c.esc(copy.O5_FAULT_TITLE)}'
                    f'<span>{c.esc(copy.O5_FAULT_NOTE)}</span></div>')
            with st.container(horizontal=True, width="content", gap="small"):
                for code in copy.O5_FAULT_CODES:
                    if st.button(code, key=f"fault_{code}"):
                        st.session_state["_fault_ask"] = code
                        st.rerun()
                if st.button(copy.O5_FAULT_CLEAR, key="fault_clear"):
                    st.session_state["_fault_ask"] = "clear"
                    st.rerun()

        asking = st.session_state.get("_fault_ask")
        if asking:
            # 누르면 확인을 거쳐 주입 시각을 기록한다 (P-06 SCR-006 요소 5)
            label = copy.O5_FAULT_CLEAR if asking == "clear" else asking
            with st.container(key="moa_fault_ask", horizontal=True, vertical_alignment="center"):
                ask = ("주입한 장애를 모두 해제할까요?" if asking == "clear"
                       else f"{asking} 장애를 주입할까요?")
                st.html(f'<div class="moa-sugg-ask">{c.esc(ask)} 실습 환경에서만 쓰는 기능이에요</div>')
                if st.button("실행", key="fault_yes", type="primary"):
                    data = api.get(
                        lambda: api_client.ops_fault(None if asking == "clear" else asking,
                                                     "clear" if asking == "clear" else "inject",
                                                     ops_token=ops_token),
                        fallback={"user_message": f"{label} 처리했어요"}, label="ops_fault")
                    st.session_state["_fault_ask"] = None
                    st.toast(data.get("user_message", ""))
                    st.rerun()
                if st.button("그만두기", key="fault_no"):
                    st.session_state["_fault_ask"] = None
                    st.rerun()

    layout._preview_notice()


dashboard()
