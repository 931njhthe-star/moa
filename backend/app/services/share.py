"""공유 내용 생성 — 내용은 서버가 만든다. 화면이 조립하지 않는다 (API-033).

공유 카드 이미지(PNG)는 생성 후 응답으로만 보낸다 — 파일 · DB 에 두지 않는다.
보관할 이유가 없다. 같은 버전이면 다시 만든다 (D-07 2.4).

개인별 금액을 넣지 않는다 (D-07 D-5).
"""

import datetime

from app.services import share_image
from app.services.chat_parse import UNNAMED

FOOT = "Moa · 비공식 시연 서비스"
NOTICE = "참고용 금액이에요. 실제 결제 금액과 다를 수 있어요"

BRAND_HEAD = {"starbucks": "스타벅스", "generic": "일반 카페"}

# 폰트가 없어 그릴 수 없을 때만 쓰는 문구 — 이미지 기능 자체는 구현돼 있다
IMAGE_UNAVAILABLE_TEXT = "이미지는 아직 만들지 못했어요. 텍스트 복사로 공유해 주세요"


def _spec_text(group: dict) -> str:
    """메뉴명 뒤에 붙는 사양 — 옵션 칩을 한 줄로 합친다."""
    parts = []
    for option in group.get("options") or []:
        value = option.get("value")
        if not value:
            continue
        label = option.get("label")
        # 사이즈는 값만, 나머지는 "얼음 적게"처럼 라벨을 붙인다
        parts.append(value if label == "사이즈" else f"{label} {value}")
    return " ".join(parts)


def build_card(sheet: dict, *, now: datetime.datetime | None = None, show_names: bool = True) -> dict:
    """공유 카드 구조. 화면과 이미지 생성이 같은 값을 쓴다.

    show_names=False 면 묶음마다의 이름 줄을 뺀다 — 메뉴 · 수량 · 요청 · 합계만 남는다(2026-11-04 · 사용자 요청 #8).
    머리줄의 "N명"은 인원 수라 이름이 아니므로 남긴다.

    이름이 없는 대화(참여자가 `이름 없음` 하나뿐)는 **요청 없이도** 이름 줄을 뺀다 —
    "이름 없음 · 이름 없음"을 단톡방에 올리는 것은 이름 표시가 아니다(2026-11-05 사용자 결정 1번).
    """
    now = now or _now_kst()
    if show_names and not _has_real_names(sheet):
        show_names = False
    brand_head = BRAND_HEAD.get(sheet["brand"]["id"], "카페")
    summary = sheet["summary"]
    totals = sheet["totals"]

    lines = []
    for group in sheet["groups"]:
        spec = _spec_text(group)
        lines.append({
            "menu_text": f'{group["menu_text"]} {spec}'.strip(),
            "quantity": group["quantity"],
            "people": group["people"] if show_names else [],
            "custom_request": group["custom_request"],
        })

    total_text = (f'합계 {totals["cups"]}잔'
                  if totals["estimated_total"] is None
                  else f'합계 {totals["cups"]}잔 · 예상 {totals["estimated_total"]:,}원')

    return {
        "head": f"커피 주문 · {brand_head}",
        "sub": f'{now:%-m/%-d %H:%M} 기준 · {summary["people"]}명 · {summary["cups"]}잔'
               if _supports_dash() else
               f'{now.month}/{now.day} {now:%H:%M} 기준 · {summary["people"]}명 · {summary["cups"]}잔',
        "lines": lines,
        "total_text": total_text,
        "notice": NOTICE,
        "foot": FOOT,
    }


def _has_real_names(sheet: dict) -> bool:
    """이름이라고 할 만한 주문자가 하나라도 있는가 — `이름 없음`은 이름이 아니다."""
    return any(name and name != UNNAMED
               for group in sheet.get("groups") or [] for name in group.get("people") or [])


# 공유 카드 · 파일 이름의 "기준 시각"은 한국 시간이다. 컨테이너 시계는 UTC 라 그대로 쓰면 오전 11시 주문이
# "02:07 기준"으로 나갔다(2026-11-04 전체 흐름 확인). 한국은 서머타임이 없어 고정 +9 로 충분하다 — tzdata 가 없는
# slim 이미지에서도 돈다
KST = datetime.timezone(datetime.timedelta(hours=9))


def _now_kst() -> datetime.datetime:
    return datetime.datetime.now(KST)


def _supports_dash() -> bool:
    """`%-m` 은 플랫폼에 따라 없다 — 윈도우에서 터지는 자리라 미리 가른다."""
    try:
        datetime.datetime.now().strftime("%-m")
        return True
    except ValueError:
        return False


def render_text(card: dict) -> str:
    """복사용 텍스트. 공유 카드와 같은 내용이어야 한다."""
    out = [card["head"], card["sub"], ""]
    for line in card["lines"]:
        out.append(f'{line["menu_text"]}  x{line["quantity"]}')
        if line["people"]:
            out.append("  " + " · ".join(line["people"]))
        if line["custom_request"]:
            out.append(f'  요청: {line["custom_request"]}')
    out += ["", card["total_text"], card["notice"], card["foot"]]
    return "\n".join(out)


def image_filename(brand_id: str, *, now: datetime.datetime | None = None) -> str:
    now = now or _now_kst()
    return f'주문_{BRAND_HEAD.get(brand_id, "카페")}_{now:%Y%m%d_%H%M}.png'


def view(sheet: dict, *, fmt: str = "text", now: datetime.datetime | None = None,
         show_names: bool = True) -> dict:
    """API-033 — 공유 내용 생성 응답.

    `image_available` 은 **한글 폰트가 있는지**로 정한다(share_image.available()). 폰트가 없는
    환경에서 참으로 내보내면 글자가 두부(□)로 찍힌 그림이 단톡방에 올라간다 — 그때는 거짓과
    대체 문구를 함께 주고 화면이 [텍스트 복사]만 쓰게 한다.
    """
    card = build_card(sheet, now=now, show_names=show_names)
    shown = show_names and _has_real_names(sheet)
    return {
        "format": fmt,
        "show_names": shown,
        "content": render_text(card),
        "card": card,
        "image_filename": image_filename(sheet["brand"]["id"], now=now),
        "image_available": share_image.available(),
        "image_unavailable_text": IMAGE_UNAVAILABLE_TEXT,
    }


def render_image(sheet: dict, *, now: datetime.datetime | None = None, show_names: bool = True) -> bytes:
    """공유 카드 PNG. 텍스트와 **같은 카드 구조**에서 그린다."""
    return share_image.render(build_card(sheet, now=now, show_names=show_names))


def content_hash(content: str) -> str:
    """공유한 내용과 같은지 판정하는 값 (share_history.content_hash)."""
    from app import ids

    return ids.content_hash(content)
