# QA H-33 재지적(2026-11-09) — DB 오류 처리 경로의 예외 전문 노출
#
# 지적 2곳: main.py 의 DbUnavailable 처리기 · psycopg.OperationalError 처리기가 str(exc) 를 로그와
# 응답 detail 에 그대로 실었다. 같은 방식의 경로(db.connect · db.health · 미들웨어 · healing 워커)도 함께 본다.
#
# 측정 도구 자기 검증(G-A0): 민감 문자열이 **있던 자리**를 직접 만들어 넣고, (a) 그 문자열이 사라졌는지와
# (b) 추적 칸(error_code · exc_type · trace_id)이 **남아 있는지**를 함께 본다. 한쪽만 보면
# "아무것도 안 남기는" 구현도 통과한다.
import json
import logging

import psycopg
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app import db, logging_setup
from app.main import app

SECRET_URL = "postgresql://app_rw:S3cretPw!@10.0.3.17:5432/moa"
SECRET_PG = ('connection to server at "db" (172.18.0.2), port 5432 failed: '
             'FATAL:  password authentication failed for user "app_rw" password=S3cretPw!')
LEAKS = ("S3cretPw", "10.0.3.17", "172.18.0.2", "app_rw", "5432/moa")   # 스킴(postgresql://)은 비밀이 아니다

router = APIRouter()


@router.get("/__h33/db_unavailable")
def _raise_db_unavailable():
    try:
        raise psycopg.OperationalError(SECRET_PG)
    except psycopg.OperationalError as exc:
        raise db.DbUnavailable(SECRET_URL) from exc     # 누가 실수로 전문을 담아도 새지 않아야 한다


@router.get("/__h33/operational")
def _raise_operational():
    raise psycopg.OperationalError(SECRET_PG)


@router.get("/__h33/unhandled")
def _raise_unhandled():
    raise RuntimeError(SECRET_URL)


app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def logged(monkeypatch):
    lines = []
    real = logging_setup.log
    monkeypatch.setattr(logging_setup, "log", lambda event, **f: (lines.append((event, f)), real(event, **f)))
    from app.services import history, metrics

    monkeypatch.setattr(metrics, "record", lambda *a, **k: None)
    monkeypatch.setattr(history, "save_request", lambda **k: None)
    return lines


def _no_leak(text: str):
    for s in LEAKS:
        assert s not in text, f"민감 문자열 노출: {s!r} in {text[:200]!r}"


@pytest.mark.parametrize("path,where", [("/__h33/db_unavailable", "on_db_unavailable"),
                                        ("/__h33/operational", "on_db_operational")])
def test_db_error_response_and_log_hide_internals_but_keep_tracing(logged, path, where):
    res = client.get(path)
    body = res.json()
    assert res.status_code == 200
    err = body["error"]
    assert err["code"] == "DB_UNAVAILABLE" and err["retryable"] is True
    assert "detail" not in err                                    # 내부 정보는 응답에 싣지 않는다
    assert err["user_message"]                                    # 일반화된 문구는 있다
    _no_leak(res.text)

    (event, fields), = [x for x in logged if x[0] == "db_unavailable"]
    _no_leak(json.dumps(fields, ensure_ascii=False))
    # (b) 추적 칸은 남는다
    assert fields["error_code"] == "DB_UNAVAILABLE"
    assert fields["exc_type"] in ("DbUnavailable", "OperationalError")
    assert fields["trace_id"] == body["meta"]["trace_id"] == res.headers["X-Trace-Id"]
    assert fields["where"] == where and fields["path"] == path


def test_unhandled_exception_request_log_keeps_type_only(logged):
    res = client.get("/__h33/unhandled")
    assert res.status_code == 500
    _no_leak(res.text)
    (_, fields), = [x for x in logged if x[0] == "request"]
    assert fields["error"] == "RuntimeError"
    assert fields["trace_id"]


def test_connect_failure_wraps_without_psycopg_text(monkeypatch):
    class Boom:
        def connection(self):
            raise psycopg.OperationalError(SECRET_PG)

    monkeypatch.setattr(db, "_pool", lambda role: Boom())
    with pytest.raises(db.DbUnavailable) as caught:
        with db.connect():
            pass
    _no_leak(str(caught.value))
    assert "OperationalError" in str(caught.value)


def test_health_text_hides_internals(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "db_configured", lambda: True)

    def down(*a, **k):
        raise psycopg.errors.UndefinedTable(SECRET_PG)

    monkeypatch.setattr(db, "fetch_one", down)
    state = db.health()
    assert state["state"] == "error"
    _no_leak(state["text"])


def test_redact_masks_connection_info_and_keeps_plain_text():
    # (a) 민감 정보는 가린다
    _no_leak(db.redact(SECRET_URL))
    _no_leak(db.redact(SECRET_PG))
    _no_leak(db.redact("host=10.0.3.17 user=app_rw password='S3cretPw!' dbname=moa"))
    # (b) 코드가 정한 고정 문구는 그대로 둔다 — 다 지워 버리는 마스킹은 추적을 망친다
    assert db.redact("연결 대기 초과 (2초)") == "연결 대기 초과 (2초)"
    assert db.redact("DATABASE_URL 미설정") == "DATABASE_URL 미설정"


def test_healing_worker_db_failure_logs_no_traceback(caplog):
    import healing.__main__ as worker

    caplog.set_level(logging.ERROR, logger="moa.healing")
    try:
        raise psycopg.OperationalError(SECRET_PG)
    except psycopg.OperationalError:
        worker._log_failure("worker database operation failed")
    record, = caplog.records
    text = record.getMessage() + (caplog.text or "")
    _no_leak(text)
    assert record.exc_info is None                                  # traceback 에 전문이 실린다
    assert "error_code=DB_UNAVAILABLE" in text and "exc_type=OperationalError" in text

    caplog.clear()
    try:
        raise ValueError("plain bug")
    except ValueError:
        worker._log_failure("worker loop failed")
    assert caplog.records[0].exc_info is not None                   # DB 와 무관하면 traceback 유지
