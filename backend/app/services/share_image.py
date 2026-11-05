"""공유 카드 PNG 생성 (API-033 `format=image` · PRD FR-009 · FR-010 "이미지 저장").

왜 서버가 그리는가 — 공유 내용은 **서버가 만든다**(D-02 3절). 텍스트와 이미지가 같은
`share.build_card()` 결과를 쓰므로 둘이 어긋나지 않는다. 화면이 캔버스로 그리면 같은 규칙이
두 곳에 생기고, 한쪽만 고쳤을 때 조용히 달라진다.

**한글 폰트가 없으면 그리지 않는다.** 폰트 없이 그리면 Pillow 가 예외를 던지지 않고 글자를
두부(□)로 채운 그림을 내놓는다 — 담당자는 깨진 이미지를 단톡방에 올리게 된다. 그래서
`available()` 로 먼저 묻고, 없으면 기존 안내("이미지는 아직 만들지 못했어요")로 되돌아간다.
배포 이미지에는 Dockerfile 이 한글 폰트를 넣는다.

관리 링크 · 토큰 · QR · 브랜드 로고를 넣지 않는다 (NFR-003 · P-06 공유 카드).
"""

import functools
import glob
import io
import os

from PIL import Image, ImageDraw, ImageFont

# --- 크기 · 색 — **공유하기 미리보기(화면)와 같은 디자인**이다 (2026-11-05 사용자 요청) ----------
# 미리보기: frontend/moa/components.share_card_html + tokens.py `.moa-share-*`. 그 CSS 값(px)을 SCALE 배로 그린다.
# 한쪽을 고치면 다른 쪽도 고친다 — 담당자는 미리보기를 보고 저장하므로 둘이 다르면 "본 것과 받은 것"이 어긋난다.
SCALE = 2
CARD_W = 480                  # 미리보기 카드 폭(공유 대화상자 540px - 안쪽 여백)
WIDTH = CARD_W * SCALE
RADIUS = 14 * SCALE

GREEN_DEEP = "#1E4D3A"        # --moa-green-deep  머리 띠
GREEN_MINT = "#A9D3BE"        # --moa-green-mint  머리 부제
SUNKEN = "#F8F8F7"            # --moa-sunken      본문 바탕
LINE = "#EAEAE7"              # --moa-line        테두리 · 합계 위 선
INK = "#18181B"               # --moa-ink
MUTED = "#6A6A70"             # --moa-muted       이름 · 요청
MUTED_2 = "#8B8B91"           # --moa-muted-2     금액 고지
MUTED_3 = "#97979D"           # --moa-muted-3     꼬리말
WHITE = "#FFFFFF"
HEAD_DOTS = ("#3B2A20", "#E9D9B8", "#A9D3BE")

# 메뉴 점 색 — frontend/moa/icons.py `_SWATCH` · `swatch_color` 와 같은 규칙 · 같은 값
_SWATCH = [
    ("유자", "#E8D27A"), ("민트", "#A9D3BE"), ("자바", "#6B4A36"), ("바닐라", "#E9D9B8"),
    ("라떼", "#CDB394"), ("모카", "#6B4A36"), ("카라멜", "#D9B98A"), ("아메리카노", "#3B2A20"),
    ("콜드 브루", "#3B2A20"), ("에스프레소", "#3B2A20"), ("티", "#E8D27A"), ("에이드", "#E8D27A"),
]
SWATCH_UNKNOWN, SWATCH_DEFAULT = "#ECECE9", "#CDB394"


def swatch_color(menu_name: str | None) -> str:
    if not menu_name:
        return SWATCH_UNKNOWN
    return next((color for word, color in _SWATCH if word in menu_name), SWATCH_DEFAULT)


def _px(value: float) -> int:
    return int(round(value * SCALE))


# 찾아볼 한글 폰트 — (보통, 굵게). 앞에서부터 처음 있는 짝을 쓴다.
# 번들 폰트가 없는 개발 PC 에서도 실습이 되도록 OS 기본 한글 폰트를 함께 본다.
_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
     "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.ttf"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
     "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf"),
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc",
     "/System/Library/Fonts/AppleSDGothicNeo.ttc"),
)

# 저장소에 폰트를 함께 둘 때 보는 자리 (라이선스를 확인한 폰트만 넣는다)
_BUNDLE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "fonts")


