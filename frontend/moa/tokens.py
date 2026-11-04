# 화면 토큰과 컴포넌트 CSS — 출처는 정본 시안 `Moa_전체화면.svg`(23케이스)다
#
# 이 파일이 색 · 글자 · 간격 · 반경 · 치수의 유일한 출처다. 값은 시안에서 실측했다.
# 다른 파일에서 색 값(#...)이나 px 크기를 직접 쓰지 않는다 — 예외는 `moa/icons.py`의
# 그림(로고 · 메뉴 색 견본)뿐이다.
#
# Streamlit 컨테이너에는 클래스를 직접 붙일 수 없다. 대신 `key=`를 주면 `st-key-{key}` 클래스가
# 생기므로(1.62) 화면 코드는 정해진 키 이름을 쓰고, 여기서 그 키로 고른다.
#   moa_*    한 화면에 하나뿐인 영역 (헤더 · 하단 바 · 패널 …)
#   card_*   누르면 열리는 카드 — 안의 `hit_*` 버튼이 카드 전체를 덮는다
#   hit_*    카드 전체를 덮는 투명 버튼
#   link_*   글자 링크처럼 보이는 버튼
import streamlit as st

ROOT_CSS = """
:root {
  /* 바탕 · 면 · 선 */
  --moa-bg: #FAFAF9;
  --moa-surface: #FFFFFF;
  --moa-sunken: #F8F8F7;
  --moa-chip: #F2F2F0;
  --moa-tab: #F0F0EE;
  --moa-skeleton: #F4F4F2;
  --moa-line: #EAEAE7;
  --moa-line-2: #E4E4E1;
  --moa-line-3: #DADAD6;
  --moa-line-soft: #EFEFEC;
  --moa-line-faint: #F3F3F1;
  --moa-bar-line: #EEEEEB;

  /* 글자 */
  --moa-ink: #18181B;
  --moa-ink-2: #27272A;
  --moa-ink-3: #38383C;
  --moa-ink-4: #46464B;
  --moa-ink-5: #5A5A60;
  --moa-muted: #6A6A70;
  --moa-muted-2: #8B8B91;
  --moa-muted-3: #97979D;
  --moa-faint: #A1A1A7;
  --moa-slash: #D4D4D0;

  /* 초록 (주 색) */
  --moa-green: #2E7154;
  --moa-green-hover: #285F47;
  --moa-green-deep: #1E4D3A;
  --moa-green-text: #24573F;
  --moa-green-ink: #1F3D2E;
  --moa-green-label: #1F5E40;
  --moa-green-soft: #EAF3EE;
  --moa-green-pill: #EEF5F1;
  --moa-green-pill-line: #D3E6DA;
  --moa-green-line: #BFD8C9;
  --moa-green-mint: #A9D3BE;
  --moa-green-tint: #E6EFE9;
  --moa-green-tint-label: #3F5F4E;
  --moa-green-tint-ink: #173D2D;
  --moa-green-other: #F4F8F5;
  --moa-status-info-bg: #F1F5F2;
  --moa-status-info-text: #2F4A3B;

  /* 주황 (확인 필요 · 주의) */
  --moa-amber-bg: #FCF4E3;
  --moa-amber-text: #8A5A12;
  --moa-amber-status: #7A5110;
  --moa-amber-card: #FFFCF4;
  --moa-amber-line: #F1DFB8;
  --moa-amber-strong: #C98A1E;
  --moa-changed: #FFF8E6;

  /* 빨강 (멈춤 · 빼기) */
  --moa-red-bg: #FDEEEC;
  --moa-red-soft: #FDF3F2;
  --moa-red-text: #A8322D;
  --moa-red-dot: #D14A43;
  --moa-red-action: #B23A35;
  --moa-red-line: #E0928C;
  --moa-red-input: #FFF8F7;

  /* 비활성 · 토스트 */
  --moa-disabled-bg: #EAEAE7;
  --moa-disabled-text: #A8A8AD;
  --moa-toast: #1F1E1C;

  /* 글꼴 */
  --moa-font: "Pretendard", "Pretendard Variable", -apple-system, BlinkMacSystemFont,
              "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
  --moa-mono: Menlo, ui-monospace, "SF Mono", Consolas, monospace;

  /* 치수 (시안 실측) */
  --moa-frame: 1120px;
  --moa-gutter: 25px;
  --moa-header: 56px;
  --moa-bar: 67px;
  --moa-foot: 44px;
  --moa-column: 760px;
  --moa-panel: 400px;
  --moa-side: 360px;
  /* SCR-002 두 열 높이 — 헤더 · 상태 줄 · 안내 줄 · 하단 바 · 고지 줄을 뺀 나머지 */
  --moa-work-height: calc(100vh - 148px - var(--moa-bar) - var(--moa-foot) - 16px);

  --moa-ease: cubic-bezier(0.2, 0, 0, 1);
}
"""

