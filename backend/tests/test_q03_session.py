# Q-03 — 세션 생성 · 재입력 · 체크포인트 (Q-01 TC-004③ · TC-005 · TC-010 · TC-011)
#
# Q-01 테스트시나리오의 "신규" 칸만 만든다. 기존 테스트를 다시 쓰지 않는다.
# DB 없이 돈다 — 체크포인트 순서는 N-09 가 부르는 순서를 잡아서 본다(실제 DB 흐름은 test_live_flow).
import contextlib

import pytest
from fastapi.testclient import TestClient

from app import config, db, envelope, logging_setup
from app.api import deps
from app.graph import nodes
from app.main import app
from app.services import brand_flow, sessions, settlement, suggestions

client = TestClient(app, raise_server_exceptions=False)
TOKEN = {"X-Session-Token": "tok_q03"}
SESSION = {"session_id": "ORD-0001", "brand_id": "starbucks", "menu_version": "mv_20261029",
           "status": "running", "version": 1, "checkpoint": "created", "token_hash": "h",
           "is_verification": False, "brand_source": "request_line", "brand_evidence_text": None,
           "trace_id": "tr_Q03"}


def error_of(res):
    return res.json()["error"]


# --- TC-004 ③ 메시지 501건 -------------------------------------------------------------
# 기대 코드는 D-02 API스펙 6절(`CONVERSATION_TOO_LARGE` — 1MB · 500건 초과)이 정본이다.
# Q-01 TC-004 칸의 "MAX_MESSAGES" 는 문서 표기이고 API 코드가 아니다.
def test_over_max_messages_is_rejected_before_any_analysis(monkeypatch):
    called = []
    monkeypatch.setattr(brand_flow, "start", lambda *a, **k: called.append(1))
    raw = "\n".join(f"[김민수] 아아 톨 {i}잔" for i in range(config.MAX_MESSAGES + 1))

    res = client.post("/api/sessions", json={"raw_text": raw}, headers=TOKEN)

    assert res.status_code == 400
    assert error_of(res)["code"] == "CONVERSATION_TOO_LARGE"
    assert called == []                      # 분석에 들어가지 않는다 — LLM 호출 0건


def test_input_guard_also_rejects_over_max_messages(monkeypatch):
    """API 가 먼저 막더라도 그래프 N-01 이 같은 상한을 갖고 있어야 한다 (단일 진입 · G-A4)."""
    monkeypatch.setattr(db, "fetch_one", lambda *a, **k: {"snapshot_id": "ORD-0001-s1"})
    monkeypatch.setattr(db, "fetch_all", lambda *a, **k: [
        {"message_id": f"m{i}", "seq": i, "sender": "김민수", "text": "아아"}
        for i in range(1, config.MAX_MESSAGES + 2)])

    with pytest.raises(nodes.GraphRejected):
        nodes.input_guard_node({"session": SESSION, "source": "snapshot"})


# --- TC-005 같은 대화 재입력 (FR-011) ---------------------------------------------------
def test_same_conversation_returns_the_existing_session_without_reanalysis(monkeypatch):
    seen = {}
    monkeypatch.setattr(sessions, "find_by_content",
                        lambda content_hash, token_hash: seen.setdefault("hashes", (content_hash, token_hash)) and None
                        or SESSION)
    ran = []
    monkeypatch.setattr(deps, "run_pipeline_background", lambda *a, **k: ran.append(1))
    monkeypatch.setattr(sessions, "run_pipeline", lambda *a, **k: ran.append(1))
    monkeypatch.setattr(sessions, "create", lambda *a, **k: pytest.fail("새 세션을 만들면 안 된다"))

    res = client.post("/api/sessions", json={"raw_text": "[김민수] 아아 톨 한 잔이요.\n스타벅스로 갈 예정이야"},
                      headers=TOKEN)

    body = res.json()["data"]
    assert res.status_code == 200
    assert body["reused"] is True
    assert body["session_id"] == "ORD-0001"
    assert "session_token" not in body             # 토큰은 다시 주지 않는다
    assert ran == []                               # 새 분석 0회 → LLM 호출 0회
    assert seen["hashes"][1]                       # 그 담당자 토큰으로만 찾는다


def test_reuse_needs_the_owner_token(monkeypatch):
    """토큰 없는 요청에는 기존 세션을 돌려주지 않는다 — 화면을 열 방법이 없기 때문."""
    monkeypatch.setattr(sessions, "find_by_content", lambda *a, **k: pytest.fail("찾지 않는다"))
    monkeypatch.setattr(brand_flow.brand_service, "resolve", lambda raw: {"brand_id": "starbucks"})
    made = []
    monkeypatch.setattr(sessions, "create", lambda *a, **k: made.append(1) or {"session_id": "ORD-0002"})

    brand_flow.start("[김민수] 아아", source="paste", trace_id="tr_T", owner_token=None)

    assert made == [1]