def _bundled() -> tuple[str, str] | None:
    files = sorted(glob.glob(os.path.join(_BUNDLE_DIR, "*.ttf"))
                   + glob.glob(os.path.join(_BUNDLE_DIR, "*.ttc")))
    if not files:
        return None
    bold = next((f for f in files if "bold" in os.path.basename(f).lower()), files[0])
    regular = next((f for f in files if f != bold), files[0])
    return regular, bold


@functools.lru_cache(maxsize=1)
def font_pair() -> tuple[str, str] | None:
    """쓸 수 있는 (보통, 굵게) 폰트 경로. 없으면 None.

    환경변수 `SHARE_IMAGE_FONT` 가 있으면 그것만 본다 — 배포에서 폰트를 고정할 수단이다.
    """
    override = os.getenv("SHARE_IMAGE_FONT", "").strip()
    if override:
        if not os.path.exists(override):
            return None
        bold = os.getenv("SHARE_IMAGE_FONT_BOLD", "").strip()
        return override, (bold if bold and os.path.exists(bold) else override)
    found = _bundled()
    if found:
        return found
    for regular, bold in _FONT_CANDIDATES:
        if os.path.exists(regular):
            return regular, (bold if os.path.exists(bold) else regular)
    return None


def available() -> bool:
    """이미지를 만들 수 있는가 — 한글 폰트가 있는지로 판정한다."""
    return font_pair() is not None


