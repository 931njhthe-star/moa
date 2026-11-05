"""인원별 정리 — 이벤트를 **사람 단위로 다시 본다** (2026-11-05 사용자 보고 2 · 5 · 7 · 8번).

왜 필요한가: Intake 는 메시지 하나씩 판정한다(묶음 4건 + 앞 4건). 그래서 주문이 아닌 말이
주문으로 올라오고("네네 스타벅스입니다~"), 한 사람이 말한 횟수만큼 잔이 늘었다
(김민수 대리 혼자 5잔 — 사용자 보고 7번). 메시지 단위 판정을 고치는 것으로는 막을 수 없다 —
**그 사람의 다른 말과 함께 봐야** 주문인지 알 수 있기 때문이다.

이 모듈은 LLM 을 부르지 않는다. 같은 입력에 같은 결과가 나오는 규칙이며, LLM 해석과 규칙 해석
**양쪽 뒤에** 똑같이 걸린다(N-04). LLM 프롬프트(classify.md)도 같은 판단을 하도록 고쳤지만,
확률적으로 동작하므로 규칙이 마지막 방어선이다.

세 가지만 한다. 메뉴를 고르거나 금액을 만지지 않는다.
  1 주문이 아닌 말은 항목을 만들지 않는다        add  -> ignore   (보고 2 · 7번)
  2 메뉴 없이 사양만 말한 것은 앞 주문의 변경이다  add  -> update  (보고 8번)
  3 자기 주문을 가리키며 사양만 말한 잡담도 변경이다 ignore -> update (보고 8번 · 규칙 해석 경로)
"""

import re

from app.services import intake
from app.services import menu as menu_service

# 자기 주문을 가리키는 말 — 3번(ignore -> update)을 좁히는 조건이다.
# 이것이 없으면 "ㅋㅋ 샷 추가면 비싸겠네" 같은 잡담이 앞 주문을 바꾼다
_MINE = re.compile(r"제\s*거|제\s*것|내\s*거|내\s*것|제꺼|내꺼|저는|전\s|난\s|나는|제\s*건")

# 앞서 한 주문을 되짚는 말 — "아까 카라멜 마키아또 주문했는데 샷 하나 더 추가해주세요"(2026-11-05 2차 보고 2번).
# 이 말이 있으면 **새 주문이 아니라 그 주문의 변경**이다. 없으면 "라떼 하나 더요"처럼 한 잔 더 받는 것이다
# "한 잔 더"인가 "그 잔을 바꿔"인가 — 보탬 말과 바꿈 말을 가른다 (2026-11-05 3차 보고).
#   "아 저 카페 라떼도 하나 추가요"를 LLM 이 update 로 보고, 앞 주문에 반영하려다 **잔이 사라졌다**
_ADD_MORE = re.compile(r"추가|하나\s*더|한\s*잔\s*더|더\s*주세요|더\s*주시|도\s*하나|도\s*한\s*잔|또\s*하나")
_REPLACE = re.compile(r"바꿔|바꿀|변경|말고|대신|수정|취소")

_LOOKBACK = re.compile(r"아까|방금|조금\s*전|앞서|먼저\s*(?:말한|시킨|주문한)|제가\s*(?:시킨|주문한)|"
                       r"주문했는데|시켰는데|말했는데|했는데")


def menu_signal(item: dict, *, brand_id: str, menu_version: str) -> str:
    """이 항목이 무엇을 근거로 메뉴가 되는가 — menu · trait · reference · option · none.

    `menu` 는 메뉴판에 걸린 것이다(확정이든 후보든). `none` 은 메뉴판과 아무 관계가 없는 말이다.
    """
    text = item.get("match_text") or item.get("menu_text") or ""
    hit = menu_service.match(brand_id, menu_version, text)
    if hit.get("menu_id") or hit.get("candidates"):
        return "menu"
    if (item.get("options") or item.get("ambiguous_options")) and _only_option_traits(item):
        # 사양만 말했다 — "디카페인으로"는 옵션 값이면서 특성 낱말이기도 하다. 그 특성은 메뉴를 고르는
        # 근거가 아니다(보고 8번). 반대로 "달달한 거 그란데로"는 옵션과 **별개의** 특성이라 trait 다
        return "option"
    if item.get("traits"):
        return "trait"
    if item.get("reference"):
        return "reference"
    if item.get("options") or item.get("ambiguous_options"):
        return "option"
    return "none"