# --- TC-010 체크포인트 5값 순서 ---------------------------------------------------------
@pytest.fixture
def captured_checkpoints(monkeypatch):
    """N-09 가 저장하는 체크포인트를 순서대로 잡는다. DB 는 쓰지 않는다."""
    saved = []

    @contextlib.contextmanager
    def fake_transaction(role="app"):
        yield object()

    monkeypatch.setattr(db, "transaction", fake_transaction)
    monkeypatch.setattr(db, "fetch_one", lambda *a, **k: {"snapshot_id": "ORD-0001-s1"})
    monkeypatch.setattr(sessions, "set_checkpoint",
                        lambda cur, session_id, checkpoint: saved.append(checkpoint))
    monkeypatch.setattr(sessions, "_insert_events", lambda *a, **k: None)
    monkeypatch.setattr(sessions, "_insert_items", lambda *a, **k: None)
    monkeypatch.setattr(sessions, "_build_questions", lambda *a, **k: None)
    monkeypatch.setattr(sessions, "items", lambda *a, **k: [])
    monkeypatch.setattr(settlement, "compute_lines", lambda live: [])
    monkeypatch.setattr(settlement, "save_lines", lambda *a, **k: None)
    return saved


def test_checkpoints_are_saved_in_the_five_value_order(captured_checkpoints):
    """chat_read 는 N-04(Intake 결과 저장), 나머지 셋은 N-09 — 합치면 5값 순서다 (PRD 5.2 Handoff)."""
    nodes.route_node({"session": SESSION, "source": "snapshot", "events": []})
    nodes.apply_node({"session": SESSION, "source": "snapshot", "service": None,
                      "targets": {"ordered": []}, "rows": [], "cancels": [], "messages": []})

    assert captured_checkpoints == ["chat_read", "menu_matched", "validated", "settled"]
    assert sessions.CHECKPOINTS == ("created", "chat_read", "menu_matched", "validated", "settled")


def test_intake_result_is_saved_before_rule_steps(captured_checkpoints, monkeypatch):
    """N-04 가 이벤트를 저장한 뒤에 chat_read — 저장본 없이 chat_read 가 남지 않는다."""
    order = []
    monkeypatch.setattr(sessions, "_insert_events", lambda *a, **k: order.append("events"))
    monkeypatch.setattr(sessions, "set_checkpoint", lambda cur, sid, cp: order.append(cp))
    nodes.route_node({"session": SESSION, "source": "snapshot",
                      "events": [{"message_id": "m1", "event_type": "add", "_order": [1, 0]}]})
    assert order == ["events", "chat_read"]


def test_resume_does_not_save_intake_again(captured_checkpoints, monkeypatch):
    saved = []
    monkeypatch.setattr(sessions, "_insert_events", lambda *a, **k: saved.append(1))
    nodes.route_node({"session": SESSION, "source": "snapshot", "resumed": True, "events": []})
    assert saved == [] and captured_checkpoints == []


def test_chat_and_reply_do_not_save_intake_events(captured_checkpoints, monkeypatch):
    saved = []
    monkeypatch.setattr(sessions, "_insert_events", lambda *a, **k: saved.append(1))
    for source in ("chat", "reply"):
        nodes.route_node({"session": SESSION, "source": source, "events": []})
    assert saved == []


# --- 재개 — Intake 저장본으로 N-03 을 건너뛴다 (PRD 5.2 · D-12 10.4) ------------------------
PAYLOAD = {"message_id": "m1", "event_type": "add", "_order": [1, 0], "person": "김민수",
           "evidence_message_ids": ["m1"], "is_reference": False, "items": []}


@pytest.mark.parametrize("checkpoint,rows,expect", [
    ("chat_read", [{"payload": PAYLOAD}], True),                 # LLM 뒤에서 죽음 → 저장본으로
    ("created", [{"payload": PAYLOAD}], False),                  # Intake 전에 죽음 → 처음부터
    ("settled", [{"payload": PAYLOAD}], False),                  # 끝난 분석 → 재개 아님
    ("chat_read", [], False),                                    # 저장본 없음
    ("chat_read", [{"payload": PAYLOAD}, {"payload": None}], False),   # 예전 행 섞임
])
def test_resume_only_from_chat_read_with_full_payload(monkeypatch, checkpoint, rows, expect):
    """판정기 양방향 — 재개해야 하는 경우 1과 하면 안 되는 경우 4 (G-A0)."""
    monkeypatch.setattr(db, "fetch_all", lambda *a, **k: rows)
    monkeypatch.setattr(nodes, "_interpreter_ready", lambda: False)
    out = nodes.batch_node({"session": {**SESSION, "checkpoint": checkpoint}, "source": "snapshot",
                            "messages": [{"message_id": "m1", "seq": 1, "sender": "김민수", "text": "아아"}]})
    assert bool(out.get("resumed")) is expect
    if expect:
        assert out["batches"] == [] and out["events"] == [PAYLOAD]
        assert nodes.dispatch_batches_edge(out) == "route"
    else:
        assert out["batches"]


