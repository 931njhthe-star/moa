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

# --- 크기 · 색 (D-01 디자인스타일가이드 팔레트) -------------------------------
WIDTH = 720
PAD = 28                      # 카드 바깥 여백
INNER = 32                    # 카드 안쪽 여백
RADIUS = 28

PAGE_BG = "#F7F3EC"
CARD_BG = "#FFFFFF"
INK = "#3B2A20"               # 본문
MUTED = "#8A7A6D"             # 보조
FAINT = "#B3A596"             # 꼬리말
RULE = "#EDE4D8"              # 구분선
DOT = "#CDB394"               # 메뉴 점

SIZE_HEAD, SIZE_SUB = 30, 21
SIZE_MENU, SIZE_PEOPLE, SIZE_REQ = 26, 21, 19
SIZE_TOTAL, SIZE_NOTE, SIZE_FOOT = 27, 19, 19

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
    """공유 카드 1종을 PNG 바이트로. 세로 길이는 내용에 맞춰 늘어난다."""
    fonts = {
        "head": _load(SIZE_HEAD, bold=True), "sub": _load(SIZE_SUB),
        "menu": _load(SIZE_MENU, bold=True),
        "people": _load(SIZE_PEOPLE), "req": _load(SIZE_REQ),
        "total": _load(SIZE_TOTAL, bold=True), "note": _load(SIZE_NOTE),
        "foot": _load(SIZE_FOOT),
    }
    # 1) 자리 계산을 먼저 한다 — 높이를 알아야 캔버스를 만들 수 있다
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    text_left = PAD + INNER + 26                 # 메뉴 점 자리만큼 들여쓴다
    right = WIDTH - PAD - INNER
    text_width = right - text_left
    qty_width = 72

    blocks = []
    for line in card.get("lines", []):
        menu = _wrap(probe, line.get("menu_text") or "", fonts["menu"], text_width - qty_width)
        people = _wrap(probe, " · ".join(line.get("people") or []), fonts["people"], text_width)
        request = (_wrap(probe, f'요청: {line["custom_request"]}', fonts["req"], text_width)
                   if line.get("custom_request") else [])
        blocks.append((menu, people, request, f'×{line.get("quantity", 0)}'))

    note_lines = _wrap(probe, card.get("notice") or "", fonts["note"], text_width)

    height = PAD + INNER + SIZE_HEAD + 12 + SIZE_SUB + 24
    for menu, people, request, _ in blocks:
        height += 18 + len(menu) * (SIZE_MENU + 8) + len(people) * (SIZE_PEOPLE + 6) \
            + len(request) * (SIZE_REQ + 5)
    height += 14 + SIZE_TOTAL + 10 + len(note_lines) * (SIZE_NOTE + 5)
    height += 18 + SIZE_FOOT + INNER + PAD

    # 2) 그린다
    image = Image.new("RGB", (WIDTH, int(height)), PAGE_BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((PAD, PAD, WIDTH - PAD, height - PAD), radius=RADIUS, fill=CARD_BG)

    y = PAD + INNER
    draw.text((PAD + INNER, y), card.get("head") or "", font=fonts["head"], fill=INK)
    y += SIZE_HEAD + 12
    draw.text((PAD + INNER, y), card.get("sub") or "", font=fonts["sub"], fill=MUTED)
    y += SIZE_SUB + 24

    for menu, people, request, qty in blocks:
        draw.line((PAD + INNER, y, right, y), fill=RULE, width=1)
        y += 18
        dot_y = y + SIZE_MENU // 2 - 6
        draw.ellipse((PAD + INNER, dot_y, PAD + INNER + 12, dot_y + 12), fill=DOT)
        for index, text in enumerate(menu):
            draw.text((text_left, y), text, font=fonts["menu"], fill=INK)
            if index == 0:
                draw.text((right, y), qty, font=fonts["menu"], fill=INK, anchor="ra")
            y += SIZE_MENU + 8
        for text in people:
            draw.text((text_left, y), text, font=fonts["people"], fill=MUTED)
            y += SIZE_PEOPLE + 6
        for text in request:
            draw.text((text_left, y), text, font=fonts["req"], fill=MUTED)
            y += SIZE_REQ + 5

    draw.line((PAD + INNER, y, right, y), fill=RULE, width=1)
    y += 14
    label, _, value = (card.get("total_text") or "").partition(" ")
    draw.text((PAD + INNER, y), label, font=fonts["total"], fill=INK)
    draw.text((right, y), value, font=fonts["total"], fill=INK, anchor="ra")
    y += SIZE_TOTAL + 10
    for text in note_lines:
        draw.text((PAD + INNER, y), text, font=fonts["note"], fill=MUTED)
        y += SIZE_NOTE + 5
    y += 18
    draw.text((PAD + INNER, y), card.get("foot") or "", font=fonts["foot"], fill=FAINT)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