COMPONENT_CSS = """
/* ===== 바탕 ===== */
html, body, .stApp, [class*="st-"], button, input, textarea, select { font-family: var(--moa-font); }
[data-testid="stIconMaterial"], span[class*="material-symbols"] {
  font-family: "Material Symbols Rounded" !important;
}
.stApp, body { background: var(--moa-bg); color: var(--moa-ink); }
header[data-testid="stHeader"] { display: none; }
#MainMenu, footer { visibility: hidden; }
.block-container {
  max-width: var(--moa-frame);
  padding: 0 var(--moa-gutter) calc(var(--moa-foot) + 24px);
}
.block-container:has(.st-key-moa_bar) { padding-bottom: calc(var(--moa-bar) + var(--moa-foot) + 24px); }
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] { gap: 0; }
[data-testid="stVerticalBlock"] { gap: 12px; }
.stMarkdown p { margin: 0; }
[data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.moa-num { font-variant-numeric: tabular-nums; }
.moa-ico { display: inline-block; vertical-align: -3px; flex: none; }
.moa-mono { font-family: var(--moa-mono); }

/* ===== 버튼 공통 ===== */
.stButton button, .stFormSubmitButton button, .stDownloadButton button, .stPopover button {
  min-height: 38px; padding: 0 14px;
  border-radius: 10px; border: 1px solid var(--moa-line-2);
  background: var(--moa-surface); color: var(--moa-ink-3);
  font: 600 14px/20px var(--moa-font);
  box-shadow: none;
  transition: background 150ms var(--moa-ease), border-color 150ms var(--moa-ease);
}
.stButton button p, .stFormSubmitButton button p, .stDownloadButton button p { font: inherit; }
.stButton button:hover, .stFormSubmitButton button:hover { border-color: var(--moa-line-3); color: var(--moa-ink); background: var(--moa-surface); }
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"],
.stButton button[data-testid="stBaseButton-primary"],
.stFormSubmitButton button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: var(--moa-green); border-color: var(--moa-green); color: #FFFFFF; font-weight: 700;
}
.stButton button[kind="primary"]:hover,
.stFormSubmitButton button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: var(--moa-green-hover); border-color: var(--moa-green-hover); color: #FFFFFF;
}
.stButton button:disabled, .stButton button[kind="primary"]:disabled,
.stButton button:disabled:hover {
  background: var(--moa-disabled-bg); border-color: var(--moa-disabled-bg);
  color: var(--moa-disabled-text); cursor: not-allowed;
}
.stButton button:focus-visible { outline: 2px solid var(--moa-green); outline-offset: 2px; }
/* 글자 링크 버튼 — 테두리 · 배경 없음 */
[class*="st-key-link_"] .stButton button, [class*="st-key-link_"] button {
  min-height: 0; padding: 0; border: none; background: transparent;
  color: var(--moa-green); font: 600 13px/20px var(--moa-font);
}
[class*="st-key-link_"] button:hover { background: transparent; color: var(--moa-green-hover); text-decoration: underline; }
[class*="st-key-link_mute"] .stButton button { color: var(--moa-muted); font-weight: 500; }
[class*="st-key-link_red"] .stButton button { color: var(--moa-red-action); }

/* 누르면 열리는 카드 — 투명 버튼이 카드 전체를 덮는다 */
[class*="st-key-card_"] { position: relative; }
[class*="st-key-hit_"] { position: absolute !important; inset: 0; z-index: 3; margin: 0 !important; }
[class*="st-key-hit_"] .stButton, [class*="st-key-hit_"] button {
  width: 100%; height: 100%; min-height: 0; opacity: 0; cursor: pointer;
}

/* ===== 입력 ===== */
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"] {
  border-radius: 10px !important; border-color: var(--moa-line-2) !important;
  background: var(--moa-surface) !important;
}
[data-testid="stTextInputRootElement"]:focus-within, [data-testid="stTextAreaRootElement"]:focus-within { border-color: var(--moa-green) !important; }
.stTextInput input, .stTextArea textarea {
  font: 400 14px/22px var(--moa-font); color: var(--moa-ink-2); background: transparent;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder { color: var(--moa-faint); opacity: 1; }
[data-testid="InputInstructions"] { display: none; }

/* 옵션 버튼 묶음 (st.pills) — 따로 떨어진 작은 버튼, 고른 것은 초록 */
.stButtonGroup [role="radiogroup"], .stButtonGroup > div { gap: 6px; flex-wrap: wrap; }
.stButtonGroup button {
  min-height: 32px; height: 32px; padding: 0 12px; border-radius: 8px !important;
  border: 1px solid var(--moa-line-2); background: var(--moa-surface);
  color: var(--moa-ink-4); font: 400 12.5px/18px var(--moa-font);
}
.stButtonGroup button p { font: inherit; }
.stButtonGroup button[aria-checked="true"], .stButtonGroup button[data-selected="true"],
.stButtonGroup button[aria-pressed="true"] {
  background: var(--moa-green-soft) !important; border-color: var(--moa-green) !important;
  color: var(--moa-green-text) !important; font-weight: 700;
}

/* ===== 헤더 (56px · 흰 바탕 · 아래 선) ===== */
.st-key-moa_header {
  min-height: var(--moa-header); background: var(--moa-surface);
  border-bottom: 1px solid var(--moa-line);
  box-shadow: 0 0 0 100vmax var(--moa-surface); clip-path: inset(0 -100vmax);
  align-items: center; flex-wrap: nowrap; gap: 10px; margin-bottom: 12px;
}
.moa-brandmark { display: flex; align-items: center; gap: 9px; white-space: nowrap; }
.moa-logo-word { font: 800 18px/24px var(--moa-font); letter-spacing: -0.04em; color: var(--moa-ink); }
.moa-logo-slash { font: 300 16px/24px var(--moa-font); color: var(--moa-slash); margin: 0 6px 0 3px; }
.moa-ops-word { font: 600 13px/20px var(--moa-font); color: var(--moa-muted); margin-left: 4px; }
.moa-tabs { display: flex; gap: 2px; }
.moa-tab {
  display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 10px;
  border-radius: 8px; font: 500 13px/20px var(--moa-font); color: var(--moa-faint);
}
.moa-tab b { font: 500 11px/1 var(--moa-mono); color: var(--moa-faint); }
.moa-tab-on { background: var(--moa-tab); color: var(--moa-ink); font-weight: 600; }
.moa-tab-on b { color: var(--moa-green); font-weight: 700; }
.moa-head-right { display: flex; align-items: center; justify-content: flex-end; gap: 10px; white-space: nowrap; }
.moa-evidence { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-2); }
.moa-brand-pill {
  display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 10px;
  border-radius: 8px; background: var(--moa-green-pill); border: 1px solid var(--moa-green-pill-line);
  font: 600 12.5px/18px var(--moa-font); color: var(--moa-green-label);
}
.moa-brand-pill::before { content: ""; width: 6px; height: 6px; border-radius: 3px; background: var(--moa-green); }
.moa-env-badge {
  display: inline-flex; align-items: center; height: 22px; padding: 0 9px; border-radius: 11px;
  background: var(--moa-amber-bg); color: var(--moa-amber-text); font: 700 12px/16px var(--moa-font);
}
.st-key-moa_header .stButton button {
  min-height: 28px; height: 28px; padding: 0 10px; border-radius: 8px;
  font: 600 12.5px/18px var(--moa-font); color: var(--moa-ink-4);
}
.st-key-link_logout button { color: var(--moa-ink-4) !important; font: 600 13px/20px var(--moa-font) !important; }

/* ===== 상태 줄 (둥근 상자 · tone별 색) ===== */
.moa-status {
  display: flex; align-items: center; gap: 12px; min-height: 41px; padding: 0 16px;
  border-radius: 10px; font: 500 14px/20px var(--moa-font);
}
.moa-status-info    { background: var(--moa-status-info-bg); color: var(--moa-status-info-text); }
.moa-status-success { background: var(--moa-green-soft); color: var(--moa-green-text); font-weight: 600; }
.moa-status-warning { background: var(--moa-amber-bg); color: var(--moa-amber-status); font-weight: 600; }
.moa-status-danger  { background: var(--moa-red-bg); color: var(--moa-red-text); font-weight: 600; }
.st-key-moa_retry { margin-top: 16px; }
/* 링크 무효 화면 — [처음으로]를 상태 줄에서 띄운다 */
.st-key-link_invalid_home { margin-top: 16px; }
.moa-subhint { font: 400 12px/18px var(--moa-font); color: var(--moa-muted-3); margin: 6px 2px 0; }

/* ===== 하단 고정 바 · 가격 고지 ===== */
.st-key-moa_bar {
  position: fixed; left: 0; right: 0; bottom: var(--moa-foot); z-index: 100;
  min-height: var(--moa-bar); background: var(--moa-surface); border-top: 1px solid var(--moa-bar-line);
  padding: 0 max(var(--moa-gutter), calc((100vw - var(--moa-frame)) / 2 + var(--moa-gutter)));
  align-items: center; flex-wrap: nowrap;
}
.st-key-moa_bar_right { align-items: center; flex-wrap: nowrap; gap: 12px; }
.st-key-moa_bar .stButton button[kind="primary"], .st-key-moa_bar .stButton button:disabled {
  min-height: 42px; height: 42px; padding: 0 26px; border-radius: 12px; font: 700 15px/20px var(--moa-font);
}
.moa-barhint { font: 400 13px/20px var(--moa-font); color: var(--moa-muted-2); white-space: nowrap; }
.moa-barhint-warn { color: var(--moa-amber-text); font-weight: 600; }
.moa-footnote {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 99; height: var(--moa-foot);
  display: flex; align-items: center; justify-content: center;
  background: var(--moa-bg); font: 400 12px/16px var(--moa-font); color: var(--moa-faint);
}
.moa-devnote { font: 400 11px/16px var(--moa-font); color: var(--moa-faint); margin-top: 16px; }

/* ===== 공통 조각 ===== */
.moa-card {
  background: var(--moa-surface); border: 1px solid var(--moa-line); border-radius: 14px;
}
.moa-chip {
  display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 10px;
  border-radius: 11px; background: var(--moa-chip); font: 400 12px/16px var(--moa-font);
  color: var(--moa-ink-3); margin: 0 6px 0 0; white-space: nowrap;
}
.moa-chip i { font-style: normal; color: var(--moa-muted-3); }
.moa-chip-amb { background: var(--moa-amber-bg); color: var(--moa-amber-text); font-weight: 600; }
.moa-chip-amb i { color: var(--moa-amber-text); font-weight: 400; }
.moa-pill {
  display: inline-flex; align-items: center; height: 20px; padding: 0 8px; border-radius: 10px;
  font: 700 11.5px/16px var(--moa-font); white-space: nowrap;
}
.moa-pill-amber { background: var(--moa-amber-bg); color: var(--moa-amber-text); }
.moa-pill-green { background: var(--moa-green-soft); color: var(--moa-green-text); }
.moa-pill-gray  { background: var(--moa-tab); color: var(--moa-muted); }
.moa-pill-red   { background: var(--moa-red-bg); color: var(--moa-red-action); }
.moa-pill-solid { background: var(--moa-green); color: #FFFFFF; }
.moa-pill-strong{ background: var(--moa-amber-strong); color: #FFFFFF; }
.moa-custom {
  background: var(--moa-sunken); border-radius: 8px; padding: 9px 12px; margin-top: 8px;
  font: 400 12.5px/19px var(--moa-font); color: var(--moa-muted);
}
.moa-custom b { font-weight: 600; color: var(--moa-muted-3); margin-right: 2px; }
.moa-swatch { display: inline-flex; align-items: center; justify-content: center; flex: none; }
.moa-swatch-ring { border: 1.5px solid rgba(255,255,255,0.9); border-radius: 50%; }
.moa-avatar {
  width: 30px; height: 30px; border-radius: 8px; background: var(--moa-green-soft);
  display: inline-flex; align-items: center; justify-content: center; flex: none;
}
.moa-avatar-lg { width: 34px; height: 34px; }
.moa-skel { height: 64px; border-radius: 10px; background: var(--moa-skeleton); margin-bottom: 12px; }

/* ===== SCR-001 주문 시작 ===== */
.st-key-moa_s1 { max-width: var(--moa-column) !important; margin: 16px auto 0 !important; width: 100% !important; gap: 18px; }
.moa-hero {
  height: 136px; border-radius: 16px; background: var(--moa-green-deep); padding: 0 24px;
  display: flex; align-items: center; justify-content: space-between;
}
.moa-hero-kicker { font: 600 12px/16px var(--moa-font); color: var(--moa-green-mint); margin-bottom: 8px; }
.moa-hero-title { font: 700 24px/32px var(--moa-font); color: #FFFFFF; letter-spacing: -0.02em; }
.moa-hero-art { display: flex; align-items: center; gap: 10px; margin-right: 20px; }
.moa-hero-dot { width: 12px; height: 12px; border-radius: 6px; }
.moa-hero-line { width: 28px; height: 1px; background: #E9D9B8; margin: 0 4px; }
.moa-hero-cup {
  width: 72px; height: 72px; border-radius: 36px; background: #F4EEE3;
  display: flex; align-items: center; justify-content: center;
}
.moa-hero-cup-in {
  width: 50px; height: 50px; border-radius: 25px; background: #7A5238;
  display: flex; align-items: center; justify-content: center;
}
/* 아바타 + 카드 한 줄 (Moa 말) */
[class*="st-key-moa_says"] { flex-wrap: nowrap; gap: 12px; align-items: flex-start; }
[class*="st-key-moa_says"] > div:first-child { flex: 0 0 34px !important; width: 34px !important; }
.st-key-moa_intro, .st-key-moa_preview {
  background: var(--moa-surface); border: 1px solid var(--moa-line); border-radius: 6px;
  padding: 24px 24px 22px; gap: 0; flex: 1 1 auto; min-width: 0;
}
.moa-intro-title { font: 700 18px/26px var(--moa-font); color: var(--moa-ink); margin-bottom: 8px; }
.moa-intro-desc { font: 400 14.5px/24px var(--moa-font); color: var(--moa-ink-5); }
.moa-intro-desc b { color: var(--moa-ink); font-weight: 700; }
.moa-intro-label { font: 700 12.5px/18px var(--moa-font); color: var(--moa-muted-2); margin: 22px 0 10px; }
.moa-steps-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.moa-step-tile {
  display: flex; align-items: center; gap: 10px; height: 46px; padding: 0 14px;
  border-radius: 10px; background: var(--moa-sunken); font: 400 13.5px/20px var(--moa-font); color: var(--moa-ink-3);
}
.moa-step-no {
  width: 22px; height: 22px; border-radius: 11px; flex: none; display: inline-flex;
  align-items: center; justify-content: center; font: 700 12px/1 var(--moa-font);
  background: var(--moa-surface); border: 1px solid var(--moa-line-3); color: var(--moa-ink-5);
}
.moa-step-no-on { background: var(--moa-green); border-color: var(--moa-green); color: #FFFFFF; }
.moa-format-box {
  border-radius: 10px; background: var(--moa-sunken); padding: 12px 16px;
  font: 400 13.5px/20px var(--moa-font); color: var(--moa-ink-3);
}
.moa-format-box b, .moa-reply-name { color: var(--moa-green); font-weight: 600; }
.st-key-link_sample { margin-top: 18px; }
.st-key-link_sample button {
  min-height: 38px !important; padding: 0 18px !important; border-radius: 19px !important;
  border: 1px solid var(--moa-green-line) !important; background: var(--moa-surface) !important;
  color: var(--moa-green-text) !important; font: 600 13.5px/20px var(--moa-font) !important;
}
/* 대화 미리보기 */
.st-key-moa_preview { padding: 20px 20px 16px; }
.st-key-moa_preview_head { align-items: center; flex-wrap: nowrap; margin-bottom: 8px; }
.moa-preview-title { display: flex; align-items: center; gap: 8px; font: 700 15px/22px var(--moa-font); color: var(--moa-ink); }
.moa-preview-rows { display: grid; grid-template-columns: 76px 1fr; row-gap: 12px; padding: 6px 2px 14px; }
.moa-preview-name { font: 500 13.5px/20px var(--moa-font); color: var(--moa-ink-5); }
.moa-preview-text { font: 400 13.5px/20px var(--moa-font); color: var(--moa-ink); }
.moa-preview-bad { color: var(--moa-red-text); }
.moa-preview-foot {
  border-top: 1px solid var(--moa-line-soft); padding-top: 12px;
  display: flex; align-items: center; gap: 8px; font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-2);
}
.moa-preview-foot .moa-warn { color: var(--moa-amber-text); margin-left: 8px; }
/* 입력 바 */
.st-key-moa_inputbar {
  background: var(--moa-surface); border: 1px solid var(--moa-line-2); border-radius: 14px;
  padding: 10px; flex-wrap: nowrap; align-items: center; gap: 12px; margin-top: 8px;
}
.st-key-moa_inputbar .stTextArea { flex: 1 1 auto; }
.st-key-moa_inputbar [data-testid="stTextAreaRootElement"] { border: none !important; background: transparent !important; }
.st-key-moa_inputbar textarea {
  min-height: 38px !important; height: 38px; padding: 8px 4px !important; resize: none;
  font: 400 14.5px/22px var(--moa-font) !important;
}
.st-key-moa_inputbar [data-testid="stTextAreaRootElement"], .st-key-moa_inputbar .stTextArea > div > div {
  min-height: 38px !important; height: auto !important;
}
/* 대화를 넣으면 세 줄까지 보이고 그 아래는 칸 안에서 스크롤한다 — 비어 있을 때는 시안처럼 한 줄 */
.st-key-moa_inputbar textarea:not(:placeholder-shown) { height: 74px !important; overflow-y: auto; }
.st-key-moa_inputbar .stTextArea { min-width: 0; }
.st-key-moa_inputbar .stButton button {
  min-height: 38px; height: 38px; padding: 0 20px; font: 700 15px/20px var(--moa-font); border-radius: 10px;
}
/* [+] — 파일 고르기. Streamlit 업로더를 38px 정사각으로 줄이고 영문 문구를 감춘다 */
.st-key-moa_upload { flex: 0 0 38px !important; width: 38px !important; }
.st-key-moa_upload [data-testid="stFileUploader"] > label,
.st-key-moa_upload [data-testid="stFileUploaderDropzoneInstructions"],
.st-key-moa_upload [data-testid="stFileUploaderFile"],
.st-key-moa_upload [data-testid="stFileUploaderDeleteBtn"],
.st-key-moa_upload section + div { display: none !important; }
.st-key-moa_upload [data-testid="stFileUploaderDropzone"] {
  width: 38px; height: 38px; min-height: 38px; padding: 0; border: none; border-radius: 10px;
  background: var(--moa-chip); display: flex; align-items: center; justify-content: center;
}
.st-key-moa_upload [data-testid="stFileUploaderDropzone"] button {
  position: absolute; inset: 0; width: 38px; height: 38px; min-height: 38px; opacity: 0; padding: 0;
}
.st-key-moa_upload [data-testid="stFileUploaderDropzone"] { position: relative; overflow: hidden; }
.st-key-moa_upload [data-testid="stFileUploaderDropzone"] > *:not(button) { display: none; }
.st-key-moa_upload [data-testid="stFileUploaderDropzone"]::after {
  content: "+"; position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font: 300 22px/1 var(--moa-font); color: var(--moa-ink-4); pointer-events: none;
}
.moa-under { text-align: center; font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-3); margin-top: 4px; }
/* 사진 안내는 입력 바 바로 위에 떠 있다 — 입력 바를 밀어내지 않는다 (시안 케이스 03) */
.st-key-moa_s1 > [data-testid="stElementContainer"]:has(.moa-toast-pill) { height: 0; overflow: visible; z-index: 5; }
.st-key-moa_s1 .moa-toast-pill { transform: translateY(-46px); }
.moa-toast-pill {
  display: flex; align-items: center; gap: 10px; width: fit-content; margin: 0 auto;
  height: 40px; padding: 0 20px; border-radius: 20px; background: var(--moa-toast);
  color: #FFFFFF; font: 500 13.5px/20px var(--moa-font);
}

/* ===== 대화상자 ===== */
[role="dialog"] { border-radius: 16px !important; background: var(--moa-surface) !important; }
.moa-dlg-head { margin-top: 6px !important; }
[role="dialog"] h2 { font: 700 18px/26px var(--moa-font) !important; color: var(--moa-ink); padding: 22px 24px 2px !important; }
[role="dialog"] h2 p { font: inherit !important; }
[data-testid="stDialog"] div:has(> [role="dialog"] .st-key-dlg_ops) { width: 420px !important; max-width: calc(100vw - 32px) !important; }
[data-testid="stDialog"] div:has(> [role="dialog"] .st-key-dlg_brand) { width: 480px !important; max-width: calc(100vw - 32px) !important; }
[data-testid="stDialog"] div:has(> [role="dialog"] .st-key-dlg_menu) { width: 520px !important; max-width: calc(100vw - 32px) !important; }
[data-testid="stDialog"] div:has(> [role="dialog"] .st-key-dlg_share) { width: 540px !important; max-width: calc(100vw - 32px) !important; }
[role="dialog"]:has(.st-key-dlg_ops) h2, [role="dialog"]:has(.st-key-dlg_brand) h2 { display: none; }
.moa-dlg-head { display: flex; gap: 14px; align-items: flex-start; margin: -4px 0 4px; }
.moa-dlg-icon {
  width: 40px; height: 40px; border-radius: 10px; background: var(--moa-chip); flex: none;
  display: flex; align-items: center; justify-content: center; color: var(--moa-ink-4);
}
.moa-dlg-icon-green { background: var(--moa-green-pill); color: var(--moa-green); }
.moa-dlg-title { font: 700 17px/24px var(--moa-font); color: var(--moa-ink); }
.moa-dlg-sub { font: 400 13px/20px var(--moa-font); color: var(--moa-muted); }
.moa-field-label { font: 600 12.5px/18px var(--moa-font); color: var(--moa-ink-3); margin: 12px 0 -4px; }
.moa-form-error { font: 600 12.5px/18px var(--moa-font); color: var(--moa-red-text); margin-top: -4px; }
.st-key-dlg_ops [data-testid="stForm"] { border: none; padding: 0; }
.st-key-dlg_ops_err [data-testid="stTextInputRootElement"] { border-color: var(--moa-red-line) !important; background: var(--moa-red-input) !important; }
.st-key-dlg_ops_err input { background: transparent !important; }
.st-key-dlg_ops [data-testid="stTextInputRootElement"] { min-height: 42px; }
/* 대화상자는 화면 가운데 (시안 케이스 04 · 05 · 15 · 21) */
[data-testid="stDialog"] > div:has(> [role="dialog"]) { margin-top: auto !important; margin-bottom: auto !important; }
.st-key-dlg_ops [data-testid="stFormSubmitButton"] button { min-height: 42px; border-radius: 10px; }
/* 매장 되묻기 */
.moa-found {
  background: var(--moa-sunken); border-radius: 12px; padding: 12px 12px 6px; margin: 4px 0 6px;
}
.moa-found-label { font: 600 11.5px/16px var(--moa-font); color: var(--moa-muted-2); margin-bottom: 8px; }
.moa-found-chip {
  display: inline-flex; align-items: center; height: 26px; padding: 0 10px; border-radius: 13px;
  background: var(--moa-surface); border: 1px solid var(--moa-line); margin: 0 6px 6px 0;
  font: 400 12px/16px var(--moa-font); color: var(--moa-ink-3);
}
.moa-found-chip b { color: var(--moa-green-text); font-weight: 700; margin-right: 2px; }
.moa-opt {
  display: flex; align-items: center; gap: 14px; min-height: 60px; padding: 12px 14px;
  border: 1px solid var(--moa-line); border-radius: 12px; background: var(--moa-surface);
}
[class*="st-key-card_brand"]:hover .moa-opt { border-color: var(--moa-green-line); }
.moa-opt-icon {
  width: 36px; height: 36px; border-radius: 10px; flex: none;
  display: flex; align-items: center; justify-content: center;
}
.moa-opt-icon span { width: 14px; height: 14px; border-radius: 7px; }
.moa-opt-title { font: 700 14.5px/20px var(--moa-font); color: var(--moa-ink); }
.moa-opt-desc { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-2); }
.moa-opt-chev { margin-left: auto; color: var(--moa-faint); }
.st-key-dlg_brand_other {
  border: 1px solid var(--moa-green); border-radius: 12px; background: var(--moa-green-other);
  padding: 14px; gap: 10px;
}
.moa-opt-other-title { display: flex; align-items: center; gap: 14px; font: 700 14.5px/20px var(--moa-font); color: var(--moa-green-text); }
.st-key-dlg_brand_other_row { flex-wrap: nowrap; align-items: center; gap: 8px; }
.st-key-dlg_brand_other_row .stTextInput { flex: 1 1 auto; }
.st-key-dlg_brand_other_row .stButton button { min-height: 40px; }
.moa-opt-hint { font: 400 12px/18px var(--moa-font); color: var(--moa-muted); }
.st-key-dlg_brand_foot {
  margin: 8px -24px -24px; padding: 14px 24px; width: calc(100% + 48px) !important; background: var(--moa-sunken);
  border-top: 1px solid var(--moa-line-soft); border-radius: 0 0 16px 16px;
  flex-wrap: nowrap; align-items: center;
}
.st-key-dlg_brand_foot .stButton button { min-height: 34px; height: 34px; font-size: 13px; }
.moa-dlg-foot-text { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-2); }
/* 메뉴 찾기 */
.st-key-dlg_menu .stTextInput [data-testid="stTextInputRootElement"] { background: var(--moa-sunken) !important; border-color: var(--moa-bar-line) !important; }
.st-key-dlg_menu .stTextInput input { padding-left: 38px; }
.st-key-dlg_menu .stTextInput > div { position: relative; }
.st-key-dlg_menu .stTextInput::before {
  content: ""; position: absolute; left: 14px; top: 14px; width: 16px; height: 16px; z-index: 2;
  background: no-repeat center/16px url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238B8B91' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E");
}
.st-key-dlg_menu .stTextInput { position: relative; }
.moa-scope { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-2); }
.moa-scope b { color: var(--moa-green-text); font-weight: 700; }
.st-key-dlg_menu_list { gap: 0; margin: 0 -10px; border-top: 1px solid var(--moa-chip); }
.moa-menu-row {
  display: flex; align-items: center; gap: 10px; height: 58px; padding: 0 12px;
  border-bottom: 1px solid var(--moa-chip);
}
[class*="st-key-card_menu"]:hover .moa-menu-row { background: var(--moa-sunken); }
.moa-menu-name { font: 600 14.5px/20px var(--moa-font); color: var(--moa-ink); flex: 1 1 auto; }
.moa-menu-spec { height: 20px; padding: 0 9px; border-radius: 10px; background: var(--moa-chip); font: 400 12px/20px var(--moa-font); color: var(--moa-muted); }
.moa-menu-price { width: 82px; text-align: right; font: 400 13.5px/20px var(--moa-font); color: var(--moa-ink-4); }

/* ===== SCR-002 주문 정리 ===== */
.st-key-moa_work { flex-wrap: nowrap; gap: 24px; align-items: flex-start; margin-top: 18px; }
.st-key-moa_panel {
  width: var(--moa-panel) !important; height: var(--moa-work-height) !important;
  min-height: 420px !important; background: var(--moa-surface); border: 1px solid var(--moa-line);
  border-radius: 14px; gap: 0; overflow: hidden !important;
}
.st-key-moa_panel_head { padding: 22px 22px 18px; gap: 0; border-bottom: 1px solid var(--moa-line-soft); flex: none; }
.st-key-moa_panel_rows { flex: 1 1 auto !important; overflow-y: auto !important; padding: 6px 10px; gap: 2px; min-height: 0 !important; }
.st-key-moa_panel_skel { padding: 22px; gap: 0; }
.moa-panel-title { display: flex; align-items: center; gap: 8px; font: 700 15px/22px var(--moa-font); color: var(--moa-ink); }
.moa-panel-big { font: 700 30px/40px var(--moa-font); color: var(--moa-ink); letter-spacing: -0.02em; margin-top: 6px; }
.moa-panel-amount { font: 400 13px/20px var(--moa-font); color: var(--moa-muted); }
.moa-panel-amount b { color: var(--moa-ink); font-weight: 700; }
.moa-panel-empty { font: 400 13.5px/20px var(--moa-font); color: var(--moa-muted); margin: 12px 0 24px; }
.moa-panel-foot {
  flex: none; border-top: 1px solid var(--moa-line-soft); padding: 12px 22px;
  font: 400 12px/18px var(--moa-font); color: var(--moa-muted-3); background: var(--moa-surface);
}
/* 2026-11-05 보고 9번 — 패널 하단(AI 고지 + 전체 대화 펼치기) · 확인 중 안내 */
.st-key-moa_panel_foot {
  flex: none; border-top: 1px solid var(--moa-line-soft); padding: 10px 22px 12px;
  background: var(--moa-surface); gap: 2px;
}
.moa-panel-foot-text { font: 400 12px/18px var(--moa-font); color: var(--moa-muted-3); }
.moa-panel-asking {
  margin: 6px 10px; padding: 10px 12px; border-radius: 10px; background: var(--moa-sunken);
  font: 400 12.5px/19px var(--moa-font); color: var(--moa-muted-2);
}
.moa-panel-raw { max-height: 220px; overflow: auto; margin-top: 8px; }
[class*="st-key-card_row"] { border-radius: 10px; padding: 14px 12px; gap: 0; }
[class*="st-key-card_row"]:hover { background: var(--moa-sunken); }
.st-key-moa_row_changed, [class*="st-key-card_row"]:has(.moa-row-changed) { background: var(--moa-changed) !important; }
.moa-row { display: flex; gap: 12px; }
.moa-row-body { flex: 1 1 auto; min-width: 0; }
.moa-row-top { display: flex; justify-content: space-between; align-items: center; }
.moa-row-person { font: 600 12.5px/18px var(--moa-font); color: var(--moa-muted-2); }
/* 한 사람이 여러 잔일 때의 순번 — 이름 옆 작은 회색 (2026-11-05 3차 보고 3번) */
/* 막는 이유를 누를 수 있게 한 버튼 — 글자만 보이고 밑줄로 누를 수 있음을 알린다 (3차 보고 7번) */
[class*="_blocked"] button { background: transparent !important; border: none !important; }
[class*="_blocked"] button p {
  font: 400 12.5px/18px var(--moa-font) !important; color: var(--moa-muted-2) !important;
  text-decoration: underline; text-underline-offset: 3px;
}
.moa-row-seq {
  margin-left: 6px; padding: 1px 6px; border-radius: 999px; background: var(--moa-sunken);
  font: 600 11px/16px var(--moa-font); color: var(--moa-muted-3);
}
.moa-row-amount { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-2); }
.moa-row-menu { font: 700 15px/22px var(--moa-font); color: var(--moa-ink); margin: 4px 0 6px; }
.moa-row-menu-amb { color: var(--moa-amber-text); }
.moa-row-reason { font: 400 12px/18px var(--moa-font); color: var(--moa-amber-text); margin-top: 6px; }
/* 행 편집 상자 */
[class*="st-key-moa_editor"] {
  margin: 12px 0 2px 48px; padding: 14px; border: 1px solid var(--moa-line); border-radius: 12px;
  background: var(--moa-sunken); gap: 10px;
}
.moa-edit-head { font: 700 14px/20px var(--moa-font); color: var(--moa-ink); }
.moa-edit-head span { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-2); margin-left: 6px; }
[class*="st-key-optrow_"] { flex-wrap: nowrap; align-items: center; gap: 8px; }
[class*="st-key-optrow_"] > div:first-child { flex: 0 0 52px; }   /* "기타 요청"이 두 줄로 꺾이지 않게 */
.moa-opt-label { font: 400 12px/18px var(--moa-font); color: var(--moa-muted-2); white-space: nowrap; }
[class*="st-key-moa_editor"] .stTextArea textarea, [class*="st-key-moa_editor"] .stTextInput input { font-size: 12.5px; }
[class*="st-key-edit_actions"] { flex-wrap: nowrap; align-items: center; gap: 8px; }
[class*="st-key-edit_actions"] .stButton button { min-height: 32px; height: 32px; padding: 0 12px; font-size: 12.5px; border-radius: 8px; }

/* 채팅 열 */
.st-key-moa_chatcol { min-width: 0 !important; height: var(--moa-work-height) !important; min-height: 420px !important; gap: 12px; }
.st-key-moa_chatlog { flex: 1 1 auto !important; overflow-y: auto !important; min-height: 0 !important; gap: 14px; padding: 4px 4px 4px 4px; }
.st-key-moa_rawpill, .st-key-moa_rawpill_open {
  align-self: flex-end; width: fit-content; background: var(--moa-green-soft); border-radius: 14px;
  padding: 10px 16px; gap: 12px; margin-left: auto;
}
.st-key-moa_rawpill_open { width: min(560px, 100%); padding: 14px 16px 16px; }
.st-key-moa_rawpill_head, .st-key-moa_rawpill_open_head { flex-wrap: nowrap; align-items: center; gap: 14px; }
.st-key-link_progress_collapse .stButton button { color: var(--moa-muted-2); }
/* 열 안의 스크롤 영역 — Streamlit은 키 달린 컨테이너를 한 겹 더 감싸므로 감싼 쪽도 늘린다 */
.st-key-moa_panel > [data-testid="stLayoutWrapper"]:has(> .st-key-moa_panel_rows),
.st-key-moa_chatcol > [data-testid="stLayoutWrapper"]:has(> .st-key-moa_chatlog) {
  flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column;
}
.st-key-moa_work > [data-testid="stLayoutWrapper"]:has(> .st-key-moa_panel) { flex: 0 0 var(--moa-panel); }
.st-key-moa_work > [data-testid="stLayoutWrapper"]:has(> .st-key-moa_chatcol) { flex: 1 1 auto; min-width: 0; }
.moa-raw-label { display: flex; align-items: center; gap: 8px; font: 700 14px/20px var(--moa-font); color: var(--moa-green-ink); white-space: nowrap; }
.moa-raw-list { background: var(--moa-surface); border-radius: 10px; padding: 4px 14px; }
.moa-raw-row { display: grid; grid-template-columns: 62px 1fr auto; gap: 12px; align-items: start; padding: 10px 0; border-bottom: 1px solid var(--moa-line-faint); }
.moa-raw-row:last-child { border-bottom: none; }
.moa-raw-name { font: 500 13px/20px var(--moa-font); color: var(--moa-ink-5); }
.moa-raw-text { font: 400 13px/20px var(--moa-font); color: var(--moa-ink); }
[class*="st-key-bot_"] { flex-wrap: nowrap; gap: 10px; align-items: flex-start; }
[class*="st-key-bot_"] > div:first-child { flex: 0 0 30px; }
[class*="st-key-bubble_"] {
  width: fit-content; max-width: 560px !important; background: var(--moa-surface); border: 1px solid var(--moa-line);
  border-radius: 6px; padding: 14px 16px; gap: 10px;
}
.moa-bubble-text { font: 400 14.5px/22px var(--moa-font); color: var(--moa-ink); }
.moa-bubble-text b { font-weight: 700; }
[class*="st-key-bubblerow_"] { flex-wrap: nowrap; align-items: center; gap: 16px; }
.moa-me {
  align-self: flex-end; max-width: 80%; width: fit-content; margin-left: auto;
  background: var(--moa-green-soft); border-radius: 14px; padding: 9px 16px;
  font: 500 14.5px/21px var(--moa-font); color: var(--moa-green-ink);
}
.moa-progress-line { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.moa-progress-line b { font: 700 14px/20px var(--moa-font); color: var(--moa-ink); }
.moa-progress-line span { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-3); overflow: hidden; text-overflow: ellipsis; }
.moa-step-ico {
  width: 20px; height: 20px; border-radius: 10px; flex: none; display: inline-flex;
  align-items: center; justify-content: center; color: #FFFFFF; background: var(--moa-green);
}
.moa-step-ico-pending { background: transparent; border: 1px solid var(--moa-line-3); }
.moa-step-ico-failed { background: var(--moa-red-dot); }
.moa-step-ico-running { background: transparent; border: 2px solid var(--moa-green-line); border-top-color: var(--moa-green); animation: moa-spin 900ms linear infinite; }
@keyframes moa-spin { to { transform: rotate(360deg); } }
.moa-steps { display: flex; flex-direction: column; gap: 10px; }
.moa-step { display: flex; gap: 10px; align-items: flex-start; }
.moa-step-label { font: 600 14px/20px var(--moa-font); color: var(--moa-ink); }
.moa-step-pending .moa-step-label { font-weight: 400; color: var(--moa-muted-2); }
.moa-step-note { font: 400 12.5px/17px var(--moa-font); color: var(--moa-muted-2); }
.moa-step-note-warn { color: var(--moa-amber-text); font-weight: 600; }
.moa-q { display: flex; gap: 8px; align-items: flex-start; font: 600 15px/22px var(--moa-font); color: var(--moa-ink); }
.moa-q .moa-pill { margin-top: 1px; }
[class*="st-key-answers_"] { flex-wrap: wrap; gap: 8px; align-items: center; }
[class*="st-key-answers_"] .stButton button { min-width: 112px; min-height: 38px; border-color: var(--moa-line-3); color: var(--moa-ink); }
[class*="st-key-answers_"] .stButton button:disabled { background: var(--moa-sunken); border-color: var(--moa-bar-line); color: var(--moa-faint); }
[class*="st-key-chosen_"] .stButton button:disabled { background: var(--moa-surface) !important; border-color: var(--moa-ink) !important; color: var(--moa-ink) !important; font-weight: 700; }
[class*="st-key-link_evidence"] button { color: var(--moa-muted) !important; padding-left: 8px !important; }
[class*="st-key-link_undo"] button { white-space: nowrap; }
.moa-evidence-list { border-top: 1px solid var(--moa-line-soft); padding-top: 8px; }
.st-key-moa_chatcol .stChatInput, .st-key-moa_chatcol [data-testid="stChatInput"] { flex: none; }
[data-testid="stChatInput"] > div {
  border-radius: 14px !important; border: 1px solid var(--moa-line-2) !important;
  background: var(--moa-surface) !important; min-height: 58px; padding: 8px 8px 8px 18px;
}
[data-testid="stChatInputTextArea"] { font: 400 14px/22px var(--moa-font) !important; color: var(--moa-ink-2); }
[data-testid="stChatInputTextArea"]::placeholder { color: var(--moa-faint); }
[data-testid="stChatInputSubmitButton"] {
  width: 40px; height: 40px; border-radius: 10px !important; background: var(--moa-green) !important; color: #FFFFFF !important;
}
/* 빈 칸이라 못 보낼 때도 초록을 유지한다(시안 케이스 11) — 정리 중으로 입력창이 잠겼을 때만 회색 */
[data-testid="stChatInputSubmitButton"]:disabled { background: var(--moa-green) !important; color: #FFFFFF !important; opacity: 1; }
[data-testid="stChatInput"]:has(textarea:disabled) [data-testid="stChatInputSubmitButton"] {
  background: var(--moa-disabled-bg) !important; color: var(--moa-disabled-text) !important;
}
[data-testid="stChatInputSubmitButton"] svg { color: inherit; fill: currentColor; }
.moa-brandask .moa-dlg-foot-text { margin-top: 2px; }
[class*="st-key-brandask_"] { flex-wrap: nowrap; gap: 8px; }
[class*="st-key-brandask_"] .stButton button { min-height: 34px; height: 34px; font-size: 13px; }

/* ===== SCR-005 주문서 ===== */
.st-key-moa_order { flex-wrap: nowrap; gap: 24px; align-items: flex-start; margin-top: 20px; }
.st-key-moa_order_main { min-width: 0 !important; gap: 16px; }
.st-key-moa_order_side { width: var(--moa-side) !important; gap: 0; }
.moa-sum-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.moa-sum { height: 97px; border-radius: 14px; padding: 22px 23px 0; }
.moa-sum-label { display: flex; align-items: center; gap: 6px; font: 400 13px/18px var(--moa-font); }
.moa-sum-num { font: 700 34px/44px var(--moa-font); letter-spacing: -0.02em; margin-top: 4px; }
.moa-sum-num small { font: 700 18px/1 var(--moa-font); margin-left: 2px; }
.moa-sum-dark { background: var(--moa-green-deep); color: #FFFFFF; }
.moa-sum-dark .moa-sum-label { color: var(--moa-green-mint); }
.moa-sum-light { background: var(--moa-green-tint); color: var(--moa-green-tint-ink); }
.moa-sum-light .moa-sum-label { color: var(--moa-green-tint-label); }
.st-key-moa_sheet { background: var(--moa-surface); border: 1px solid var(--moa-line); border-radius: 14px; padding: 22px 22px 20px; gap: 0; }
.moa-sheet-title { display: flex; align-items: baseline; gap: 10px; padding-bottom: 14px; border-bottom: 1px solid var(--moa-line-soft); }
.moa-sheet-title b { font: 700 17px/24px var(--moa-font); color: var(--moa-ink); }
.moa-sheet-title span { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-3); }
[class*="st-key-group_"] { padding: 16px 0 18px; border-bottom: 1px solid var(--moa-line-soft); gap: 12px; }
.moa-group { display: flex; gap: 16px; }
.moa-group-body { flex: 1 1 auto; min-width: 0; }
.moa-group-menu { font: 700 16px/22px var(--moa-font); color: var(--moa-ink); margin: 2px 0 7px; }
.moa-group-right { text-align: right; white-space: nowrap; }
.moa-qty { font: 700 24px/30px var(--moa-font); color: var(--moa-ink); }
.moa-qty i { font: 600 16px/1 var(--moa-font); font-style: normal; color: var(--moa-muted-3); margin-right: 2px; }
.moa-group-amount { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-3); }
[class*="st-key-names_"] { flex-wrap: wrap; gap: 6px; align-items: center; }
[class*="st-key-names_"] .stButton button {
  min-height: 30px; height: 30px; padding: 0 12px; border-radius: 15px; font: 600 13px/18px var(--moa-font); color: var(--moa-ink-3);
}
[class*="st-key-names_"] .stButton button[kind="primary"] { background: var(--moa-green-soft); border-color: var(--moa-green); color: var(--moa-green-text); }
.moa-name-chip {
  display: inline-flex; align-items: center; height: 30px; padding: 0 12px; border-radius: 15px;
  border: 1px solid var(--moa-line-2); background: var(--moa-surface); font: 600 13px/18px var(--moa-font); color: var(--moa-ink-3); margin-right: 6px;
}
.moa-total {
  margin-top: 18px; padding: 18px 18px 14px; border-radius: 12px; background: var(--moa-sunken);
}
.moa-total-top { display: flex; justify-content: space-between; align-items: baseline; }
.moa-total-top b { font: 700 15px/22px var(--moa-font); color: var(--moa-ink); }
.moa-total-top span { font: 700 16px/22px var(--moa-font); color: var(--moa-ink); }
.moa-total-note { text-align: right; font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-3); margin-top: 4px; }
[class*="st-key-moa_editor_group"] { margin: 0; }
.st-key-moa_reply { background: var(--moa-surface); border: 1px solid var(--moa-line); border-radius: 14px; padding: 22px 20px; gap: 14px; }
.moa-side-title { display: flex; align-items: center; gap: 8px; font: 700 15px/22px var(--moa-font); color: var(--moa-ink); }
.moa-side-sub { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-2); margin-top: 2px; }
.st-key-moa_reply .stTextArea [data-testid="stTextAreaRootElement"] { background: var(--moa-sunken) !important; border-color: var(--moa-bar-line) !important; }
.st-key-moa_reply .stTextArea textarea { font-size: 13px; }
.st-key-reply_find button { width: 100%; border-color: var(--moa-ink) !important; color: var(--moa-ink) !important; font-weight: 700 !important; }
/* 빈 칸이어도 시안은 같은 모양이다(케이스 18) — 누를 수만 없다 */
.st-key-reply_find button:disabled { border-color: var(--moa-ink) !important; background: var(--moa-surface) !important; color: var(--moa-ink) !important; }
.moa-found-head { border-top: 1px solid var(--moa-line-soft); padding-top: 16px; display: flex; align-items: baseline; gap: 8px; }
.moa-found-head b { font: 700 14px/20px var(--moa-font); color: var(--moa-ink); }
.moa-found-head span { font: 400 11.5px/16px var(--moa-font); color: var(--moa-muted-3); }
[class*="st-key-sugg_"] { border: 1px solid var(--moa-line); border-radius: 12px; padding: 14px; gap: 8px; }
[class*="st-key-sugg_q"] { background: var(--moa-amber-card); border-color: var(--moa-amber-line); }
.moa-sugg-who { font: 700 13.5px/20px var(--moa-font); color: var(--moa-ink); }
.moa-sugg-who span { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-2); margin-left: 6px; }
.moa-sugg-change { font: 400 13px/20px var(--moa-font); color: var(--moa-ink-3); }
.moa-sugg-change s { color: var(--moa-muted-3); }
.moa-sugg-change b { font-weight: 700; }
.moa-sugg-ask { font: 600 13px/20px var(--moa-font); color: var(--moa-amber-text); }
.moa-sugg-done { font: 600 12px/18px var(--moa-font); color: var(--moa-muted-2); }
[class*="st-key-suggbtn_"] { flex-wrap: nowrap; gap: 6px; }
[class*="st-key-suggbtn_"] .stButton button { min-height: 32px; height: 32px; padding: 0 13px; border-radius: 8px; font: 600 12.5px/18px var(--moa-font); color: var(--moa-muted); }
[class*="st-key-sg_apply_"] button { background: var(--moa-green-soft) !important; border-color: var(--moa-green-soft) !important; color: var(--moa-green-text) !important; font-weight: 700 !important; }
[class*="st-key-sg_open_"] button { border-color: var(--moa-line-3) !important; color: var(--moa-ink) !important; font-weight: 700 !important; }
.st-key-sg_apply_all, .st-key-sg_apply_all .stButton { width: 100% !important; }
.st-key-sg_apply_all button { width: 100%; background: var(--moa-chip) !important; border-color: var(--moa-chip) !important; color: var(--moa-ink-3) !important; font: 700 13px/18px var(--moa-font) !important; border-radius: 8px !important; }
/* 공유 */
.moa-share-card { border: 1px solid var(--moa-line); border-radius: 14px; overflow: hidden; background: var(--moa-sunken); }
.moa-share-head { background: var(--moa-green-deep); padding: 18px 22px; display: flex; justify-content: space-between; align-items: center; }
.moa-share-head b { display: block; font: 700 16px/22px var(--moa-font); color: #FFFFFF; }
.moa-share-head span { font: 400 12px/18px var(--moa-font); color: var(--moa-green-mint); }
.moa-share-dots { display: flex; }
.moa-share-dots i { width: 16px; height: 16px; border-radius: 8px; border: 1.5px solid var(--moa-green-deep); margin-left: -5px; }
.moa-share-body { padding: 14px 22px 14px; }
.moa-share-line { padding: 6px 0; }
.moa-share-top { display: flex; justify-content: space-between; align-items: center; font: 700 14px/20px var(--moa-font); color: var(--moa-ink); }
.moa-share-top span { display: inline-flex; align-items: center; gap: 8px; }
.moa-share-dot { width: 8px; height: 8px; border-radius: 4px; display: inline-block; }
.moa-share-people { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted); }
.moa-share-req { font: 400 12px/18px var(--moa-font); color: var(--moa-muted); }
.moa-share-total { border-top: 1px solid var(--moa-line); margin-top: 10px; padding-top: 12px; }
.moa-share-total .moa-share-top { font-size: 14px; }
.moa-share-note { font: 400 11.5px/16px var(--moa-font); color: var(--moa-muted-2); }
.moa-share-foot { font: 400 11px/16px var(--moa-font); color: var(--moa-muted-3); margin-top: 12px; }
.st-key-dlg_share_btns { flex-wrap: nowrap; gap: 10px; }
.st-key-dlg_share_btns > div { flex: 1 1 0; }
.st-key-dlg_share_btns .stButton button, .st-key-dlg_share_btns .stDownloadButton button { width: 100%; min-height: 52px; border-radius: 12px; font-size: 15px; }
.moa-dlg-caption { text-align: center; font: 400 12px/18px var(--moa-font); color: var(--moa-muted-3); }

/* ===== SCR-006 운영 대시보드 ===== */
.st-key-moa_ops { gap: 16px; margin-top: 8px; }
[class*="st-key-moa_approval_"] {
  background: var(--moa-amber-card); border: 1px solid var(--moa-amber-line); border-radius: 14px;
  padding: 18px 22px; flex-wrap: nowrap; align-items: center; gap: 16px;
}
.st-key-moa_approval_none { background: var(--moa-surface); border-color: var(--moa-line); }
.moa-appr-top { display: flex; align-items: center; gap: 8px; font: 700 12.5px/18px var(--moa-font); color: var(--moa-amber-text); }
.moa-appr-id { height: 19px; padding: 0 8px; border-radius: 8px; background: var(--moa-surface); border: 1px solid #EFE4CC; font: 400 12px/18px var(--moa-mono); color: var(--moa-muted); }
.moa-appr-title { font: 700 17px/24px var(--moa-font); color: var(--moa-ink); margin-top: 8px; }
.moa-appr-reco { font: 400 13px/20px var(--moa-font); color: var(--moa-muted); margin-top: 4px; }
[class*="st-key-appr_btns_"] { flex: none; flex-wrap: nowrap; gap: 16px; }
[class*="st-key-appr_btns_"] .stButton button { min-width: 62px; }
.st-key-moa_ops_row2 { flex-wrap: nowrap; gap: 17px; align-items: stretch; }
.st-key-moa_status_card { }
.st-key-moa_metric_card { }
.st-key-moa_status_card, .st-key-moa_metric_card, .st-key-moa_inc_card, .st-key-moa_ord_card {
  background: var(--moa-surface); border: 1px solid var(--moa-line); border-radius: 14px; padding: 20px 20px 12px; gap: 10px;
}
.moa-card-title { font: 700 15px/22px var(--moa-font); color: var(--moa-ink); margin-bottom: 4px; }
.st-key-moa_inc_card, .st-key-moa_ord_card { gap: 0; }
.st-key-moa_inc_card .moa-card-title, .st-key-moa_ord_head { margin-bottom: 10px; }
.st-key-moa_ops { margin-top: 0 !important; }
.moa-svc:last-child { margin-bottom: 0; }
.moa-svc { display: flex; align-items: center; gap: 10px; height: 36px; padding: 0 12px; border-radius: 10px; background: var(--moa-sunken); margin-bottom: 10px; }
.moa-svc-bad { background: var(--moa-red-soft); }
.moa-svc-dot { width: 8px; height: 8px; border-radius: 4px; background: var(--moa-green); }
.moa-svc-bad .moa-svc-dot { background: var(--moa-red-dot); }
.moa-svc-name { font: 600 13.5px/20px var(--moa-font); color: var(--moa-ink); }
.moa-svc-state { margin-left: auto; font: 600 12.5px/18px var(--moa-font); color: var(--moa-green-text); }
.moa-svc-bad .moa-svc-state { color: var(--moa-red-text); }
.moa-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.moa-metric { background: var(--moa-sunken); border-radius: 12px; height: 78px; padding: 14px 16px; }
.moa-metric span { display: block; font: 400 12px/16px var(--moa-font); color: var(--moa-muted-2); }
.moa-metric b { display: block; font: 700 26px/34px var(--moa-font); color: var(--moa-ink); margin-top: 4px; }
.moa-tr { display: grid; align-items: center; min-height: 45px; border-bottom: 1px solid var(--moa-line-faint); padding: 0 4px; }
.moa-th { min-height: 34px; border-bottom-color: var(--moa-line-soft); font: 400 12px/16px var(--moa-font); color: var(--moa-muted-3); }
.moa-td { font: 400 13.5px/20px var(--moa-font); color: var(--moa-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.moa-td-id { font: 600 12.5px/18px var(--moa-mono); color: var(--moa-ink); }
.moa-td-code { font: 400 12.5px/18px var(--moa-mono); color: var(--moa-muted); }
.moa-td-plain { color: var(--moa-ink); }
.moa-inc-grid { grid-template-columns: 132px 192px 1fr 132px 120px; }
.moa-ord-grid { grid-template-columns: 132px 152px 1fr 122px 92px 70px 32px; }
[class*="st-key-card_inc"]:hover .moa-tr, [class*="st-key-card_ord"]:hover .moa-tr { background: var(--moa-sunken); }
.moa-chev { color: var(--moa-muted-3); justify-self: end; }
.st-key-moa_ord_head { flex-wrap: nowrap; align-items: center; }
.st-key-moa_ord_head .stTextInput { width: 300px; flex: none; }
.st-key-moa_ord_head [data-testid="stTextInputRootElement"] { background: var(--moa-sunken) !important; border-color: var(--moa-bar-line) !important; border-radius: 8px !important; }
.moa-detail { background: var(--moa-sunken); border-radius: 12px; padding: 16px 16px 6px; margin: 6px 0 4px; }
.moa-detail-title { font: 700 13px/18px var(--moa-font); color: var(--moa-ink); margin-bottom: 8px; }
.moa-detail .moa-tr { min-height: 38px; border-bottom-color: var(--moa-line-soft); padding: 0; }
.moa-detail .moa-th { min-height: 28px; border-bottom-color: var(--moa-line); }
.moa-det-grid { grid-template-columns: 92px 122px 1fr 140px; }
.moa-det-who { font: 600 13px/18px var(--moa-font); color: var(--moa-ink); }
.moa-det-before { color: var(--moa-muted-3); }
.moa-det-after { color: var(--moa-ink); font-weight: 700; }
.moa-method { display: inline-flex; height: 19px; padding: 0 8px; border-radius: 10px; background: var(--moa-surface); border: 1px solid var(--moa-line-2); font: 600 11px/18px var(--moa-font); color: var(--moa-ink-3); }
.moa-inc-detail { display: grid; grid-template-columns: 120px 1fr; row-gap: 6px; font: 400 12.5px/18px var(--moa-font); color: var(--moa-ink-3); }
.moa-inc-detail span { color: var(--moa-muted-2); }
.st-key-moa_fault {
  border: 1px dashed var(--moa-line-3); border-radius: 14px; padding: 16px 20px; background: var(--moa-surface);
  flex-wrap: nowrap; align-items: center; gap: 8px;
}
.st-key-moa_fault .stButton button { min-height: 34px; height: 34px; min-width: 50px; padding: 0 12px; border-radius: 8px; font: 600 13px/18px var(--moa-font); color: var(--moa-ink-3); }
.st-key-fault_clear button { background: var(--moa-chip) !important; border-color: var(--moa-chip) !important; font-weight: 700 !important; }
.moa-fault-title { font: 700 15px/22px var(--moa-font); color: var(--moa-ink); white-space: nowrap; }
.moa-fault-title span { font: 400 12.5px/18px var(--moa-font); color: var(--moa-muted-3); margin-left: 8px; }
.st-key-moa_fault_ask { background: var(--moa-amber-card); border: 1px solid var(--moa-amber-line); border-radius: 12px; padding: 14px 18px; flex-wrap: nowrap; align-items: center; gap: 10px; }
.st-key-moa_ops_login { max-width: 420px; margin: 64px auto 0; background: var(--moa-surface); border: 1px solid var(--moa-line); border-radius: 16px; padding: 24px; }
.st-key-moa_ops_login [data-testid="stForm"] { border: none; padding: 0; }


/* 가로 배치의 폭은 Streamlit이 감싼 래퍼에 준다 — 안쪽 블록은 세로 플렉스라 flex 값이 높이가 된다 */
.st-key-moa_order > [data-testid="stLayoutWrapper"]:has(> .st-key-moa_order_main) { flex: 1 1 auto; min-width: 0; }
.st-key-moa_order > [data-testid="stLayoutWrapper"]:has(> .st-key-moa_order_side) { flex: 0 0 var(--moa-side); }
.st-key-moa_ops_row2 > [data-testid="stLayoutWrapper"]:has(> .st-key-moa_status_card) { flex: 0 0 43%; }
.st-key-moa_ops_row2 > [data-testid="stLayoutWrapper"]:has(> .st-key-moa_metric_card) { flex: 1 1 auto; min-width: 0; }
.st-key-moa_ops_row2 > [data-testid="stLayoutWrapper"] > div { height: 100%; }

/* 키 달린 블록은 기본이 flex: 1 1 0% 라 세로 높이를 0에서 시작한다 — 높이를 정한 블록은 끈다 */
.st-key-moa_panel, .st-key-moa_chatcol { flex: none !important; }
/* 행 편집 상자 폭 — 항목 id 가 세션 접두어를 달면서(ORD-0008-it_01) 예전 선택자(moa_editor_it)가 안 맞아
   상자가 주문서 패널 밖으로 넘치고 [저장]이 잘렸다(2026-11-04). 이름 칩 편집(moa_editor_group)은 제외 */
[class*="st-key-moa_editor_"]:not([class*="st-key-moa_editor_group"]) { width: calc(100% - 48px) !important; }

[class*="st-key-names_"] [class*="st-key-link_names"] .stButton button {
  border: none; background: transparent; color: var(--moa-green); padding: 0 6px; font: 600 13px/18px var(--moa-font);
}
/* ===== 좁은 화면 ===== */
@media (max-width: 860px) {
  .block-container { padding-left: 16px; padding-right: 16px; }
  .st-key-moa_work, .st-key-moa_order, .st-key-moa_ops_row2 { flex-direction: column; }
  .st-key-moa_panel, .st-key-moa_order_side, .st-key-moa_status_card { width: 100%; flex: 1 1 auto; }
  .st-key-moa_panel { height: 560px; }
  .st-key-moa_chatcol { height: auto; }
  .st-key-moa_chatlog { max-height: 70vh; }
  .moa-evidence { display: none; }
  .moa-tabs .moa-tab:not(.moa-tab-on) { display: none; }
  .moa-steps-grid { grid-template-columns: 1fr; }
  /* 주문 시작 — 배너 그림 · 아바타를 빼고 글자를 줄인다 */
  .moa-hero { height: auto; padding: 20px; }
  .moa-hero-art { display: none; }
  .moa-hero-title { font-size: 20px; line-height: 28px; }
  [class*="st-key-moa_says"] > div:first-child { display: none; }
  .st-key-moa_intro, .st-key-moa_preview { padding: 18px 16px; }
  .moa-preview-rows { grid-template-columns: 56px 1fr; }
  .st-key-moa_inputbar .stButton button { padding: 0 12px; }
  .st-key-moa_inputbar textarea { font-size: 13.5px !important; }
  .st-key-moa_inputbar textarea::placeholder { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .moa-under { font-size: 12px; }
}
"""

# Pretendard — `@import`는 스타일시트의 **첫 규칙**이어야 한다. 뒤에 두면 조용히 무시된다.
FONT_IMPORT = ('@import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard'
               '@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css");')


def inject() -> None:
    """토큰과 컴포넌트 CSS를 주입한다. 토큰은 `:root` 한 곳에 모으고 컴포넌트는 변수만 참조한다."""
    st.html(f"<style>{FONT_IMPORT}{ROOT_CSS}{COMPONENT_CSS}</style>")
