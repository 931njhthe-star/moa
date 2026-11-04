# Q-03 공용 가짜 — 그래프 전체를 DB 없이 태운다 (Q-01 "신규(그래프 전체 · DB 가짜)").
#
# 진짜로 돌리는 것: N-01 ~ N-10 노드 · 메뉴 매칭 규칙 · 대상 연결 · 규칙 검증 · 출력 가드.
# 가짜로 두는 것: DB 읽기 · 쓰기 하나하나. 메뉴판은 시드(sql/11)에서 쓰는 몇 줄만 메모리 캐시에 넣는다.
#
# 실제 DB 로 같은 흐름을 보는 것은 tests/test_live_flow.py(MOA_LIVE_DB=1) 다. 둘은 겹치지 않는다 —
# 이쪽은 CI 에서 돌아야 하고, 저쪽은 "응답 200 인데 숫자가 틀림"을 잡는다.
import contextlib
import time

from app import db
from app.graph import nodes
from app.services import menu as menu_service
from app.services import sessions, settlement

BRAND, MENU_VERSION = "starbucks", "mv_20261029"
SESSION = {"session_id": "ORD-0001", "brand_id": BRAND, "menu_version": MENU_VERSION,
           "status": "running", "version": 1, "checkpoint": "created", "token_hash": "h",
           "is_verification": False, "brand_source": "request_line", "brand_evidence_text": None,
           "trace_id": "tr_Q03"}

# 시드(sql/11_seed_menu_sbux.sql)에서 그대로 옮긴 행 — 값이 달라지면 시드를 보고 맞춘다
MENUS = [
    {"menu_id": "sb_004", "brand_id": BRAND, "menu_version": MENU_VERSION,
     "category": "에스프레소", "name": "아이스 아메리카노", "base_price": 4500, "trait_tags": []},
    {"menu_id": "sb_012", "brand_id": BRAND, "menu_version": MENU_VERSION,
     "category": "에스프레소", "name": "카페 라떼", "base_price": 5000, "trait_tags": ["고소한", "따뜻한"]},
    {"menu_id": "sb_003", "brand_id": BRAND, "menu_version": MENU_VERSION,
     "category": "에스프레소", "name": "아이스 카페 라떼", "base_price": 5000, "trait_tags": ["고소한"]},
    {"menu_id": "sb_013", "brand_id": BRAND, "menu_version": MENU_VERSION,
     "category": "에스프레소", "name": "바닐라라떼", "base_price": 5100, "trait_tags": ["단맛", "따뜻한"]},
    {"menu_id": "sb_006", "brand_id": BRAND, "menu_version": MENU_VERSION,
     "category": "에스프레소", "name": "아이스 바닐라라떼", "base_price": 5100, "trait_tags": ["단맛"]},
]
ALIASES = [("아아", "sb_004"), ("아이스아메", "sb_004"), ("아이스아메리카노", "sb_004"),
           ("라떼", "sb_012"), ("아이스바닐라라떼", "sb_006")]
OPTIONS = [
    ("sb_opt_size_tall", "size", "tall", "톨", 0, True),
    ("sb_opt_size_grande", "size", "grande", "그란데", 600, False),
    ("sb_opt_size_venti", "size", "venti", "벤티", 1000, False),
    ("sb_opt_ice_less", "ice", "less", "적게", 0, False),
    ("sb_opt_ice_normal", "ice", "normal", "보통", 0, True),
    ("sb_opt_ice_more", "ice", "more", "많이", 0, False),
    ("sb_opt_shot_base", "shot", "base", "기본", 0, True),
    ("sb_opt_shot_extra", "shot", "extra", "샷 추가", 600, False),
]


def catalog() -> dict:
    """menu._load 가 돌려주는 모양 그대로 — 캐시에 직접 넣어 DB 를 빼낸다."""
    from app.services.text_norm import normalize

    alias_index: dict[str, list[str]] = {}
    for m in MENUS:
        alias_index.setdefault(normalize(m["name"]), []).append(m["menu_id"])
    for alias, menu_id in ALIASES:
        alias_index.setdefault(normalize(alias), []).append(menu_id)
    options = [{"option_id": oid, "menu_id": None, "category": None, "option_group": group,
                "option_value": value, "value_label": label, "extra_price": price,
                "is_default": is_default}
               for oid, group, value, label, price, is_default in OPTIONS]
    return {"menus": MENUS, "by_id": {m["menu_id"]: m for m in MENUS},
            "alias_index": alias_index, "options": options,
            "store_words": ["스타벅스", "스벅"], "loaded_at": time.monotonic()}