def _only_option_traits(item: dict) -> bool:
    """이 항목의 특성이 **옵션 낱말에서 나온 것뿐인가** — 그렇다면 메뉴를 고를 근거가 없다."""
    words = " ".join(str(v) for v in (item.get("option_words") or {}).values())
    return set(item.get("traits") or []) <= set(intake._traits(words))


def consolidate(events: list[dict], *, brand_id: str, menu_version: str) -> list[dict]:
    """이벤트 묶음을 제자리에서 고친다. 돌려주는 값은 같은 목록이다(순서 · 개수 유지).

    `event_type` 과 `route` 를 함께 바꾼다 — N-04 가 둘을 같은 값으로 쓴다.
    버리지 않고 `ignore` 로 바꾼다: 처리 기록 · 근거 보기에서 그 메시지가 사라지지 않게.
    """
    # 메뉴판에 걸리는 주문이 하나라도 있는 사람 — 그 사람의 "메뉴 이름만 있는 말"은 잡담일 수 있다(보고 7번)
    orderers = {e.get("person") or "" for e in events if e.get("event_type") == "add"
                and any(menu_signal(i, brand_id=brand_id, menu_version=menu_version) != "none"
                        for i in e.get("items") or [])}
    last_add: dict[str, str] = {}          # 사람 -> 그 사람의 마지막 add 메시지 id
    person_menus: dict[str, set[str]] = {}  # 사람 -> 지금까지 주문한 메뉴 id (추가 · 변경 구분용)
    for event in events:
        kind = event.get("event_type")
        person = event.get("person") or ""
        text = event.get("_raw_text") or ""

        if kind == "add":
            if not intake._without_filler(text):
                # "넵" · "ㅇㅇ" · "좋아요" — 맞장구뿐인 말은 주문이 아니다(2026-11-05 2차 보고 5번).
                # 앞뒤 문맥으로 주문이 되는 경우는 참조 표현("저도" · "그걸로")이 있고, 그것은 군말이 아니다
                _to_ignore(event, text)
                continue
            signals = {menu_signal(i, brand_id=brand_id, menu_version=menu_version)
                       for i in event.get("items") or []}
            if "menu" not in signals and (intake.TALLY.search(text) or _PERMISSION.search(text)):
                # "일단 10잔으로 확인되네요" · "혹시 저도 시켜도 되나요?" — 집계 · 허락 묻기다(5차 보고).
                # 메뉴를 말하지 않았으면 주문을 만들지 않는다. 메뉴를 말했으면("저도 라떼 시켜도 되나요") 주문이다
                _to_ignore(event, text)
                continue
            if signals == {"reference"} and person in last_add and not intake.order_pattern(text):
                # "ㅋㅋㅋㅋ 저도 고민되네요" — 이미 주문한 사람의 "저도"는 참조 주문이 아니라 맞장구다(5차 보고).
                # 앞 메뉴를 끌어와 한 잔이 늘었다. 한 잔 더라면 "저도 하나 더요"처럼 주문 문형이 붙는다
                _to_ignore(event, text)
                continue
            if not signals or signals == {"none"}:
                if intake.order_pattern(text) or (person not in orderers and _bare_menu(text)):
                    # 주문 문형은 있는데 메뉴를 말하지 않았다 — 버리지 않고 확인 필요로 올린다(보고 2번)
                    # 메뉴판에 없는 이름만 말했고 그 사람의 다른 주문이 없다("나 얼박사!") — 버리면 그 사람
                    # 주문이 통째로 사라진다. 확인 필요로 올려 담당자가 고르게 한다(2026-11-05 4차 보고 3번)
                    last_add[person] = event["message_id"]
                    continue
                _to_ignore(event, text)
                continue
            if signals == {"option"} and person in last_add:
                _to_update(event, last_add[person])
                continue
            if person in last_add and _LOOKBACK.search(text) and _changes_spec(event):
                # 앞 주문을 되짚으며 사양을 더하거나 바꾸는 말 — 새 잔을 만들지 않는다(보고 2번)
                _to_update(event, last_add[person], kind="lookback_update")
                continue
            last_add[person] = event["message_id"]
            person_menus.setdefault(person, set()).update(
                _menus_of(event, brand_id=brand_id, menu_version=menu_version))
            continue

        if kind == "update" and person not in last_add and _no_menu_signal(event, brand_id, menu_version):
            # "네네 변경 내용까지 확인했습니다~" — 주문한 적 없는 사람이 메뉴도 사양도 말하지 않은 변경이다(5차 보고).
            # 바꿀 대상이 없으면 새 주문으로 받으므로(N-06) 메뉴 없는 확인 질문이 떴다
            _to_ignore(event, text)
            continue

        if kind == "update" and _is_one_more(event, text, person_menus.get(person) or set(),
                                             brand_id=brand_id, menu_version=menu_version):
            # "카페 라떼도 하나 추가요" — 앞 주문을 바꾸는 말이 아니라 **한 잔 더**다(3차 보고).
            # update 로 두면 앞 주문에 덮어써서 잔이 사라지거나 메뉴가 바뀐다
            event["event_type"] = event["route"] = "add"
            event["target_message_id"] = None
            event["consolidated"] = "one_more_cup"
            last_add[person] = event["message_id"]
            person_menus.setdefault(person, set()).update(
                _menus_of(event, brand_id=brand_id, menu_version=menu_version))
            continue

        if kind == "ignore" and person in last_add and _MINE.search(text) \
                and intake._options(text) and not _said_menu(text, brand_id, menu_version):
            # "제 거는 디카페인으로 가능할까요?" — 묻는 문형이라 규칙이 잡담으로 봤지만 자기 주문의 변경이다
            event["items"] = intake.build_items(text, person)
            _to_update(event, last_add[person])
    return events


