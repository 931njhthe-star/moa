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


def _normalize_detail(detail: dict) -> dict:
    """서버 응답 모양을 D-02 API-043 모양으로 맞춘다 (2026-11-05).

    서버(services/incidents.incident_detail)는 `timeline` · `verification` 을 **목록**으로, `attempts` 를
    최상위로 돌려준다. 화면은 API-043 대로 사전을 기대해 `.get` 에서 AttributeError 가 났다.
    두 모양을 모두 받는다 — 서버를 바꾸지 않아 다른 호출부에 영향이 없다.
    """
    detail = dict(detail)
    timeline = detail.get("timeline")
    if isinstance(timeline, list):
        keys = {"injected": "injected_at", "detected": "detected_at",
                "recovery_started": "recovery_started_at", "resolved": "resolved_at", "failed": "failed_at"}
        detail["timeline"] = {keys.get(t.get("key"), t.get("key")): t.get("at_text") for t in timeline}
    verification = detail.get("verification")
    if isinstance(verification, list):
        verdicts = {v.get("verdict") for v in verification if v.get("verdict")}
        detail["verification"] = {
            "checks": [{"name": v.get("check_name"), "result": "통과" if v.get("passed") else "미달"}
                       for v in verification],
            "verdict": ("실패" if "failed" in verdicts else "통과") if verification else None}
    recovery = dict(detail.get("recovery") or {})
    if "attempts" not in recovery and isinstance(detail.get("attempts"), list):
        recovery["attempts"] = [{"no": a.get("attempt_no"), "action": a.get("action"),
                                 "wait_ms": a.get("wait_ms"), "result": a.get("result")}
                                for a in detail["attempts"]]
        recovery["tool_calls"] = [{"tool": a.get("tool"), "args": a.get("tool_args"), "result": a.get("result")}
                                  for a in detail["attempts"] if a.get("tool")]
    if "strategy" not in recovery and detail.get("strategy"):
        recovery["strategy"] = detail["strategy"]
    detail["recovery"] = recovery
    if detail.get("elapsed_sec") is None and isinstance(detail.get("elapsed_ms"), (int, float)):
        detail["elapsed_sec"] = round(detail["elapsed_ms"] / 1000, 1)
    return detail


def _plan_text(plan) -> str:
    """복구 계획 한 줄 — 단계 목록이 있으면 순서대로, 없으면 '-'."""
    if not isinstance(plan, dict):
        return "-"
    steps = plan.get("steps") or []
    names = [s.get("strategy") or s.get("action") or str(s) if isinstance(s, dict) else str(s) for s in steps]
    return " → ".join(names) if names else "-"


def _incident_detail(detail: dict) -> str:
    """O-2 사건 상세 — 타임라인 + 항목(P-06 SCR-006 "O-2 사건 상세").

    주입 -> 탐지 -> 복구 시작 -> 정상화(또는 최종 실패) 시각과 진단 근거 · 선택 전략 ·
    시도 번호 · 대기시간 · 검증 결과를 항목별로 보여준다. **원시 JSON을 그대로 쏟지 않는다.**
    장애 코드 · 지표 이름은 운영자 화면이라 그대로 쓴다(D-02 3.1 — 담당자 화면에는 0건).
    """
    detail = _normalize_detail(detail)
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
        # Diagnosis 의 복구 계획 (PRD 5.9.3) — 장애 대응 층이 채우기 전에는 "-"
        ("복구 계획", _plan_text(detail.get("recovery_plan"))),
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

        # Keep the legacy one-off injector separate from the guided workflow.
        with st.expander("단발 장애 주입 · 개발용", expanded=False):
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


st.divider()

