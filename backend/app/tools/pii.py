"""PII 마스킹 — LLM 요청 본문에 원본 식별정보 0건 (CLAUDE.md 배포 체크리스트 6 · 교안코드규약 4.10).

참여자 이름은 가명이지만(PRD 2.5) 대화 · 기타 요청에 연락처 · 계좌가 섞여 들어올 수 있다.
  - `mask_pii`     문자열 하나 — 툴 반환의 자유 입력 칸(D-10 초판)
  - `mask_payload` 주문 해석 서비스(DEP-001)로 가는 요청 본문 전체(D-13) — LLM 으로 나가는 **유일한 경계**인
                   `interpreter_client.interpret` 가 보내기 직전에 부른다. 경로 노드마다 따로 부르지 않는다
"""

import re

# 긴 패턴부터 — 카드번호가 전화번호로 먼저 잘리지 않게
PII_PATTERNS = {
    "카드번호": r"(?<!\d)\d{4}-?\d{4}-?\d{4}-?\d{4}(?!\d)",
    "주민번호": r"(?<!\d)\d{6}-?[1-4]\d{6}(?!\d)",
    "전화번호": r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)",
    "계좌번호": r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,8}(?!\d)",
    "이메일": r"[\w.+-]+@[\w-]+\.[\w.-]+",
}

# 계좌번호는 숫자 10자리 이상만 — "2026-11-03"(8자리) 같은 날짜를 가리면 픽업 일정이 사라진다
_MIN_DIGITS = {"계좌번호": 10}

# 가리지 않는 키 — 업무 식별자 · 계약 값이다. 가리면 근거 연결(message_id)이 끊긴다
_KEEP_KEYS = frozenset({"message_id", "evidence_message_ids", "item_id", "menu_id", "schema",
                        "task", "trace_id", "brand_id", "menu_version", "order", "seq"})


def _replace(name: str):
    def repl(m: re.Match) -> str:
        if sum(c.isdigit() for c in m.group()) < _MIN_DIGITS.get(name, 0):
            return m.group()
        return f"[{name} 가림]"
    return repl


def mask_pii(text: str | None) -> tuple[str | None, list[str]]:
    """(마스킹된 문자열, 찾은 종류). 찾은 종류는 로그 · 감사용이다 — 원문은 남기지 않는다."""
    if not text:
        return text, []
    masked, found = text, []
    for name, pattern in PII_PATTERNS.items():
        replaced = re.sub(pattern, _replace(name), masked)
        if replaced != masked:
            found.append(name)
            masked = replaced
    return masked, found


def mask_payload(value, *, _key: str | None = None):
    """dict · list · str 를 재귀로 돌며 문자열 값만 가린다. (가린 값, 찾은 종류 목록)."""
    if isinstance(value, str):
        return (value, []) if _key in _KEEP_KEYS else mask_pii(value)
    if isinstance(value, dict):
        out, found = {}, []
        for k, v in value.items():
            if k in _KEEP_KEYS:
                out[k] = v
                continue
            out[k], f = mask_payload(v, _key=k)
            found += f
        return out, found
    if isinstance(value, list):
        out, found = [], []
        for v in value:
            masked, f = mask_payload(v, _key=_key)
            out.append(masked)
            found += f
        return out, found
    return value, []
