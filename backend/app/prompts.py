"""에이전트 런타임 프롬프트 — `backend/prompts/*.md` 를 읽고 조립한다 (D-11 프롬프트명세서 · D-14).

프롬프트 문장은 이 파일에 쓰지 않는다. **문장의 정본은 `prompts/*.md` 이고, 그 정본은 D-11 이다.**
문장을 바꾸려면 D-11 6절 변경 이력을 먼저 적고 `PROMPT_VERSION` 을 올린다 — llm_history.prompt_version 에 남는다.

    system_for(task)               system.md + task 별 파일 (고정 부분 — 캐시가 깨지지 않게 가변 값을 넣지 않는다)
    render_context(context, msgs)  context_tmpl.md 를 채운 user 메시지 — Intake (extract_events)
    render_agent(context, msgs)    agent_tmpl.md 를 채운 user 메시지 — 툴을 쓰는 Menu · 보조 검토의 한 왕복
"""

import functools
import pathlib

from app import config

PROMPT_VERSION = "v1.2"                      # D-11 6절의 버전과 같아야 한다 (v1.2 — menu.md 규칙 7 · 8 요청 나누기)
PROMPT_DIR = pathlib.Path(__file__).resolve().parent.parent / "prompts"

# DEP-001 task → 작업 프롬프트 파일 (D-11 0절 표)
TASK_PROMPTS = {"extract_events": "classify.md", "normalize_menu": "menu.md", "review": "review.md"}

# 화면용 매장 라벨 — 프롬프트에는 brand_id 를 넣지 않는다(D-11 5절 · D-10 G-A3 규칙 1)
BRAND_LABELS = {"starbucks": "스타벅스 메뉴 기준", "generic": "일반 카페 메뉴 기준"}


@functools.lru_cache(maxsize=None)
def load(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def system_for(task: str) -> str:
    if task not in TASK_PROMPTS:
        raise KeyError(f"프롬프트가 없는 task: {task}")
    return load("system.md") + "\n\n" + load(TASK_PROMPTS[task])


def _fill(template: str, values: dict, rows: dict[str, list[str]]) -> str:
    """[섹션] 아래의 자리표시 줄은 행 틀이다 — 그 섹션의 행 수만큼 반복하고, 비면 "없음" 한 줄.

    섹션은 빈 줄에서 끝난다 — 끝나지 않으면 마지막 섹션 뒤의 안내 줄("남은 툴 왕복: {remaining}번")까지
    행 틀로 읽혀 "없음"으로 바뀐다(실제로 그랬다 — tests/test_agents.py).
    """
    out, section = [], None
    for line in template.splitlines():
        if not line.strip():
            section = None
            out.append(line)
        elif line.startswith("[") and line.endswith("]"):
            section = line
            out.append(line)
        elif section in rows and "{" in line:
            out.extend(rows[section] or ["없음"])
        else:
            out.append(line.format(**values) if "{" in line else line)
    return "\n".join(out)


def render_agent(context: dict, messages: list[dict]) -> str:
    """agent_tmpl.md — 툴을 쓰는 에이전트(Menu · 보조 검토)의 한 왕복 입력.

    context["agent"] = {items: [{item_ref, summary}], tools: [{name, description, params}],
                        transcript: [{tool, args, result}], remaining: int}
    매장 · 세션 식별자는 넣지 않는다 — 툴이 세션에서 주입받는다(D-10 G-A3 규칙 1).
    """
    agent = context.get("agent") or {}
    rows = {
        "[대화]": [_message_row(m) for m in messages],
        "[확인할 항목]": [f"{i['item_ref']}: {i['summary']}" for i in agent.get("items") or []],
        "[쓸 수 있는 툴]": [f"{t['name']}: {t['description']} 인자: {t['params']}" for t in agent.get("tools") or []],
        "[지금까지 부른 툴]": [f"{n}. {c['tool']} {c['args']} → {c['result']}"
                          for n, c in enumerate(agent.get("transcript") or [], start=1)],
    }
    values = {"brand_label": BRAND_LABELS.get(context.get("brand_id"), BRAND_LABELS["generic"]),
              "menu_as_of": context.get("menu_as_of") or config.MENU_AS_OF,
              "remaining": max(0, int(agent.get("remaining", 0)))}
    return _fill(load("agent_tmpl.md"), values, rows)


def render_context(context: dict, messages: list[dict]) -> str:
    """context_tmpl.md 를 채운다. 목록 칸은 행 틀을 항목 수만큼 반복하고, 비면 "없음" 한 줄.

    context
      brand_id        → 라벨로만 바꿔 넣는다(식별자 자체는 넣지 않는다)
      menu_as_of      없으면 config.MENU_AS_OF
      existing_items  [이미 정리된 주문] — {message_id, person, menu_text, quantity, options}
      prev_messages   [앞 메시지] — 해석하지 않는 선행 문맥
    messages          [이번에 해석할 메시지]
    """
    rows = {
        "[이미 정리된 주문]": [_order_row(i) for i in context.get("existing_items") or []],
        "[앞 메시지]": [_message_row(m) for m in context.get("prev_messages") or []],
        "[이번에 해석할 메시지]": [_message_row(m) for m in messages],
    }
    values = {"brand_label": BRAND_LABELS.get(context.get("brand_id"), BRAND_LABELS["generic"]),
              "menu_as_of": context.get("menu_as_of") or config.MENU_AS_OF}

    return _fill(load("context_tmpl.md"), values, rows)


def _message_row(m: dict) -> str:
    return f"{m['message_id']} [{m.get('sender', '')}] {m.get('text', '')}"


def _order_row(item: dict) -> str:
    options = item.get("options") or ""
    if isinstance(options, dict):
        options = " ".join(str(v) for v in options.values())
    elif isinstance(options, list):
        options = " ".join(str(v) for v in options)
    return (f"{item.get('message_id', '')} {item.get('person', '')}: {item.get('menu_text', '')} "
            f"{item.get('quantity', 1)}잔 {options}").rstrip()
