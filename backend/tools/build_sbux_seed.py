"""스타벅스 메뉴 시드 생성기 — 스타벅스_메뉴별_옵션정리.xlsx → sql/11_seed_menu_sbux.sql

    python tools/build_sbux_seed.py ../../스타벅스_메뉴별_옵션정리.xlsx      (backend/ 에서 실행)

규칙 (2026-11-04)
  - 가격이 있는 메뉴만 넣는다. 기본 사이즈의 가격이 base_price, 다른 사이즈는 그 차액이 size 옵션의
    extra_price 다(Short 는 음수). 메뉴 찾기 화면이 base_price 를 보여 주므로 기본 주문 금액과 같아야 한다.
    가격이 비어 있는 사이즈는 그 메뉴에 없다.
  - 옵션은 5종만 DB 로 관리한다: size · ice · shot · bean · cup. 그 밖의 요청은 기타 요청이다.
  - 기존 메뉴 ID(sb_001 ~ sb_027)는 유지한다(LEGACY). 평가셋 · 테스트가 이 ID 를 쓴다.
    새 메뉴 ID 는 sb_c{상품코드} 다 — 엑셀을 다시 돌려도 같은 ID 가 나온다.
  - 같은 이름이 두 행이면(기본 사이즈만 다른 변형) 기본 사이즈가 Tall 인 행을 쓴다.
  - 별칭은 sql/seed_src/sbux_alias.csv 에서 읽는다.
"""

import csv
import pathlib
import re
import sys

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "sql" / "11_seed_menu_sbux.sql"
ALIAS_CSV = ROOT / "sql" / "seed_src" / "sbux_alias.csv"
MENU_VERSION = "mv_20261029"          # app/config.py MENU_VERSION 과 같은 값 — ID 를 유지하므로 판을 올리지 않는다

SIZES = [("short", "Short", "숏"), ("tall", "Tall", "톨"), ("grande", "Grande", "그란데"),
         ("venti", "Venti", "벤티")]
SHOT_EXTRA, DECAF_EXTRA, CUP_DISCOUNT = 600, 300, -400       # 엑셀 가격·메모 열의 값

# 기존 ID → 엑셀 상품코드. name 이 있으면 그 이름을 쓴다(사용자가 부르는 이름 · 온도 짝 유지)
LEGACY = {
    "sb_004": {"code": "110563", "name": "아이스 아메리카노"},   # 엑셀 '아이스 카페 아메리카노'
    "sb_011": {"code": "94"}, "sb_003": {"code": "110569"}, "sb_012": {"code": "41"},
    "sb_006": {"code": "9200000006346"}, "sb_013": {"code": "9200000006343"},
    "sb_014": {"code": "110566"}, "sb_015": {"code": "110582"},
    "sb_016": {"code": "9200000000038"}, "sb_017": {"code": "9200000002081"},
    "sb_018": {"code": "20"}, "sb_002": {"code": "168016"}, "sb_019": {"code": "168010"},
    "sb_020": {"code": "168066"}, "sb_021": {"code": "9200000003276"},
    "sb_005": {"code": "9200000002956"}, "sb_023": {"code": "4004000000039"},
    "sb_024": {"code": "135612"}, "sb_025": {"code": "110621"},     # 아이스 초콜릿 → 아이스 시그니처 초콜릿
    "sb_026": {"code": "9200000002496"},                          # 그린 티 라떼 → 제주 말차 라떼
    "sb_027": {"code": "18"},
}
# 엑셀에 가격이 없는 기존 메뉴 — 이전 시드 가격을 가안으로 유지한다(사이즈 추가금도 이전 가안 +600 · +1,000)
LEGACY_FALLBACK = {"sb_017": 5900, "sb_018": 4000, "sb_024": 5800, "sb_027": 3800}
# 엑셀에 없는 기존 메뉴
#   sb_001 민트 초콜릿 칩 블렌디드 — PRD 8 기준 입력(참조 주문)의 정답 메뉴라 비활성하지 않는다(가격 가안)
#   sb_022 아이스 자스민 그린 티 — 비활성
NOT_IN_SHEET = {
    "sb_001": {"name": "민트 초콜릿 칩 블렌디드", "category": "블렌디드", "price": 5700,
               "groups": ["size", "ice", "cup"], "active": True},
    "sb_022": {"name": "아이스 자스민 그린 티", "category": "티", "price": 4500,
               "groups": [], "active": False},
}
# 이름이 같은 변형 중 버리는 행(상품코드) — 가격이 같고 기본 사이즈만 다르다
SKIP_CODES = {"9200000004770", "9200000004753", "9200000005310", "9200000004769",
              "9200000005516"}   # 마지막: 리저브 '아이스 아메리카노' — sb_004 와 이름 · 가격이 같다