def points_back(text: str) -> bool:
    """앞 주문을 **가리키려고** 메뉴 이름을 말한 문장인가 (2026-11-05 3차 보고).

    "아까 바닐라라떼 주문했는데 샷 하나 더" 의 메뉴 이름은 바꾸려는 값이 아니라 대상을 가리키는 말이다.
    그대로 반영하면 아이스 바닐라라떼가 따뜻한 바닐라라떼로 바뀐다. 바꿈 말이 함께 있으면 거짓이다.
    """
    return bool(_LOOKBACK.search(text or "")) and not _REPLACE.search(text or "")


def _menus_of(event: dict, *, brand_id: str, menu_version: str) -> set[str]:
    """이 이벤트의 항목들이 가리키는 메뉴 id."""
    found = set()
    for item in event.get("items") or []:
        hit = menu_service.match(brand_id, menu_version,
                                 item.get("match_text") or item.get("menu_text") or "")
        if hit.get("menu_id"):
            found.add(hit["menu_id"])
    return found


def _is_one_more(event: dict, text: str, mine: set[str], *, brand_id: str, menu_version: str) -> bool:
    """이 변경이 실은 **한 잔 더**인가 — 보탬 말이 있고, 지금까지 안 시킨 메뉴를 말한다.

    "아까 카라멜 마키아또 주문했는데 샷 하나 더"는 거짓이다 — 말한 메뉴가 **이미 시킨 그 메뉴**이고,
    더하는 것은 옵션(샷)이기 때문이다. "바꿔 · 말고 · 대신"이 있으면 언제나 변경이다.
    """
    if not _ADD_MORE.search(text) or _REPLACE.search(text):
        return False
    if _LOOKBACK.search(text):
        return False          # "아까 주문했는데 …" — 앞 주문을 가리키는 말이면 언제나 변경이다
    named = _base_names(brand_id, menu_version, menu_service.mentions(brand_id, menu_version, text))
    return bool(named) and not (named & _base_names(brand_id, menu_version, mine))