def _load(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    pair = font_pair()
    if pair is None:          # available() 를 먼저 묻는다 — 여기 오면 호출 순서가 틀렸다
        raise RuntimeError("한글 폰트가 없다")
    return ImageFont.truetype(pair[1] if bold else pair[0], size)


def _fit(draw, word: str, font, limit: int) -> list[str]:
    """한 낱말이 한 줄보다 길면 글자 단위로 쪼갠다 (긴 기타 요청 문구).

    한글은 공백 없이도 길어지므로 낱말 단위 줄바꿈만으로는 카드 밖으로 넘친다.
    """
    if draw.textlength(word, font=font) <= limit:
        return [word]
    out, current = [], ""
    for char in word:
        if current and draw.textlength(current + char, font=font) > limit:
            out.append(current)
            current = char
        else:
            current += char
    if current:
        out.append(current)
    return out


def _wrap(draw, text: str, font, limit: int) -> list[str]:
    """글자 폭을 재서 줄을 나눈다."""
    if not text:
        return []
    lines: list[str] = []
    for chunk in text.split("\n"):
        current = ""
        for word in chunk.split(" "):
            for piece in _fit(draw, word, font, limit):
                trial = f"{current} {piece}".strip()
                if current and draw.textlength(trial, font=font) > limit:
                    lines.append(current)
                    current = piece
                else:
                    current = trial
        lines.append(current)
    return lines


def render(card: dict) -> bytes:
    """공유 카드 1종을 PNG 바이트로 — 미리보기와 같은 배치. 세로 길이는 내용에 맞춰 늘어난다.

    배치(CSS px · SCALE 배)
      머리  초록 띠 · 안쪽 18/22 · 제목 16px 굵게(흰색) · 부제 12px(민트) · 오른쪽 겹친 점 3개(16px)
      본문  연회색 바탕 · 안쪽 14/22 · 메뉴 줄(위아래 6) = [색 점 8px] 메뉴 14px 굵게 ··· ×수량
            이름 12.5px · 요청 12px · 합계 위 선(위 여백 10 · 안쪽 12) · 고지 11.5px · 꼬리말 11px(위 12)
    """
    fonts = {
        "head": _load(_px(16), bold=True), "sub": _load(_px(12)),
        "menu": _load(_px(14), bold=True), "people": _load(_px(12.5)), "req": _load(_px(12), bold=True),
        "total": _load(_px(14), bold=True), "note": _load(_px(11.5)), "foot": _load(_px(11)),
    }
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    left, right = _px(22), WIDTH - _px(22)
    text_left = left + _px(8 + 8)                 # 색 점 8px + 간격 8px
    qty_width = _px(48)

    blocks = []
    for line in card.get("lines", []):
        menu = _wrap(probe, line.get("menu_text") or "", fonts["menu"], right - text_left - qty_width)
        people = _wrap(probe, " · ".join(line.get("people") or []), fonts["people"], right - left)
        request = (_wrap(probe, f'요청: {line["custom_request"]}', fonts["req"], right - left)
                   if line.get("custom_request") else [])
        blocks.append((line.get("menu_text"), menu, people, request, f'×{line.get("quantity", 0)}'))
    note_lines = _wrap(probe, card.get("notice") or "", fonts["note"], right - left)
    foot_lines = _wrap(probe, card.get("foot") or "", fonts["foot"], right - left)

    # 1) 높이 — 줄 높이(line-height) 단위로 쌓는다
    head_h = _px(18) + _px(22) + _px(26) + _px(18)    # 부제 줄은 브라우저에서 26px 로 잡힌다(실측)
    body_h = _px(14)
    for _, menu, people, request, _ in blocks:
        body_h += _px(6) + len(menu) * _px(20) + len(people) * _px(18) + len(request) * _px(18) + _px(6)
    body_h += _px(10) + _px(12) + _px(20) + len(note_lines) * _px(16)
    body_h += _px(12) + len(foot_lines) * _px(16) + _px(14)
    height = head_h + body_h

    # 2) 그린다 — 둥근 카드(테두리 1px) 안에 머리 띠와 본문
    image = Image.new("RGB", (WIDTH, height), WHITE)
    draw = ImageDraw.Draw(image)
    border = max(1, SCALE // 2)
    draw.rounded_rectangle((0, 0, WIDTH - 1, height - 1), radius=RADIUS, fill=SUNKEN, outline=LINE, width=border)
    draw.rounded_rectangle((border, border, WIDTH - 1 - border, head_h + RADIUS), radius=RADIUS - border,
                           fill=GREEN_DEEP)
    draw.rectangle((border, head_h, WIDTH - 1 - border, head_h + RADIUS), fill=SUNKEN)

    y = _px(18)
    draw.text((left, y + _px(11)), card.get("head") or "", font=fonts["head"], fill=WHITE, anchor="lm")
    y += _px(22)
    draw.text((left, y + _px(13)), card.get("sub") or "", font=fonts["sub"], fill=GREEN_MINT, anchor="lm")
    # 겹친 점 3개 — 지름 16 · 테두리 1.5(머리 띠 색) · 왼쪽으로 5 겹친다
    dot, ring, overlap = _px(16), _px(1.5), _px(5)
    cy = head_h // 2
    x = right - dot * 3 + overlap * 2
    for color in HEAD_DOTS:
        draw.ellipse((x, cy - dot // 2, x + dot, cy + dot // 2), fill=color, outline=GREEN_DEEP, width=ring)
        x += dot - overlap

    y = head_h + _px(14)
    for name, menu, people, request, qty in blocks:
        y += _px(6)
        mid = y + _px(10)
        draw.ellipse((left, mid - _px(4), left + _px(8), mid + _px(4)), fill=swatch_color(name))
        for index, text in enumerate(menu):
            draw.text((text_left, y + _px(10)), text, font=fonts["menu"], fill=INK, anchor="lm")
            if index == 0:
                draw.text((right, y + _px(10)), qty, font=fonts["menu"], fill=INK, anchor="rm")
            y += _px(20)
        for text in people:
            draw.text((left, y + _px(9)), text, font=fonts["people"], fill=MUTED, anchor="lm")
            y += _px(18)
        for text in request:
            draw.text((left, y + _px(9)), text, font=fonts["req"], fill=INK, anchor="lm")
            y += _px(18)
        y += _px(6)

    y += _px(10)
    draw.line((left, y, right, y), fill=LINE, width=border)
    y += _px(12)
    label, _, value = (card.get("total_text") or "").partition(" ")
    draw.text((left, y + _px(10)), label, font=fonts["total"], fill=INK, anchor="lm")
    draw.text((right, y + _px(10)), value, font=fonts["total"], fill=INK, anchor="rm")
    y += _px(20)
    for text in note_lines:
        draw.text((left, y + _px(8)), text, font=fonts["note"], fill=MUTED_2, anchor="lm")
        y += _px(16)
    y += _px(12)
    for text in foot_lines:
        draw.text((left, y + _px(8)), text, font=fonts["foot"], fill=MUTED_3, anchor="lm")
        y += _px(16)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