# 기존 23종의 특성 태그는 그대로 둔다
LEGACY_TAGS = {
    "sb_004": [], "sb_011": ["따뜻한"], "sb_003": ["고소한"], "sb_012": ["고소한", "따뜻한"],
    "sb_006": ["단맛"], "sb_013": ["단맛", "따뜻한"], "sb_014": ["단맛"], "sb_015": ["단맛"],
    "sb_016": [], "sb_017": ["단맛"], "sb_018": [], "sb_001": ["단맛", "초콜릿", "카페인없음"],
    "sb_002": ["단맛", "초콜릿"], "sb_019": ["단맛"], "sb_020": ["단맛", "초콜릿", "카페인없음"],
    "sb_021": ["단맛", "과일", "카페인없음"], "sb_005": ["티", "과일", "카페인없음"], "sb_022": ["티"],
    "sb_023": ["티"], "sb_024": ["티", "단맛"], "sb_025": ["단맛", "초콜릿", "카페인없음"],
    "sb_026": ["티", "단맛"], "sb_027": ["카페인없음"],
}
_SWEET = ("초콜릿", "카라멜", "바닐라", "모카", "돌체", "크림", "꿀", "프라푸치노", "블렌디드", "요거트",
          "밀크", "스위트")
_FRUIT = ("망고", "딸기", "자몽", "유자", "라임", "피치", "복숭아", "체리", "레몬", "아사이", "패션")
_NO_CAFFEINE = ("캐모마일", "히비스커스", "민트 블렌드", "유스베리", "요거트", "망고", "초콜릿 크림 칩")
_HOT_CATEGORIES = ("에스프레소", "브루드 커피", "티", "기타 제조 음료")


def tags_for(name: str, category: str) -> list[str]:
    tags = []
    if any(w in name for w in _SWEET):
        tags.append("단맛")
    if "초콜릿" in name or "모카" in name or "자바 칩" in name:
        tags.append("초콜릿")
    if any(w in name for w in _FRUIT):
        tags.append("과일")
    if category == "티":
        tags.append("티")
    if any(w in name for w in _NO_CAFFEINE):
        tags.append("카페인없음")
    if category in _HOT_CATEGORIES and "아이스" not in name and "콜드" not in name:
        tags.append("따뜻한")
    return tags


def default_size(size_text: str, available: list[str]) -> str:
    for value, word, _ in SIZES:
        if value in available and re.search(rf"{word}\([^)]*기본\)", size_text or ""):
            return value
    return available[0]


def read_sheet(path: str) -> dict[str, dict]:
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r[2]:
            continue
        code = str(r[1]).strip()
        prices = {value: r[11 + i] for i, (value, _, _) in enumerate(SIZES)}
        rows[code] = {
            "category": r[0], "code": code, "name": r[2].strip(), "size_text": r[3] or "",
            "bean_shot": r[4] or "", "ice_cup": r[8] or "",
            "prices": {k: int(v) for k, v in prices.items() if v not in (None, "")},
        }
    return rows


def groups_for(row: dict) -> list[str]:
    groups = []
    if row["prices"] and row["size_text"].strip() != "선택 없음":
        groups.append("size")
    if "얼음" in row["ice_cup"]:
        groups.append("ice")
    if "샷" in row["bean_shot"]:
        groups.append("shot")
    if "시그니처" in row["bean_shot"]:
        groups.append("bean")
    if "개인컵" in row["ice_cup"]:
        groups.append("cup")
    return groups