def _base_names(brand_id: str, menu_version: str, menu_ids) -> set[str]:
    """온도를 뺀 메뉴 이름 — "바닐라라떼"와 "아이스 바닐라라떼"는 **같은 메뉴를 가리키는 말**로 본다.

    되짚는 말에서는 사람들이 온도를 빼고 부른다("아까 바닐라라떼 주문했는데"). id 로만 비교하면
    다른 메뉴로 보여 "한 잔 더"가 되고, 사양 변경이 새 잔이 된다.
    """
    catalog = menu_service.catalog(brand_id, menu_version)["by_id"]
    out = set()
    for menu_id in menu_ids or ():
        name = (catalog.get(menu_id) or {}).get("name") or menu_id
        out.add(name[len("아이스 "):] if name.startswith("아이스 ") else name)
    return out


def _changes_spec(event: dict) -> bool:
    """사양(옵션 · 수량 표현)을 건드리는 말인가 — 되짚는 말이 변경인지 가리는 조건."""
    return any(i.get("options") or i.get("ambiguous_options") for i in event.get("items") or [])


def _said_menu(text: str, brand_id: str, menu_version: str) -> bool:
    hit = menu_service.match(brand_id, menu_version, intake._menu_text(text) or text)
    return bool(hit.get("menu_id") or hit.get("candidates"))


# 메뉴 이름 하나만 덩그러니 말한 문장 — "나 얼박사!" · "저는 얼박사요" (2026-11-05 4차 보고 3번).
# 메뉴판에 없는 이름이라 주문 신호가 없어 보이지만, 단톡방에서 가장 흔한 주문 모양이다
_BARE_MENU = re.compile(r"^(?:나|난|나는|저|저는|전|내\s*꺼?는?|제\s*꺼?는?)?\s*"
                        r"(?P<name>[가-힣A-Za-z]{2,10}?)(?:이요|요)?$")
_NOT_MENU_TAIL = re.compile(r"(?:입니다|이에요|예요|해요|했어|해|다|네|지|죠|까|야|어|아|고|래|음|넵|넹|응|웅|ㅇ|ㅋ|ㅎ)$")


def _bare_menu(text: str) -> bool:
    if "?" in (text or ""):
        return False          # "얼박사?" — 묻는 말이다
    body = re.sub(r"[!~.,…^]+", " ", intake._without_filler(text)).strip()
    hit = _BARE_MENU.match(body)
    if not hit or _NOT_MENU_TAIL.search(hit.group("name")):
        return False
    # 매장 이름만 말한 것("스타벅스!")은 주문이 아니다
    from app.services import brand as brand_service
    try:
        return not brand_service._find(hit.group("name"), brand_service._dictionary())
    except Exception:       # 매장 사전을 못 읽어도 주문을 버리지 않는 쪽으로 둔다
        return True


# 주문해도 되는지 묻는 말 — 주문이 아니라 허락을 구하는 말이다 (5차 보고 · "혹시 저도 시켜도 되나요?")
_PERMISSION = re.compile(r"(?:시켜|주문해|마셔|먹어|해)도\s*(?:되|돼|괜찮)")


def _no_menu_signal(event: dict, brand_id: str, menu_version: str) -> bool:
    signals = {menu_signal(i, brand_id=brand_id, menu_version=menu_version) for i in event.get("items") or []}
    return not signals or signals == {"none"}


def _to_ignore(event: dict, text: str) -> None:
    event["event_type"] = event["route"] = "ignore"
    event["items"] = []
    # 메뉴 이름이 섞인 잡담은 참조 주문("그걸로")의 근거가 된다 — 그 성질은 유지한다
    event["is_reference"] = bool(intake._menu_text(text))
    event["consolidated"] = "not_an_order"


# 이 정리로 만든 update 는 **사양만** 바꾼다 — 메뉴 이름은 가리키려고 말한 것이지 바꾸려는 값이 아니다.
#   "아까 카라멜 마키아또 주문했는데 샷 하나 더" → 메뉴를 (아이스) 카라멜 마키아또로 덮어쓰면 온도가 바뀐다
SPEC_ONLY = ("spec_only_update", "lookback_update")


def _to_update(event: dict, target_message_id: str, *, kind: str = "spec_only_update") -> None:
    event["event_type"] = event["route"] = "update"
    event["target_message_id"] = target_message_id
    event["target_unclear"] = False
    event["consolidated"] = kind
