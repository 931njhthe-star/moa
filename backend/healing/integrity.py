"""복구 시험 회차의 주문 무결성 — SC-5 "복구 전후 주문 중복 · 유실 0건" (2026-11-09).

장애를 넣기 **전에** 주문 세션마다 항목 지문을 떠 두고, 복구가 끝난 **뒤에** 같은 세션을 다시 떠서 견준다.
DEP-5(`scripts/dep-test.sh`)가 앱 전환 한 번에 하던 "항목 수 전후 비교"를 시험 회차마다 하는 것이다.

비교 대상은 **그 사이 아무도 손대지 않은 세션**뿐이다. 담당자가 시험 중에 바꾸기 · 답장 반영을 하면
지문이 정당하게 달라지므로, 그 창 안에 GET 이 아닌 요청이 그 세션을 가리킨 기록(app.request_history)이
있으면 뺀다. 손대지 않았는데 지문이 달라졌다면 복구 동작(재시작 · 전환 · 재연결 · 재개)이 주문을
두 번 넣었거나 잃은 것이다.

비교할 세션이 0개면 측정하지 않은 것으로 둔다 — "0건"은 비교한 세션이 있을 때만 말한다.
"""

from app import db

SESSION_LIMIT = 500          # 최근 갱신 순 — 시험 한 회차에 훑는 세션 상한

# 항목 지문 — 항목 id · 삭제 여부 · 수량 · 금액 · 주문자 · 메뉴. 순서를 고정해 같은 상태면 같은 값이 나온다
_FINGERPRINT = (
    "SELECT s.session_id, COUNT(i.item_id) AS items, "
    "       md5(COALESCE(string_agg(concat_ws(':', i.item_id, i.removed, i.quantity, i.estimated_price, "
    "                                         i.person, i.menu_id), ',' ORDER BY i.item_id), '')) AS digest "
    "  FROM app.order_session s LEFT JOIN app.order_item i ON i.session_id = s.session_id ")


def snapshot() -> dict | None:
    """장애 주입 직전 지문. DB 를 못 읽으면 None — 그 회차는 미측정이다."""
    try:
        at = db.fetch_one("SELECT NOW() AS at", role="healing")["at"]
        rows = db.fetch_all(
            "SELECT * FROM (" + _FINGERPRINT +
            " GROUP BY s.session_id, s.updated_at ORDER BY s.updated_at DESC LIMIT %s) t",
            (SESSION_LIMIT,), role="healing")
    except Exception:            # noqa: BLE001 — 측정 실패가 시험 회차를 깨지 않는다
        return None
    return {"at": at, "sessions": {r["session_id"]: _fp(r) for r in rows}}


def check(before: dict | None) -> dict:
    """복구 뒤 지문을 떠서 견준다. 결과는 workflow_iteration.result 의 `integrity` 칸에 그대로 들어간다."""
    if not before:
        return {"measured": False, "reason": "장애 전 주문 상태를 읽지 못했어요"}
    ids = list(before["sessions"])
    if not ids:
        return {"measured": False, "reason": "비교할 주문 세션이 없어요"}
    try:
        rows = db.fetch_all(_FINGERPRINT + " WHERE s.session_id = ANY(%s) GROUP BY s.session_id",
                            (ids,), role="healing")
        touched_rows = db.fetch_all(
            "SELECT session_id, path FROM app.request_history "
            " WHERE created_at >= %s AND method <> 'GET'", (before["at"],), role="healing")
    except Exception:            # noqa: BLE001
        return {"measured": False, "reason": "복구 뒤 주문 상태를 읽지 못했어요"}
    return compare(before["sessions"], {r["session_id"]: _fp(r) for r in rows},
                   touched(ids, touched_rows))


def touched(ids: list[str], rows: list[dict]) -> set[str]:
    """창 안에 바꾸는 요청이 가리킨 세션. session_id 칸이 비어도 경로에 세션 id 가 있으면 잡는다."""
    hit = {r["session_id"] for r in rows if r.get("session_id")}
    paths = [r.get("path") or "" for r in rows]
    return hit | {sid for sid in ids if any(sid in p for p in paths)}


def compare(before: dict, after: dict, skip: set[str]) -> dict:
    compared = issues = 0
    changed: list[str] = []
    for sid, fp in before.items():
        if sid in skip:
            continue
        compared += 1
        now = after.get(sid)
        if now is None:                                   # 세션째 사라졌다 — 항목 전부 유실
            issues += max(fp["items"], 1)
        elif now["digest"] != fp["digest"]:               # 늘었으면 중복 · 줄었으면 유실 · 같으면 내용 변조
            issues += max(abs(now["items"] - fp["items"]), 1)
        else:
            continue
        changed.append(sid)
    if compared == 0:
        return {"measured": False, "reason": "시험 중 모든 주문 세션이 사용 중이라 비교하지 않았어요",
                "skipped": len(skip & set(before))}
    return {"measured": True, "compared": compared, "skipped": len(before) - compared,
            "issues": issues, "changed": changed[:5]}


def _fp(row: dict) -> dict:
    return {"items": int(row["items"]), "digest": row["digest"]}
