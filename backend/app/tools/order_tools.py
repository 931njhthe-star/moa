"""주문 항목 조회 툴 — TOOL-004 · 005. **소유 조건이 조회 쿼리 안에 있다**(G-A3 ②).

    WHERE i.session_id = %s(ToolContext)  AND  i.item_id = %s(LLM 인자)

검증 코드를 따로 두지 않는다 — 조건을 쿼리에 박아 두면 "검사를 빠뜨린 경로"가 생기지 않는다.
남의 세션 항목 ID 는 행이 없으므로 빈 결과다. 존재 여부를 구분해 알려주지 않는다.
"""

from app import db
from app.tools.pii import mask_pii

_SELECT = (
    "SELECT i.item_id, i.person, COALESCE(m.name, i.menu_text) AS menu, i.options, "
    "       i.ambiguous_options, i.custom_request, i.quantity, i.validation_status "
    "  FROM app.order_item i LEFT JOIN app.menu m ON m.menu_id = i.menu_id "
    " WHERE i.session_id = %s AND i.removed = false"
)


def _project(row: dict) -> dict:
    """LLM 에 가는 모양 — 금액 · 판정 내부 값 · 토큰은 빼고, 자유 입력은 마스킹한다."""
    return {
        "item_id": row["item_id"],
        "person": row["person"],                       # 가명(PRD 2.5) — 원문 식별정보가 아니다
        "menu": mask_pii(row["menu"])[0],
        "options": row["options"] or {},
        "unclear": sorted((row["ambiguous_options"] or {}).keys()),
        "custom_request": mask_pii(row["custom_request"])[0] if row["custom_request"] else None,
        "quantity": row["quantity"],
        "needs_review": row["validation_status"] != "passed",
    }


def get_order_item(ctx, item_id: str) -> dict:
    """TOOL-004 — 항목 하나. 다른 세션의 item_id 는 빈 결과."""
    row = db.fetch_one(_SELECT + " AND i.item_id = %s", (ctx.session_id, item_id))
    return {"item": _project(row) if row else None}


def list_order_items(ctx) -> dict:
    """TOOL-005 — 이 세션의 항목 전체."""
    rows = db.fetch_all(_SELECT + " ORDER BY i.item_id", (ctx.session_id,))
    return {"items": [_project(r) for r in rows]}
