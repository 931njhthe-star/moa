# 아이콘 — 정본 시안 `Moa_전체화면.svg`가 쓰는 선 아이콘을 인라인 SVG로 둔다
#
# 외부 아이콘 글꼴 · 이미지 파일을 쓰지 않는다. 색은 `currentColor`라 놓인 자리의 글자색을 따른다.
# 메뉴 색 견본 · 로고처럼 시안 고유의 그림도 여기에 모은다.

import base64

_STROKE = ('xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           'stroke="currentColor" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"')

_PATHS = {
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "alert": ('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
              '<path d="M12 9v4"/><path d="M12 17h.01"/>'),
    "check-circle": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "file": ('<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
             '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'),
    "users": ('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
              '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
    "coffee": ('<path d="M10 2v2"/><path d="M14 2v2"/><path d="M16 8a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7'
               'a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1"/><path d="M6 2v2"/>'),
    "message": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5 5.5 5.5 0 0 1-5.5 5.5H11"/>',
    "refresh": ('<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
                '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>'),
    "logout": ('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/>'
               '<path d="M21 12H9"/>'),
    "store": ('<path d="m2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7"/>'
              '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="M15 22v-4a2 2 0 0 0-2-2h-2'
              'a2 2 0 0 0-2 2v4"/><path d="M2 7h20"/><path d="M22 7v3a2 2 0 0 1-2 2a2.7 2.7 0 0 1-1.59-.63'
              '.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 16 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 12 12'
              'a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 8 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0'
              'A2.7 2.7 0 0 1 4 12a2 2 0 0 1-2-2V7"/>'),
}


def _data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def icon(name: str, size: int = 16, *, width: float = 1.75, cls: str = "moa-ico") -> str:
    """선 아이콘 하나. 장식이라 스크린리더에서 숨긴다 — 뜻은 옆 글자가 전한다(U-8).

    `st.html`은 `<svg>` 태그를 지운다. 그래서 그림을 CSS 마스크로 얹고 바탕을 `currentColor`로
    칠한다 — 놓인 자리의 글자색을 그대로 따른다.
    """
    svg = (f'<svg {_STROKE.format(w=width).replace("currentColor", "black")} '
           f'width="{size}" height="{size}">{_PATHS[name]}</svg>')
    uri = _data_uri(svg)
    return (f'<span class="{cls}" aria-hidden="true" style="width:{size}px;height:{size}px;'
            f'background:currentColor;-webkit-mask:url({uri}) center/contain no-repeat;'
            f'mask:url({uri}) center/contain no-repeat"></span>')


def _img(svg: str, size: int) -> str:
    return (f'<img src="{_data_uri(svg)}" width="{size}" height="{size}" alt="" '
            f'style="display:block" aria-hidden="true">')


def logo(size: int = 24) -> str:
    """Moa 로고 — 작은 원 두 개 + 큰 원 하나 (시안 헤더 · 말풍선 아바타)."""
    return _img('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72">'
                '<circle cx="20" cy="20" r="9" fill="#BFD8C9"/><circle cx="52" cy="20" r="9" fill="#7FB197"/>'
                '<circle cx="36" cy="50" r="18" fill="#2E7154"/></svg>', size)


def cup_badge() -> str:
    """SCR-001 배너 오른쪽 그림 — 점 세 개 · 선 · 컵 원판 (시안 케이스 01)."""
    heart = _img('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#FFFFFF" '
                 'd="M12 21s-7.5-4.6-9.6-9.2C.9 7.6 3.4 4 7 4c2 0 3.6 1 5 2.7C13.4 5 15 4 17 4c3.6 0 '
                 '6.1 3.6 4.6 7.8C19.5 16.4 12 21 12 21z"/></svg>', 20)
    return ('<div class="moa-hero-art" aria-hidden="true">'
            '<span class="moa-hero-dot" style="background:#E9D9B8"></span>'
            '<span class="moa-hero-dot" style="background:#CDB394"></span>'
            '<span class="moa-hero-dot" style="background:#A9D3BE"></span>'
            '<span class="moa-hero-line"></span>'
            f'<span class="moa-hero-cup"><span class="moa-hero-cup-in">{heart}</span></span></div>')


# --- 메뉴 색 견본 --------------------------------------------------------------
# 시안은 메뉴마다 음료 색을 띤 정사각 견본(가운데 흰 고리)을 둔다. **장식일 뿐 판정이 아니다** —
# 메뉴 이름에 든 낱말로 색만 고르고, 모르는 메뉴 · 확인 필요 항목은 회색이다.
_SWATCH = [
    ("유자", "#E8D27A"), ("민트", "#A9D3BE"), ("자바", "#6B4A36"), ("바닐라", "#E9D9B8"),
    ("라떼", "#CDB394"), ("모카", "#6B4A36"), ("카라멜", "#D9B98A"), ("아메리카노", "#3B2A20"),
    ("콜드 브루", "#3B2A20"), ("에스프레소", "#3B2A20"), ("티", "#E8D27A"), ("에이드", "#E8D27A"),
]
SWATCH_UNKNOWN = "#ECECE9"


def swatch_color(menu_name: str | None, *, unknown: bool = False) -> str:
    if unknown or not menu_name:
        return SWATCH_UNKNOWN
    for word, color in _SWATCH:
        if word in menu_name:
            return color
    return "#CDB394"


def swatch(menu_name: str | None, size: int = 36, *, unknown: bool = False) -> str:
    color = swatch_color(menu_name, unknown=unknown)
    return (f'<span class="moa-swatch" style="background:{color};width:{size}px;height:{size}px;'
            f'border-radius:{max(8, size // 3)}px"><span class="moa-swatch-ring" '
            f'style="width:{size // 3}px;height:{size // 3}px"></span></span>')