def build(path: str) -> tuple[list[dict], list[dict]]:
    sheet = read_sheet(path)
    legacy_codes = {v["code"]: mid for mid, v in LEGACY.items()}
    menus, skipped = [], []
    for code, row in sheet.items():
        menu_id = legacy_codes.get(code)
        if code in SKIP_CODES and not menu_id:
            skipped.append({**row, "why": "같은 이름 변형"})
            continue
        prices = dict(row["prices"])
        fallback = False
        if not prices and menu_id in LEGACY_FALLBACK:
            base = LEGACY_FALLBACK[menu_id]
            sizes = [v for v, w, _ in SIZES if w in row["size_text"] and v != "short"]
            prices = ({"tall": base, "grande": base + 600, "venti": base + 1000} if sizes else {"tall": base})
            prices = {k: v for k, v in prices.items() if not sizes or k in sizes}
            fallback = True
        if not prices:
            skipped.append({**row, "why": "가격 없음"})
            continue
        menu_id = menu_id or f"sb_c{code}"
        name = LEGACY.get(menu_id, {}).get("name") or row["name"]
        available = [v for v, _, _ in SIZES if v in prices]
        chosen = default_size(row["size_text"], available)
        groups = groups_for(row)
        if fallback and len(prices) > 1 and "size" not in groups:
            groups.insert(0, "size")
        menus.append({
            "menu_id": menu_id, "code": code, "name": name, "category": row["category"],
            "prices": prices, "base": prices[chosen], "sizes": available,
            "default_size": chosen, "groups": groups,
            "tags": LEGACY_TAGS.get(menu_id, tags_for(name, row["category"])),
            "active": True, "note": "가격 가안(엑셀 미기재 · 이전 시드값)" if fallback else "",
        })
    for menu_id, spec in NOT_IN_SHEET.items():
        base = spec["price"]
        prices = {"tall": base, "grande": base + 600, "venti": base + 1000} if "size" in spec["groups"] else {}
        menus.append({
            "menu_id": menu_id, "code": "", "name": spec["name"], "category": spec["category"],
            "prices": prices or {"tall": base}, "base": base, "sizes": list(prices),
            "default_size": "tall", "groups": spec["groups"], "tags": LEGACY_TAGS[menu_id],
            "active": spec["active"],
            "note": "엑셀에 없음 · 가격 가안" if spec["active"] else "엑셀에 없음 · 비활성",
        })
    return menus, skipped


def option_rows(menu: dict) -> list[tuple]:
    mid, rows = menu["menu_id"], []

    def add(group, value, label, price, default):
        rows.append((f"sb_opt_{mid}_{group}_{value}", mid, group, value, label, price, default))

    if "size" in menu["groups"]:
        for value, _, label in SIZES:
            if value in menu["sizes"]:
                add("size", value, label, menu["prices"][value] - menu["base"], value == menu["default_size"])
    if "ice" in menu["groups"]:
        for value, label, default in [("none", "없이", False), ("less", "적게", False),
                                      ("normal", "보통", True), ("more", "많이", False)]:
            add("ice", value, label, 0, default)
    if "shot" in menu["groups"]:
        add("shot", "base", "기본", 0, True)
        add("shot", "extra", "샷 추가", SHOT_EXTRA, False)
    if "bean" in menu["groups"]:
        add("bean", "signature", "시그니처", 0, True)
        add("bean", "blonde", "블론드", 0, False)
        add("bean", "decaf", "디카페인", DECAF_EXTRA, False)
    if "cup" in menu["groups"]:
        add("cup", "none", "미사용", 0, True)
        add("cup", "personal", "사용", CUP_DISCOUNT, False)
    return rows