_FAULT_GUIDE = {
    "F-1": ("해석 API 오류", "해석 API가 서버 오류(5xx)를 반환하는 상황입니다.",
            "오류를 감지하고 반대쪽 해석기로 최대 1회 전환한 뒤 결과를 확인합니다."),
    "F-2": ("해석 API 지연", "해석 응답이 5초를 넘는 상황입니다.",
            "지연을 감지해 반대쪽으로 전환합니다. 전체 처리 상한은 15초입니다."),
    "F-3": ("앱 backend 중단", "A 또는 B 앱 backend가 응답하지 않는 상황입니다.",
            "Gateway에서 제외 → backend 재시작 → 상태와 기능 확인 순서로 진행합니다."),
    "F-4": ("반복 장애와 회로 차단", "해석기 오류가 반복되어 회로 차단기가 열리는 상황입니다.",
            "3회 실패 → 60초 차단 → 단일 probe를 확인합니다. probe 실패는 사람 확인으로 넘깁니다."),
    "F-5": ("잘못된 에이전트 출력", "결과가 정해진 출력 형식이나 계약을 지키지 않는 상황입니다.",
            "최대 2회 다시 생성하고, 계속 실패하면 NEEDS_REVIEW로 넘깁니다."),
    "F-6": ("메뉴 조회 실패와 캐시 폴백", "메뉴 저장소 조회가 실패하는 상황입니다.",
            "같은 브랜드·버전·checksum의 캐시로 처리되는지 확인합니다. 안전한 캐시가 없으면 실패 처리합니다."),
}
_TARGET_LABELS = {
    "order_interpreter_primary": "주문 해석기 기본(primary)",
    "order_interpreter_backup": "주문 해석기 대체(backup)",
    "moa-a-backend-1": "앱 A backend",
    "moa-b-backend-1": "앱 B backend",
    "menu_store": "메뉴 저장소 조회",
}
_MODE_LABELS = {"quick": "빠른 확인 · 선택 장애 1회",
                "custom": "직접 설정 · 선택 장애 1~10회",
                "full": "전체 복구 측정 · 25회 (F-4 제외)"}
_STATUS_LABELS = {
    "queued": "대기 중", "preflight": "환경 확인 중", "running": "실행 중",
    "stop_requested": "중지 처리 중", "cleaning": "장애 정리 중",
    "completed": "실행 종료", "stopped": "중지됨", "failed": "실행 실패",
    "needs_operator_action": "운영자 확인 필요", "invalid": "환경 확인 실패",
    "PASS": "예상대로 통과", "FAIL": "예상과 다름", "NEEDS_REVIEW": "사람 확인 필요",
    "AWAITING_APPROVAL": "승인 대기", "INVALID": "실행 전 조건 미충족",
}
_PHASE_LABELS = {
    "queued": "대기", "preflight": "환경 확인", "fault_injection": "장애 주입",
    "injecting": "장애 주입", "detecting": "장애 감지", "recovering": "자동 복구",
    "verifying": "복구 결과 확인", "cooldown_probe": "차단 후 단일 확인",
    "cleanup": "장애 정리", "stop_requested": "중지·정리",
}