def test_resumed_run_skips_intake_llm(monkeypatch):
    """그래프 전체 — 저장본이 있으면 해석 서비스를 한 번도 부르지 않는다."""
    from app import interpreter_client
    from app.graph import build
    from tests import q03_fakes as F

    store = F.install(monkeypatch, F.Store(), messages=F.chat(["[김민수] 아아 톨 한 잔이요"]))
    payload = {**PAYLOAD, "_raw_text": "아아 톨 한 잔이요", "seq": 1,
               "items": [{"person": "김민수", "menu_text": "아아 톨 한 잔이요", "match_text": "아아 톨",
                          "options": {"size": "tall"}, "option_words": {}, "ambiguous_options": {},
                          "custom_request": None, "quantity": 1, "traits": [], "reference": False,
                          "temperature_base": None, "temperature_hint": None}]}
    original = db.fetch_all
    monkeypatch.setattr(db, "fetch_all", lambda sql, params=None, **k:
                        [{"payload": payload}] if "payload FROM app.order_event" in sql else original(sql, params, **k))
    called = []
    monkeypatch.setattr(interpreter_client, "interpret", lambda *a, **k: called.append(1))
    monkeypatch.setattr(nodes, "_pick_service", lambda: "primary")
    monkeypatch.setattr(config, "ORDER_INTERPRETER_PRIMARY_URL", "http://primary")
    monkeypatch.setattr(nodes, "_needs_menu_agent", lambda row, state: False)
    monkeypatch.setattr(nodes, "_review_unclear", lambda state, rows: 0)

    build.run("snapshot", {**F.SESSION, "checkpoint": "chat_read"}, trace_id="tr_resume")
    assert called == []                                  # N-03 LLM 0회
    assert store.events == []                            # 이벤트를 다시 쓰지 않는다
    assert store.checkpoints == ["menu_matched", "validated", "settled"]
    assert len(store.live()) == 1


def test_checkpoint_name_outside_the_five_is_refused():
    with pytest.raises(ValueError):
        sessions.set_checkpoint(None, "ORD-0001", "almost_done")


# --- TC-011 체크포인트 저장 실패 → failed · 부분 결과 미노출 ------------------------------
def test_checkpoint_update_hitting_no_row_is_fatal(monkeypatch):
    """UPDATE 0행은 삼키지 않는다 (FR-013). 이력과 다르게 취급하는 지점이다."""
    events = []
    monkeypatch.setattr(logging_setup, "log", lambda event, **f: events.append(event))

    class Cur:
        rowcount = 0

        def execute(self, *a, **k):
            return None

    with pytest.raises(RuntimeError):
        sessions.set_checkpoint(Cur(), "ORD-0001", "settled")
    assert "checkpoint_save_failed" in events


def test_failed_analysis_marks_the_session_and_logs_where_it_stopped(monkeypatch):
    events, writes = [], []
    monkeypatch.setattr(logging_setup, "log", lambda event, **f: events.append((event, f)))
    monkeypatch.setattr(sessions, "run_pipeline",
                        lambda session_id, *, trace_id: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(db, "fetch_one", lambda *a, **k: {"checkpoint": "menu_matched"})
    monkeypatch.setattr(db, "execute", lambda sql, params=None, **k: writes.append((sql, params)))

    deps.run_pipeline_background("ORD-0001", "tr_Q03")

    logged = dict((e, f) for e, f in events)
    assert "checkpoint_save_failed" in logged
    assert logged["checkpoint_save_failed"]["step"] == "menu_matched"     # 멈춘 자리
    assert "status = 'failed'" in writes[0][0]
    assert "status IN ('running','recovering')" in writes[0][0]           # 완료 세션은 건드리지 않는다
    assert envelope.current_trace.get() is None


def test_failed_session_progress_shows_no_partial_result(monkeypatch):
    """failed 는 200 + status 로 간다 (D-02 2.3). 진행 응답에 부분 결과가 실리지 않는다."""
    from app.services import projection

    view = projection.progress_view({**SESSION, "status": "failed", "checkpoint": "menu_matched"},
                                    review_count=2)

    assert view["status"] == "failed"
    states = [s["state"] for s in view["steps"]]
    assert states[:2] == ["done", "done"]          # 끝난 단계는 유지
    assert states[2] == "failed"                   # 멈춘 자리만 failed
    assert view["collapsed_text"] is None          # "정리했어요" 를 띄우지 않는다
    assert view["review_count"] is None            # 확인 필요 건수도 내보내지 않는다
    assert view["status_line"]["tone"] == "danger"
    assert "그대로 있어요" in view["status_line"]["text"]
    assert not set(view) & {"items", "order_sheet", "settlement"}
