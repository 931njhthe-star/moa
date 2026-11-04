"""메뉴 조회 툴 — TOOL-001 ~ 003. 매장 기준(`brand_id` · `menu_version`)은 ToolContext 에서만 온다.

다른 매장 기준의 메뉴는 **보이지 않는다**(FR-004 — 일반 카페 기준일 때 스타벅스 메뉴 0건).
반환은 답에 필요한 최소 필드다 — 원가 · 내부 플래그 · 버전 문자열은 돌려주지 않는다.
"""

from app.services import menu as menu_service

# 메뉴 DB 의 trait_tags 값 (sql/11 · 12). 목록 밖의 태그는 스키마가 거부한다
TRAITS = ["단맛", "고소한", "과일", "초콜릿", "카페인없음", "따뜻한", "티"]


def _brief(hit: dict) -> dict:
    return {"menu_id": hit["menu_id"], "name": hit["name"], "base_price": hit["base_price"],
            "trait_tags": list(hit.get("trait_tags") or [])}


def search_menu(ctx, query: str, limit: int = 5) -> dict:
    """TOOL-001 — 이름 · 별칭 검색. 매칭 규칙은 분석 경로와 같은 함수(menu.search)를 쓴다."""
    hits = menu_service.search(ctx.brand_id, ctx.menu_version, query, limit=limit)
    return {"menus": [_brief(h) for h in hits]}


def find_menu_by_traits(ctx, traits: list[str]) -> dict:
    """TOOL-002 — 특성 표현 후보. 정렬 근거 태그를 함께 준다(FR-004). 후보가 하나여도 확정 근거가 아니다."""
    hits = menu_service.by_traits(ctx.brand_id, ctx.menu_version, traits)[:5]
    return {"menus": [{**_brief(h), "reason_tags": h.get("reason_tags", [])} for h in hits]}


def get_menu(ctx, menu_id: str) -> dict:
    """TOOL-003 — 메뉴 하나의 사양 · 옵션. **세션 매장 기준에 없는 menu_id 는 빈 결과**다."""
    cat = menu_service.catalog(ctx.brand_id, ctx.menu_version)
    menu = cat["by_id"].get(menu_id)
    if menu is None:
        return {"menu": None, "options": []}
    groups = menu_service.option_groups(ctx.brand_id, ctx.menu_version, menu_id)
    return {
        "menu": {"menu_id": menu_id, "name": menu["name"], "category": menu["category"],
                 "base_price": menu["base_price"]},
        "options": [{"group": g["option_group"],
                     "values": [{"value": v["option_value"], "label": v["value_label"],
                                 "extra_price": v["extra_price"]} for v in g["values"]]}
                    for g in groups],
    }
