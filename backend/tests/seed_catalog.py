# 저장소 SQL 시드(sql/10 · 11 · 12)를 그대로 읽어 메뉴 캐시 · 매장 사전에 넣는다 — DB 없이 실제 가격으로 돈다.
#
# q03_fakes 의 메뉴판은 시드에서 몇 줄만 옮긴 것이라 가격 · 별칭이 실제와 다를 수 있다. QA 재현(2026-11-06
# 코드 수정 요청서 MOA-CORE-001 · 002)은 시드 mv_20261029 전체 기준이므로, 같은 조건을 이 모듈로 만든다.
import re
import time
from pathlib import Path

SQL = Path(__file__).resolve().parents[1] / "sql"
_TOKEN = re.compile(r"'((?:[^']|'')*)'|(NULL|true|false)|(-?\d+)", re.IGNORECASE)


def _rows(path: Path, table: str) -> tuple[list[str], list[list]]:
    """`INSERT INTO <table> (cols) VALUES (...), (...);` 의 행들. 여러 INSERT 가 있으면 모두 모은다."""
    text = path.read_text(encoding="utf-8")
    text = "\n".join(line.split("--")[0] if not line.lstrip().startswith("(") else re.sub(r"\)\s*,?\s*--.*$", ")", line)
                     for line in text.splitlines())
    cols, rows = [], []
    for block in re.finditer(r"INSERT INTO " + re.escape(table) + r" \(([^)]*)\) VALUES(.*?)(?:ON CONFLICT|;)",
                             text, re.S):
        cols = [c.strip() for c in block.group(1).split(",")]
        for tup in re.finditer(r"\(((?:'(?:[^']|'')*'|[^()'])*)\)", block.group(2)):
            values = []
            for hit in _TOKEN.finditer(tup.group(1)):
                if hit.group(1) is not None:
                    values.append(hit.group(1).replace("''", "'"))
                elif hit.group(2) is not None:
                    word = hit.group(2).lower()
                    values.append(None if word == "null" else word == "true")
                else:
                    values.append(int(hit.group(3)))
            if len(values) == len(cols):
                rows.append(values)
    return cols, rows


def _dicts(path: Path, table: str) -> list[dict]:
    cols, rows = _rows(path, table)
    return [dict(zip(cols, r)) for r in rows]


def _array(value) -> list[str]:
    inner = (value or "{}").strip("{}")
    return [v.strip('"') for v in inner.split(",") if v.strip('"')]


def catalog(brand_id: str, menu_version: str = "mv_20261029") -> dict:
    """menu._load 와 같은 모양 — 시드 파일에서."""
    from app.services.text_norm import normalize

    path = SQL / ("11_seed_menu_sbux.sql" if brand_id == "starbucks" else "12_seed_menu_generic.sql")
    menus = [{**m, "trait_tags": _array(m["trait_tags"])} for m in _dicts(path, "app.menu")
             if m["brand_id"] == brand_id and m["menu_version"] == menu_version and m.get("is_active", True)]
    for m in menus:
        m.pop("is_active", None)
    by_id = {m["menu_id"]: m for m in menus}
    alias_index: dict[str, list[str]] = {}
    for m in menus:
        alias_index.setdefault(normalize(m["name"]), []).append(m["menu_id"])
    for row in _dicts(path, "app.menu_alias"):
        if row["menu_id"] in by_id:
            alias_index.setdefault(normalize(row["alias"]), []).append(row["menu_id"])
    options = [{k: v for k, v in o.items() if k != "brand_id"} for o in _dicts(path, "app.menu_option")]
    options.sort(key=lambda o: (o["option_group"], o["extra_price"]))
    store_words = sorted({normalize(r["alias"]) for r in brand_aliases()} - {""}, key=len, reverse=True)
    return {"menus": menus, "by_id": by_id, "alias_index": alias_index, "options": options,
            "store_words": store_words, "loaded_at": time.monotonic()}


def brand_aliases() -> list[dict]:
    return _dicts(SQL / "10_seed_brand.sql", "app.brand_alias")


def install(monkeypatch, menu_version: str = "mv_20261029") -> None:
    """두 매장 메뉴판과 매장 사전을 시드 그대로 끼운다."""
    from app.services import brand as brand_service
    from app.services import menu as menu_service
    from app.services.text_norm import normalize

    for brand_id in ("starbucks", "generic"):
        monkeypatch.setitem(menu_service._CACHE, (brand_id, menu_version), catalog(brand_id, menu_version))

    def dictionary():
        rows = [{**r, "_key": normalize(r["alias"])} for r in brand_aliases()]
        return sorted(rows, key=lambda r: -len(r["_key"]))

    monkeypatch.setattr(brand_service, "_dictionary", dictionary)