class Store:
    """가짜 저장소 — 주문 항목 · 이벤트 · 질문 · 체크포인트 · 상태를 메모리에 모은다."""

    def __init__(self):
        self.items: list[dict] = []
        self.events: list[dict] = []
        self.checkpoints: list[str] = []
        self.status: str | None = None
        self.settlement: list[dict] = []
        self.questions: list[dict] = []
        self.changes: list[dict] = []
        self.sql: list[str] = []

    def live(self) -> list[dict]:
        return [r for r in self.items if not r.get("removed")]

    def review_count(self) -> int:
        return sum(1 for r in self.live() if r.get("validation_status") == "needs_review")


def install(monkeypatch, store: Store, messages: list[dict] | None = None) -> Store:
    """DB 를 쓰는 지점만 가짜로 바꾼다. 노드 로직은 그대로 돈다.

    messages 를 주면 N-01 의 app.message 조회가 그것을 돌려준다(분석 경로).
    """
    monkeypatch.setitem(menu_service._CACHE, (BRAND, MENU_VERSION), catalog())

    class Cur:
        rowcount = 1

        def execute(self, sql, params=None):
            store.sql.append(" ".join(sql.split()))

        def fetchone(self):
            return None

        def fetchall(self):
            return []

        def executemany(self, sql, rows):
            store.sql.append(" ".join(sql.split()))

    @contextlib.contextmanager
    def fake_transaction(role="app"):
        yield Cur()

    monkeypatch.setattr(db, "transaction", fake_transaction)
    monkeypatch.setattr(db, "execute", lambda sql, params=None, **k: store.sql.append(" ".join(sql.split())))
    monkeypatch.setattr(db, "fetch_one", lambda sql, params=None, **k: {"snapshot_id": "ORD-0001-s1"})

    def fake_fetch_all(sql, params=None, **k):
        if "FROM app.message" in sql:
            return list(messages or [])
        return []

    monkeypatch.setattr(db, "fetch_all", fake_fetch_all)

    monkeypatch.setattr(sessions, "set_checkpoint",
                        lambda cur, session_id, checkpoint: store.checkpoints.append(checkpoint))
    monkeypatch.setattr(sessions, "set_status",
                        lambda cur, session_id, status: setattr(store, "status", status))
    monkeypatch.setattr(sessions, "items", lambda session_id, include_removed=False:
                        store.items if include_removed else store.live())
    monkeypatch.setattr(sessions, "review_count", lambda session_id: store.review_count())
    monkeypatch.setattr(sessions, "_insert_events",
                        lambda cur, session_id, snapshot_id, events, trace_id:
                        store.events.extend(events))
    monkeypatch.setattr(sessions, "_insert_items",
                        lambda cur, session_id, rows: store.items.extend(_as_item(r) for r in rows))
    monkeypatch.setattr(sessions, "_build_questions",
                        lambda session_id, rows, *, brand_id, menu_version:
                        store.questions.extend(_as_question(r) for r in rows
                                               if r.get("validation_status") == "needs_review"))
    monkeypatch.setattr(settlement, "save_lines",
                        lambda session_id, version, lines, *, cur=None: store.settlement.extend(lines))
    return store


def _as_item(row: dict) -> dict:
    """_insert_items 가 DB 에 넣는 칸만 — 뒤 단계(정산 · 가드 · 질문)가 읽는 모양."""
    return {"item_id": row.get("item_id"), "person": row.get("person"),
            "menu_id": row.get("menu_id"), "menu_name": row.get("menu_name"),
            "menu_text": row.get("menu_text"), "quantity": row.get("quantity") or 1,
            "options": row.get("options") or {}, "ambiguous_options": row.get("ambiguous_options") or {},
            "validation_status": row.get("validation_status"), "rule_verdict": row.get("rule_verdict"),
            "review_reason": row.get("review_reason"),
            "review_reason_text": row.get("review_reason_text"),
            "removed": bool(row.get("_removed")), "candidates": row.get("candidates") or [],
            "unit_price": row.get("unit_price"), "estimated_price": row.get("estimated_price")}


def _as_question(row: dict) -> dict:
    return {"item_id": row.get("item_id"), "question_text": row.get("review_reason_text"),
            "options": row.get("candidates") or []}


def no_interpreter(monkeypatch):
    """해석 서비스 없음 — 규칙 해석으로 돈다(LLM 0회). 경로는 규칙이 정한다."""
    from app import config

    monkeypatch.setattr(config, "ORDER_INTERPRETER_PRIMARY_URL", "")
    monkeypatch.setattr(config, "ORDER_INTERPRETER_BACKUP_URL", "")
    monkeypatch.setattr(nodes, "_pick_service", lambda: None)


def chat(lines: list[str]) -> list[dict]:
    """[이름] 문장 줄을 N-01 이 넘기는 messages 모양으로."""
    out = []
    for i, line in enumerate(lines, start=1):
        sender, _, text = line.partition("] ")
        out.append({"message_id": f"m{i}", "seq": i, "sender": sender.lstrip("["), "text": text})
    return out