def _report_escape(value):
    return str(value if value not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


def _workflow_report_markdown(run: dict) -> str:
    """저장된 실행 정보를 사람이 읽을 수 있는 Markdown 보고서로 만든다."""
    summary = run.get("summary") or {}
    mode = run.get("mode")
    title = "통합 장애 시험 결과보고서" if mode == "full" else "장애 시험 결과보고서"
    lines = [
        f"# {title}", "",
        f"- 실행 ID: {_report_escape(run.get('run_id'))}",
        f"- 시험 방식: {_report_escape(_MODE_LABELS.get(mode, mode))}",
        f"- 상태: {_report_escape(_STATUS_LABELS.get(run.get('status'), run.get('status')))}",
        f"- 시작: {_report_escape(run.get('started_at'))}",
        f"- 종료: {_report_escape(run.get('finished_at'))}",
        f"- 결과: 통과 {summary.get('pass', 0)} / 실패 {summary.get('fail', 0)} / "
        f"사람 확인 {summary.get('needs_review', 0) + summary.get('awaiting_approval', 0)} / "
        f"전체 {summary.get('total', run.get('total_iterations', 0))}",
        f"- 평균 감지 시간: {summary.get('avg_mttd_ms') if summary.get('avg_mttd_ms') is not None else '—'} ms",
        f"- 평균 복구 시간: {summary.get('avg_mttr_ms') if summary.get('avg_mttr_ms') is not None else '—'} ms",
        "", "> ‘실행 종료’는 장애 시험 절차가 끝났다는 뜻입니다. 복구 성공은 회차별 판정으로 확인합니다.",
        "", "## 회차별 결과", "",
        "| 회차 | 장애 유형 | 대상 | 판정 | 감지(ms) | 복구(ms) | 시도 횟수 | 결과 설명 |",
        "|---:|---|---|---|---:|---:|---:|---|",
    ]
    for item in run.get("iterations") or []:
        detail = item.get("result") or {}
        if not isinstance(detail, dict):
            detail = {}
        fault = item.get("fault_type", detail.get("fault_type", "—"))
        target = item.get("target", detail.get("target", "—"))
        status = item.get("status", detail.get("status", "—"))
        label = _FAULT_GUIDE.get(fault, (fault, "", ""))[0]
        lines.append(
            f"| {item.get('iteration_no', '—')} | {_report_escape(fault)} {_report_escape(label)} "
            f"| {_report_escape(_TARGET_LABELS.get(target, target))} "
            f"| {_report_escape(_STATUS_LABELS.get(status, status))} "
            f"| {item.get('mttd_ms') if item.get('mttd_ms') is not None else '—'} "
            f"| {item.get('mttr_ms') if item.get('mttr_ms') is not None else '—'} "
            f"| {len(detail.get('attempts') or [])} | {_report_escape(detail.get('detail'))} |"
        )
        for step in detail.get("steps") or []:
            lines.extend([
                "", f"### {item.get('iteration_no', '—')}회차 진행 단계", "",
                "| 단계 | 예상 흐름 | 실제 결과 | 걸린 시간(ms) | 판정 |",
                "|---|---|---|---:|---|",
            ])
            break
        for step in detail.get("steps") or []:
            lines.append(
                f"| {_report_escape(step.get('name'))} | {_report_escape(step.get('expected'))} "
                f"| {_report_escape(step.get('actual'))} | {step.get('duration_ms', '—')} "
                f"| {_report_escape(_STATUS_LABELS.get(step.get('status'), step.get('status')))} |"
            )
        attempts = detail.get("attempts") or []
        if attempts:
            lines.extend([
                "", f"### {item.get('iteration_no', '—')}회차 복구 시도", "",
                "| 시도 | 대상/액션 | 결과 | 확인 반복 | 걸린 시간(ms) |",
                "|---:|---|---|---:|---:|",
            ])
            for index, attempt in enumerate(attempts, start=1):
                lines.append(
                    f"| {attempt.get('attempt_no', index)} "
                    f"| {_report_escape(attempt.get('service') or attempt.get('action') or attempt.get('stage'))} "
                    f"| {_report_escape(attempt.get('outcome') or attempt.get('result'))} "
                    f"| {attempt.get('poll_count', attempt.get('request_attempt_no', '—'))} "
                    f"| {attempt.get('duration_ms', '—')} |"
                )
    lines.extend(["", "## 시간순 진행 기록", "", "| 시각 | 진행 내용 |", "|---|---|"])
    for event in run.get("events") or []:
        lines.append(
            f"| {_report_escape(event.get('created_at'))} "
            f"| {_report_escape(event.get('summary'))} · {_report_escape(event.get('details'))} |"
        )
    return "\n".join(lines) + "\n"


def _render_preflight(check: dict) -> None:
    checks = check.get("checks") or []
    failed = [item for item in checks if not item.get("ready")]
    if not failed and checks:
        st.success("시험에 필요한 환경을 모두 확인했습니다. 장애 주입은 아직 시작되지 않았습니다.")
    elif failed:
        st.error(f"시작 전에 해결할 항목이 {len(failed)}개 있습니다. 실패 항목을 확인하세요. 장애는 주입되지 않았습니다.")
    else:
        st.warning("점검 결과를 받지 못했습니다. 서버 연결 상태를 확인하세요.")
    labels = {
        "lab 환경": ("실습 환경", "장애 시험은 lab 환경에서만 실행할 수 있습니다."),
        "DB 연결": ("데이터베이스 연결", "DB 서비스와 연결 설정을 확인하세요."),
        "workflow 스키마": ("시험 기록 테이블", "workflow 스키마가 적용됐는지 확인하세요."),
        "healing worker": ("자동 복구 작업기", "healing 서비스와 최근 heartbeat를 확인하세요."),
        "Docker proxy·allowlist": ("안전한 컨테이너 제어 연결", "socket-proxy 연결과 허용목록을 확인하세요."),
        "backend allowlist": ("A/B backend 허용목록", "두 backend가 복구 작업기 허용목록에 있는지 확인하세요."),
        "Gateway": ("트래픽 Gateway", "Gateway 서비스 상태를 확인하세요."),
        "interpreter primary": ("기본 해석 서비스", "기본 해석 서비스의 /health 상태를 확인하세요."),
        "interpreter backup": ("대체 해석 서비스", "대체 해석 서비스의 /health 상태를 확인하세요."),
        "A backend": ("앱 A backend", "앱 A의 /ready 상태를 확인하세요."),
        "B backend": ("앱 B backend", "앱 B의 /ready 상태를 확인하세요."),
        "A frontend": ("앱 A 화면 서비스", "앱 A frontend 상태를 확인하세요."),
        "B frontend": ("앱 B 화면 서비스", "앱 B frontend 상태를 확인하세요."),
        "F-3 allowlisted target": ("F-3 대상 권한", "선택한 backend가 허용목록에 있는지 확인하세요."),
    }
    for item in checks:
        title, guidance = labels.get(item.get("name"), (item.get("name", "점검 항목"), "세부 상태를 확인하세요."))
        with st.container(border=True):
            st.markdown(f"{'✅' if item.get('ready') else '❌'} **{title}** · "
                        f"{'준비됨' if item.get('ready') else '확인 필요'}")
            st.caption(item.get("detail") if item.get("ready") else guidance)
            if not item.get("ready") and item.get("detail"):
                st.caption(f"세부 정보: {item['detail']}")


st.markdown("## 장애 복구 시험")
st.info("진행 순서: 범위와 장애 선택 → 환경 점검 → 시험 시작 → 아래 시험 기록에서 결과 확인", icon="ℹ️")
with st.expander("사전 점검이란?", expanded=False):
    st.write("장애를 넣기 전에 실습 환경, DB, 시험 기록 테이블, 복구 작업기, Gateway와 앱 연결이 준비됐는지 확인합니다.")
    st.write("점검이 실패하면 장애를 주입하지 않습니다. 실패한 항목과 확인 방법을 아래에 표시합니다.")

ops_token = st.session_state.get(state.OPS_TOKEN)
mode = st.radio("시험 범위", ["quick", "custom", "full"], horizontal=True,
                format_func=lambda value: _MODE_LABELS[value], key="wf_mode")
with st.expander("F-1~F-6 장애 코드 안내", expanded=(mode == "full")):
    for code, (label, description, recovery) in _FAULT_GUIDE.items():
        st.markdown(f"**{code} · {label}** — {description}")
        st.caption(f"예상 복구: {recovery}")
if mode == "full":
    fault_type, target, repetitions = None, None, 1
else:
    fault_type = st.selectbox("시험할 장애 유형", list(_FAULT_GUIDE),
                              format_func=lambda code: f"{code} · {_FAULT_GUIDE[code][0]}", key="wf_fault")
    st.markdown(f"**상황:** {_FAULT_GUIDE[fault_type][1]}  \n**예상 복구:** {_FAULT_GUIDE[fault_type][2]}")
    targets = {
        "F-1": ["order_interpreter_primary", "order_interpreter_backup"],
        "F-2": ["order_interpreter_primary", "order_interpreter_backup"],
        "F-3": ["moa-a-backend-1", "moa-b-backend-1"],
        "F-4": ["order_interpreter_primary", "order_interpreter_backup"],
        "F-5": ["order_interpreter_primary", "order_interpreter_backup"],
        "F-6": ["menu_store"],
    }
    target = st.selectbox("장애를 적용할 대상", targets[fault_type],
                          format_func=lambda value: _TARGET_LABELS.get(value, value), key="wf_target")

if mode == "custom":
    repetitions = st.number_input("반복 횟수", min_value=1, max_value=10, value=1, step=1,
                                  help="같은 장애 시나리오를 몇 번 실행할지 정합니다.", key="wf_repetitions")
elif mode == "quick":
    repetitions = 1

injection_seconds = st.number_input("장애 유지 시간(초)", min_value=1, max_value=120, value=1, step=1,
                                    help="장애를 주입한 뒤 복구 동작을 관찰할 시간입니다. 빠른 확인은 1회, 전체 측정은 25회 실행합니다.",
                                    key="wf_seconds")
selection = (mode, fault_type, target, int(repetitions), int(injection_seconds))

if st.button("점검 결과만 확인", key="wf_preflight"):
    try:
        check = api_client.ops_workflow_preflight(mode=mode, fault_type=fault_type or "F-1",
                                                  target=target, ops_token=ops_token)
        st.session_state["wf_preflight_result"] = check
        st.session_state["wf_preflight_selection"] = selection
    except api_client.ApiError as error:
        st.error(error.user_message or "점검 결과를 가져오지 못했습니다.")

prior_check = st.session_state.get("wf_preflight_result")
if prior_check:
    if st.session_state.get("wf_preflight_selection") == selection:
        with st.expander("최근 점검 결과", expanded=False):
            _render_preflight(prior_check)
    else:
        st.caption("선택을 바꿨으므로 이전 점검 결과는 시작 조건으로 사용하지 않습니다.")

if st.button("환경 확인 후 장애 시험 시작", type="primary", key="wf_start"):
    try:
        check = api_client.ops_workflow_preflight(mode=mode, fault_type=fault_type or "F-1",
                                                  target=target, ops_token=ops_token)
        st.session_state["wf_preflight_result"] = check
        st.session_state["wf_preflight_selection"] = selection
        _render_preflight(check)
        if check.get("ready"):
            import uuid
            run = api_client.ops_workflow_create(
                mode=mode, fault_type=fault_type or "F-1", target=target,
                repetitions=int(repetitions), injection_seconds=int(injection_seconds),
                idempotency_key=str(uuid.uuid4()), ops_token=ops_token)
            if run and run.get("run_id"):
                st.session_state["wf_active_run"] = run["run_id"]
                st.session_state["wf_selected_run"] = run["run_id"]
                st.success(f"시험 기록 {run['run_id']}을 저장하고 실행 대기열에 등록했습니다.")
                st.rerun()
            elif run and run.get("preflight"):
                st.session_state["wf_preflight_result"] = run["preflight"]
                st.error("시작 직전에 환경 상태가 바뀌었습니다. 장애는 주입되지 않았습니다.")
                _render_preflight(run["preflight"])
            else:
                st.error("시험이 시작되지 않았고 기록도 생성되지 않았습니다.")
    except api_client.ApiError as error:
        st.error(error.user_message or "시험을 시작하지 못했습니다.")
        if error.detail:
            with st.expander("기술 세부 정보"):
                st.code(str(error.detail))


@st.fragment(run_every=5)
def workflow_results():
    ops_token = st.session_state.get(state.OPS_TOKEN)
    try:
        recent_response = api_client.ops_workflows(ops_token=ops_token)
    except api_client.ApiError as error:
        st.subheader("시험 기록")
        st.error("기록을 불러오지 못했습니다. 기록이 없는 상태와 서버 연결 실패를 구분해 표시합니다.")
        st.caption(error.user_message or "잠시 후 다시 시도해 주세요.")
        return
    recent = recent_response.get("runs", []) if isinstance(recent_response, dict) else []
    if not recent:
        st.subheader("시험 기록")
        st.caption("아직 저장된 시험 기록이 없습니다. 시험이 끝나면 이곳에서 다시 열 수 있습니다.")
        return

    st.subheader("시험 기록")
    st.caption("서버 데이터베이스에 저장된 최근 실행입니다. 실행을 선택해 진행 과정과 결과를 다시 확인할 수 있습니다.")
    run_by_id = {item["run_id"]: item for item in recent if item.get("run_id")}
    options = list(run_by_id)
    wanted = st.session_state.get("wf_selected_run") or st.session_state.get("wf_active_run")
    default_id = wanted if wanted in options else options[0]
    selected_id = st.selectbox(
        "열어볼 실행 기록", options, index=options.index(default_id),
        format_func=lambda rid: (
            f"{rid} · {_STATUS_LABELS.get(run_by_id[rid].get('status'), run_by_id[rid].get('status'))} · "
            f"{run_by_id[rid].get('created_at', '')}"
        ), key="wf_record_select")
    st.session_state["wf_selected_run"] = selected_id
    try:
        run = api_client.ops_workflow(selected_id, ops_token=ops_token)
    except api_client.ApiError as error:
        st.error("선택한 실행의 상세 결과를 불러오지 못했습니다.")
        st.caption(error.user_message or "잠시 후 다시 시도해 주세요.")
        return

    status, phase = run.get("status"), run.get("phase")
    current, total = int(run.get("current_iteration") or 0), int(run.get("total_iterations") or 0)
    st.markdown(f"**상태:** {_STATUS_LABELS.get(status, status)}　·　"
                f"**현재 단계:** {_PHASE_LABELS.get(phase, phase)}　·　**회차:** {current}/{total}")
    if total:
        st.progress(min(1.0, current / total), text=f"{current} / {total}회차")
    if status in ("queued", "preflight", "running", "stop_requested", "cleaning"):
        events = run.get("events") or []
        st.info(f"현재 진행: {events[-1].get('summary', '시험 준비 중') if events else '시험 준비 중'}")
        if st.button("안전하게 중지", key=f"wf_stop_{selected_id}"):
            try:
                api_client.ops_workflow_stop(selected_id, ops_token=ops_token)
                st.success("중지 요청을 받았습니다. 진행 중인 장애를 정리한 뒤 멈춥니다.")
            except api_client.ApiError as error:
                st.error(error.user_message or "중지 요청을 전달하지 못했습니다.")

    summary = run.get("summary") or {}
    if summary:
        cols = st.columns(4)
        values = [
            ("예상대로 통과", summary.get("pass", 0)),
            ("예상과 다름", summary.get("fail", 0)),
            ("사람 확인", summary.get("needs_review", 0) + summary.get("awaiting_approval", 0)),
            ("전체 회차", summary.get("total", total)),
        ]
        for col, (label, value) in zip(cols, values):
            col.metric(label, value)
        total_done = summary.get("completed_iterations", 0)
        passed = summary.get("pass", 0)
        st.caption(f"예상 흐름 일치율: {passed}/{total_done} 완료 회차" +
                   (f" ({passed / total_done:.0%})" if total_done else " (아직 계산할 회차가 없습니다)"))
        st.caption(
            f"평균 감지 {summary.get('avg_mttd_ms') if summary.get('avg_mttd_ms') is not None else '—'} ms · "
            f"평균 복구 {summary.get('avg_mttr_ms') if summary.get('avg_mttr_ms') is not None else '—'} ms"
        )

    iterations = run.get("iterations") or []
    if iterations:
        st.markdown("**회차별 진행 결과**")
        for item in iterations:
            fault = item.get("fault_type", "—")
            label = _FAULT_GUIDE.get(fault, (fault, "", ""))[0]
            state_label = _STATUS_LABELS.get(item.get("status"), item.get("status", "대기 중"))
            detail = item.get("result") or {}
            if not isinstance(detail, dict):
                detail = {}
            with st.expander(
                f"{item.get('iteration_no', '?')}회차 · {fault} {label} · {state_label}",
                expanded=item.get("status") in ("FAIL", "NEEDS_REVIEW", "AWAITING_APPROVAL"),
            ):
                st.markdown(
                    f"**대상:** {_TARGET_LABELS.get(item.get('target'), item.get('target', '—'))}  \n"
                    f"**결과:** {detail.get('detail', '아직 결과가 기록되지 않았습니다.')}"
                )
                steps = detail.get("steps") or []
                if steps:
                    st.markdown("**예상 흐름과 실제 진행**")
                    st.dataframe(
                        [{"단계": step.get("name"), "예상": step.get("expected"),
                          "실제": step.get("actual"), "걸린 시간": f"{step.get('duration_ms', '—')} ms",
                          "판정": _STATUS_LABELS.get(step.get("status"), step.get("status"))}
                         for step in steps],
                        use_container_width=True, hide_index=True,
                    )
                attempts = detail.get("attempts") or []
                st.markdown(
                    f"**기록된 요청·복구 시도:** {len(attempts)}회 · "
                    f"감지 {item.get('mttd_ms') if item.get('mttd_ms') is not None else '—'} ms · "
                    f"복구 {item.get('mttr_ms') if item.get('mttr_ms') is not None else '—'} ms"
                )
                if attempts:
                    st.dataframe(
                        [{"시도": attempt.get("attempt_no", index + 1),
                          "대상/액션": attempt.get("service") or attempt.get("action") or attempt.get("stage"),
                          "결과": attempt.get("outcome") or attempt.get("result"),
                          "확인 반복": attempt.get("poll_count", attempt.get("request_attempt_no", "—")),
                          "걸린 시간": f"{attempt.get('duration_ms', '—')} ms"}
                         for index, attempt in enumerate(attempts)],
                        use_container_width=True, hide_index=True,
                    )
                events = [event for event in run.get("events") or []
                          if event.get("iteration_no") == item.get("iteration_no")]
                if events:
                    st.markdown("**이 회차의 시간순 진행 기록**")
                    st.dataframe(
                        [{"시각": event.get("created_at"), "진행": event.get("summary"),
                          "세부 기록": str(event.get("details") or "")} for event in events],
                        use_container_width=True, hide_index=True,
                    )

    if run.get("events"):
        with st.expander("전체 시험 진행 기록"):
            st.dataframe(
                [{"시각": event.get("created_at"), "회차": event.get("iteration_no"),
                  "진행": event.get("summary"), "세부 기록": str(event.get("details") or "")}
                 for event in run["events"]],
                use_container_width=True, hide_index=True,
            )

    title = "통합 장애 시험 결과보고서" if run.get("mode") == "full" else "장애 시험 결과보고서"
    file_name = "통합_장애_시험_결과보고서.md" if run.get("mode") == "full" else f"장애_시험_{selected_id}.md"
    st.download_button(title + " 다운로드", _workflow_report_markdown(run),
                       file_name=file_name, mime="text/markdown", key=f"wf_report_{selected_id}")
    try:
        json_data = api_client.ops_workflow_export(selected_id, "json", ops_token=ops_token)
        csv_data = api_client.ops_workflow_export(selected_id, "csv", ops_token=ops_token)
        c1, c2 = st.columns(2)
        c1.download_button("원본 JSON", json_data, file_name=f"{selected_id}.json",
                           mime="application/json", key=f"wf_json_{selected_id}")
        c2.download_button("회차 CSV", csv_data, file_name=f"{selected_id}.csv",
                           mime="text/csv", key=f"wf_csv_{selected_id}")
    except api_client.ApiError as error:
        st.caption(f"원본 내보내기 오류: {error.user_message or '잠시 후 다시 시도해 주세요.'}")


workflow_results()
