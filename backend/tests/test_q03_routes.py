# Q-03 — 경로별 정상 처리 · 다중 이벤트 (Q-01 TC-020 · TC-022 · TC-023 · TC-025)
#
# P-03 경로 5종 중 add · cancel · confirm 을 그래프 전체(N-01 → N-10)로 태운다. DB 는 가짜다(q03_fakes).
# update 는 기존 test_graph 가 노드 단위로 덮는다 — 여기서는 cancel 의 변경 이력과 다중 이벤트만 더한다.
import pytest

from app import graph
from app.services import changes
from tests import q03_fakes as F


@pytest.fixture
def store(monkeypatch):
    return F.Store()


def run(monkeypatch, store, lines):
    F.no_interpreter(monkeypatch)
    F.install(monkeypatch, store, messages=F.chat(lines))
    return graph.run("snapshot", dict(F.SESSION), trace_id="tr_Q03")


# --- 해석 결과를 고정해 태우는 도우미 — 경로 분류는 해석 서비스가 한다(규칙만으로는 confirm 이 없다) ----
def _item(menu_text, *, size_text=None, quantity=1):
    return {"menu_text": menu_text, "temperature_text": None, "size_text": size_text,
            "quantity": quantity, "option_texts": [], "custom_request": None}


ITEM_AA = _item("아아", size_text="톨")
ITEM_LATTE = _item("라떼")


def _run_with_events(monkeypatch, store, lines, events):
    """events = [(message_id, event_type, items)] — 해석 서비스가 그대로 돌려준다."""
    from app import config, interpreter_client
    from app.contracts import OrderEvents
    from app.graph import nodes

    monkeypatch.setattr(config, "ORDER_INTERPRETER_PRIMARY_URL", "http://primary")
    monkeypatch.setattr(nodes, "_pick_service", lambda: "primary")

    def fake(task, messages, context, **k):
        base = {"evidence_message_ids": [], "target_message_id": None, "reason": "r",
                "person": None, "person_unclear": False, "target_unclear": False,
                "is_reference": False}
        return OrderEvents.model_validate({"events": [
            {**base, "message_id": mid, "evidence_message_ids": [mid],
             "event_type": etype, "items": items} for mid, etype, items in events]})

    monkeypatch.setattr(interpreter_client, "interpret", fake)
    F.install(monkeypatch, store, messages=F.chat(lines))
    return graph.run("snapshot", dict(F.SESSION), trace_id="tr_Q03")


# --- TC-020 경로 add --------------------------------------------------------------------
def test_add_creates_one_confirmed_item_through_the_whole_graph(monkeypatch, store):
    out = run(monkeypatch, store, ["[박서연] 아아 톨 한 잔이요."])

    assert [e["route"] for e in out["targets"]["ordered"]] == ["add"]
    assert len(store.live()) == 1
    item = store.live()[0]
    assert (item["person"], item["menu_id"], item["quantity"]) == ("박서연", "sb_004", 1)
    assert item["options"]["size"] == "tall"
    assert item["validation_status"] == "passed"          # 확인 필요가 아니다
    assert store.checkpoints == ["chat_read", "menu_matched", "validated", "settled"]
    assert store.status == "awaiting_confirmation"        # 확인 필요 0건 → 확인 대기
    assert store.settlement                               # N-09 가 정산까지 끝냈다
    assert out["guard"]["demoted"] == 0                   # N-10 강등 0건


def test_add_without_size_takes_the_store_default(monkeypatch, store):
    run(monkeypatch, store, ["[김민수] 아이스 아메리카노 2잔이요"])

    item = store.live()[0]
    assert item["quantity"] == 2
    assert item["options"]["size"] == "tall"              # 스타벅스 기본 사이즈


# --- TC-022 경로 cancel — 물리 삭제 없음 · 변경 이력 ---------------------------------------
def test_cancel_narrowed_by_option_removes_only_that_cup_and_leaves_history(monkeypatch, store):
    recorded = []
    monkeypatch.setattr(changes, "record",
                        lambda cur, session_id, **k: recorded.append(k))

    out = run(monkeypatch, store, ["[김민수] 아아 톨 2잔, 하나는 샷 추가요.",
                                   "[김민수] 샷 추가한 한 잔 취소요."])

    assert [e["route"] for e in out["targets"]["ordered"]] == ["add", "cancel"]
    removed = [r for r in store.items if r["removed"]]
    kept = store.live()
    assert len(removed) == 1 and removed[0]["options"].get("shot") == "extra"
    assert len(kept) == 1 and kept[0]["options"].get("shot") != "extra"
    assert store.items == sorted(store.items, key=lambda r: r["item_id"])   # 행은 남는다(물리 삭제 없음)
    assert any(k.get("method") == "chat_cancel" for k in recorded)          # 변경 이력 1행


# --- TC-023 경로 confirm — 항목 변화 0 · 툴 0 ---------------------------------------------
def test_confirm_changes_nothing_and_calls_no_tool(monkeypatch, store):
    tools = []
    from app.graph import agents
    monkeypatch.setattr(agents, "menu_agent", lambda *a, **k: tools.append("menu") or (None, 0))
    monkeypatch.setattr(agents, "review_agent", lambda *a, **k: tools.append("review") or (None, 0))

    out = _run_with_events(monkeypatch, store,
                           ["[박서연] 아아 톨 한 잔이요.", "[박서연] 네 그대로 주세요."],
                           [("m1", "add", [ITEM_AA]), ("m2", "confirm", [])])

    routes = [e["route"] for e in out["targets"]["ordered"]]
    assert routes == ["add", "confirm"]
    assert len(store.live()) == 1                        # confirm 이 항목을 더하지 않는다
    assert store.live()[0]["menu_id"] == "sb_004"
    assert tools == []                                    # 툴 호출 0건 (D-10 5절)


# --- TC-025 한 메시지에 이벤트 2개 ---------------------------------------------------------
def test_one_message_can_carry_cancel_and_add(monkeypatch, store):
    out = _run_with_events(monkeypatch, store,
                           ["[김민수] 아아 톨 하나요.", "[김민수] 아아 취소하고 라떼로 하나 주세요."],
                           [("m1", "add", [ITEM_AA]), ("m2", "cancel", []), ("m2", "add", [ITEM_LATTE])])

    routes = [e["route"] for e in out["targets"]["ordered"]]
    assert routes == ["add", "cancel", "add"]             # 한 메시지에서 이벤트 2개
    assert len([r for r in store.items if r["removed"]]) == 1
    assert [r["menu_id"] for r in store.live()] == ["sb_012"]
