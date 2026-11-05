"""PRD v1.9 반영 (2026-11-05) — 처리 계획(5.9.3) · FT-04 대체 모델 재요청 · 운영 비밀번호 기본값 · 스키마 문자열.

장애 대응 층(6역할)은 대상이 아니다. 업무 층 · 스키마 · 설정에서 바뀐 것만 본다.
"""

import importlib
import pathlib

import pytest

from app import config, interpreter_client, logging_setup
from app.graph import nodes
from tests.test_graph import _batch, _contract, interpreter, msgs  # noqa: F401 — fixture 재사용

SQL = pathlib.Path(__file__).resolve().parent.parent / "sql"


# --- 처리 계획 (Planner · N-02) ---------------------------------------------------------------
def test_plan_records_what_batch_node_decided(monkeypatch):
    monkeypatch.setattr(config, "ORDER_INTERPRETER_PRIMARY_URL", "http://primary")
    monkeypatch.setattr(config, "MAX_LLM_CALLS_PER_RUN", 6)                # 2묶음까지 LLM
    monkeypatch.setattr(nodes, "_pick_service", lambda: "primary")
    logged = []
    monkeypatch.setattr(logging_setup, "log", lambda event, **f: logged.append((event, f)))

    out = nodes.batch_node({"messages": msgs(12), "source": "chat", "trace_id": "tr_P"})
    plan = out["plan"]

    assert plan["plan_id"].startswith("pl_")
    assert plan["service"] == "primary" and plan["resumed"] is False
    assert plan["batch_count"] == 3 and plan["llm_batches"] == [1, 2] and plan["rule_batches"] == [3]
    assert plan["done_when"] == ["every_message_has_event", "schema_valid", "checkpoint_chat_read"]
    # 계획은 batch_node 의 결정을 바꾸지 않는다 — 묶음 배정이 계획과 같다
    assert [b["use_llm"] for b in out["batches"]] == [True, True, False]
    # 로그는 route_decision(stage=plan) · source 키 없음 — 분류 결과 로그와 섞이지 않는다
    event, fields = logged[-1]
    assert event == "route_decision" and fields["stage"] == "plan" and "source" not in fields


def test_plan_without_interpreter_is_rules_only(monkeypatch):
    monkeypatch.setattr(config, "ORDER_INTERPRETER_PRIMARY_URL", "")
    monkeypatch.setattr(config, "ORDER_INTERPRETER_BACKUP_URL", "")
    plan = nodes.batch_node({"messages": msgs(3)})["plan"]
    assert plan["service"] is None and plan["llm_batches"] == [] and plan["rule_batches"] == [1]


def test_plan_key_is_in_run_state():
    # State 에 없는 키는 LangGraph 가 조용히 버린다(CLAUDE.md "에러 없이 반쪽")
    from app.graph.state import RunState
    assert "plan" in RunState.__annotations__


# --- FT-04 대체 모델 재요청 1회 ---------------------------------------------------------------
def test_backup_model_gets_one_try_after_regenerate_exhausted(interpreter, monkeypatch):
    monkeypatch.setattr(nodes, "_backup_ready", lambda: True)
    bad = interpreter_client.InterpreterError("AGENT_OUTPUT_INVALID", "x", service="primary")
    interpreter.extend([bad, bad, bad, _contract("m1", event_type="ignore")])
    out = nodes.intake_node(_batch(msgs(1)))
    assert out["llm_calls"] == 4                                           # 1 + 재생성 2 + 대체 1
    assert out["events"][0]["event_type"] == "ignore" and not out.get("degraded")


def test_backup_model_failure_still_falls_back_to_rules(interpreter, monkeypatch):
    monkeypatch.setattr(nodes, "_backup_ready", lambda: True)
    bad = interpreter_client.InterpreterError("AGENT_OUTPUT_INVALID", "x", service="primary")
    interpreter.extend([bad, bad, bad, bad])
    out = nodes.intake_node(_batch(msgs(1)))
    assert out["llm_calls"] == 4
    assert out["degraded"][0]["reason"] == "regenerate_exhausted"
    assert out["events"][0]["event_type"] == "add"                         # 지금처럼 규칙 해석


def test_no_backup_keeps_previous_behaviour(interpreter, monkeypatch):
    monkeypatch.setattr(nodes, "_backup_ready", lambda: False)
    bad = interpreter_client.InterpreterError("AGENT_OUTPUT_INVALID", "x", service="primary")
    interpreter.extend([bad, bad, bad])
    out = nodes.intake_node(_batch(msgs(1)))
    assert out["llm_calls"] == 3


def test_backup_ready_needs_address(monkeypatch):
    monkeypatch.setattr(config, "ORDER_INTERPRETER_BACKUP_URL", "")
    assert nodes._backup_ready() is False


# --- 운영 대시보드 비밀번호 기본값 (R-17) -------------------------------------------------------
@pytest.mark.parametrize("env, value, expected, is_default", [
    ("lab", "", "moa-ops", True),
    ("lab", "long-enough-pw", "long-enough-pw", False),
    ("prod", "", "", False),                                               # 실습 밖에서는 로그인 막힘
    ("prod", "long-enough-pw", "long-enough-pw", False),
])
def test_ops_password_default_only_in_lab(monkeypatch, env, value, expected, is_default):
    monkeypatch.setenv("ENVIRONMENT", env)
    monkeypatch.setenv("OPS_DASHBOARD_PASSWORD", value)
    try:
        reloaded = importlib.reload(config)
        assert reloaded.OPS_DASHBOARD_PASSWORD == expected
        assert reloaded.OPS_PASSWORD_IS_DEFAULT is is_default
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# --- 스키마 문자열 (DB 없이 파일로 확인) -------------------------------------------------------
def test_healing_schema_has_v19_codes_and_metrics():
    text = (SQL / "03_schema_healing.sql").read_text(encoding="utf-8")
    for code in ("AGENT_EXCEPTION", "PROMPT_INJECTION"):
        assert text.count(code) >= 2                                       # CREATE + 기존 DB 용 ALTER
    for key in ("timeout_count", "agent_error_count", "restart_count", "db_connection_error",
                "slow_query_count", "schema_error_rate", "validation_fail_rate", "injection_detect_count"):
        assert text.count(f"'{key}'") >= 2
    assert "ADD COLUMN IF NOT EXISTS recovery_plan JSONB" in text


def test_metrics_view_mttr_follows_sc3_and_appends_new_column_last():
    text = (SQL / "04_views.sql").read_text(encoding="utf-8")
    view = text[text.index("CREATE OR REPLACE VIEW healing.v_metrics"):]
    view = view[:view.index(";")]
    assert "COALESCE(i.injected_at, f.injected_at, i.detected_at)" in view
    # CREATE OR REPLACE VIEW 는 기존 칸 순서를 바꿀 수 없다 — 새 칸은 맨 끝
    select_part = view[:view.index("FROM healing.incident")]
    assert select_part.rstrip().endswith("AS mttr_excl_pause_sec")


def test_brand_seed_has_gongcha():
    text = (SQL / "10_seed_brand.sql").read_text(encoding="utf-8")
    assert "('공차'," in text