def q(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def render(menus: list[dict], source: str) -> str:
    aliases = list(csv.DictReader(ALIAS_CSV.open(encoding="utf-8")))
    known = {m["menu_id"] for m in menus}
    missing = [a for a in aliases if a["menu_id"] not in known]
    if missing:
        raise SystemExit(f"[중단] 별칭이 없는 메뉴를 가리킨다: {missing}")

    out = [
        "-- =====================================================================",
        "-- 11_seed_menu_sbux.sql — 스타벅스 기준 메뉴 · 별칭 · 옵션 (D-07 4.11 · 8절)",
        "--",
        "-- ★ 생성 파일이다. 손으로 고치지 말고 생성기를 다시 돌린다:",
        "--     python tools/build_sbux_seed.py <스타벅스_메뉴별_옵션정리.xlsx>",
        f"--   출처: {source} (메뉴 · 사이즈별 가격 · 옵션) · 별칭: sql/seed_src/sbux_alias.csv",
        "--   공개 메뉴 기준 시연 데이터 · 로고 미사용 (PRD 2.4 · R-13)",
        "--",
        "--   가격: 기본 사이즈 가격이 base_price, 다른 사이즈는 차액이 size 옵션 추가금이다(Short 는 음수).",
        f"--   옵션 5종만 DB 로 관리한다 — size · ice · shot(+{SHOT_EXTRA}) · bean(디카페인 +{DECAF_EXTRA}) ·",
        f"--   cup(개인컵 {CUP_DISCOUNT}). 시럽 · 우유 · 휘핑 등 그 밖의 요청은 기타 요청(custom_request)이다.",
        "--   가격이 없는 엑셀 행은 넣지 않는다(생성기 출력의 '제외' 목록).",
        f"--   기준 menu_version = '{MENU_VERSION}' (app/config.py MENU_VERSION 과 같은 값)",
        "-- =====================================================================",
        "",
        "INSERT INTO app.menu (menu_id, brand_id, menu_version, category, name, base_price, trait_tags, is_active) VALUES",
    ]
    values = []
    for m in menus:
        tags = "{" + ",".join(f'"{t}"' for t in m["tags"]) + "}"
        note = f"  -- {m['note']}" if m["note"] else ""
        values.append(f"  ({q(m['menu_id'])}, 'starbucks', {q(MENU_VERSION)}, {q(m['category'])}, "
                      f"{q(m['name'])}, {m['base']}, {q(tags)}, {'true' if m['active'] else 'false'}){{sep}}{note}")
    out += [v.replace("{sep}", "," if i < len(values) - 1 else "") for i, v in enumerate(values)]
    out += [
        "ON CONFLICT (menu_id) DO UPDATE",
        "   SET menu_version = EXCLUDED.menu_version, category = EXCLUDED.category, name = EXCLUDED.name,",
        "       base_price = EXCLUDED.base_price, trait_tags = EXCLUDED.trait_tags, is_active = EXCLUDED.is_active;",
        "",
        "-- --------------------------------------------------------------------",
        "-- 별칭 — 정규화 키로 저장한다 (소문자 · 공백 제거 · D-07 4.11). 메뉴 이름 자체는 적지 않는다",
        "-- --------------------------------------------------------------------",
        "DELETE FROM app.menu_alias WHERE brand_id = 'starbucks';",
        "INSERT INTO app.menu_alias (alias, menu_id, brand_id) VALUES",
    ]
    out += [f"  ({q(a['alias'])}, {q(a['menu_id'])}, 'starbucks')" + ("," if i < len(aliases) - 1 else "")
            for i, a in enumerate(aliases)]
    out += [
        "ON CONFLICT (alias, menu_id) DO NOTHING;",
        "",
        "-- --------------------------------------------------------------------",
        "-- 옵션 — 메뉴마다 따로 적는다. 매장 공통 행을 두지 않는다 — 공통 행은 그 종류를 모든 메뉴에 붙인다.",
        "-- 메뉴가 아직 안 정해진 항목은 매장 전체 값의 합집합으로 검증한다(menu.applicable_options)",
        "-- --------------------------------------------------------------------",
        "DELETE FROM app.menu_option WHERE brand_id = 'starbucks';",
        "INSERT INTO app.menu_option (option_id, menu_id, category, brand_id, option_group, option_value, value_label, extra_price, is_default) VALUES",
    ]
    rows = [r for m in menus if m["active"] for r in option_rows(m)]
    out += [f"  ({q(oid)}, {q(mid)}, NULL, 'starbucks', {q(g)}, {q(v)}, {q(label)}, {price}, "
            f"{'true' if default else 'false'})" + ("," if i < len(rows) - 1 else "")
            for i, (oid, mid, g, v, label, price, default) in enumerate(rows)]
    out += ["ON CONFLICT (option_id) DO UPDATE",
            "   SET extra_price = EXCLUDED.extra_price, value_label = EXCLUDED.value_label,",
            "       is_default = EXCLUDED.is_default;", ""]
    return "\n".join(out)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    menus, skipped = build(path)
    OUT.write_text(render(menus, pathlib.Path(path).name), encoding="utf-8")
    active = [m for m in menus if m["active"]]
    print(f"메뉴 {len(active)}종 활성 · {len(menus) - len(active)}종 비활성 · 옵션 "
          f"{sum(len(option_rows(m)) for m in active)}행 -> {OUT.relative_to(ROOT)}")
    print(f"제외 {len(skipped)}행 (가격 없음 {sum(s['why'] == '가격 없음' for s in skipped)} · "
          f"같은 이름 변형 {sum(s['why'] != '가격 없음' for s in skipped)})")
    for m in menus:
        if m["note"]:
            print(f"  {m['menu_id']} {m['name']}: {m['note']}")


if __name__ == "__main__":
    main()
