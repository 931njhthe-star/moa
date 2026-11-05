"""그래프 State — D-12 1절. 경로 필드는 `route` 다(intent 가 아니다).

`RunState` 는 분석 1회, `BatchState` 는 묶음 하나(N-03 이 Send 로 받는다),
`EventState` 는 주문 이벤트 하나(N-05 가 Send 로 받는다).
턴이 끝나면 State 를 버린다 — 턴 사이 기억은 DB 주문 항목이 가진다(D-12 1.3). 그래서 체크포인터를 붙이지 않는다.
"""

import operator
from typing import Annotated, TypedDict


class RunState(TypedDict, total=False):
    # N-01 이 세션에서 읽어 고정한다 — 툴 컨텍스트의 유일한 출처(G-A3 규칙 1)
    session: dict
    source: str                       # snapshot · chat · reply (D-12 0.2)
    trace_id: str
    text: str                         # chat 원문 · reply 원문
    messages_in: list[dict]           # reply 원본(시각 등 파싱 결과 그대로) — N-09 가 저장한다
    expected_version: int | None      # chat 의 If-Match — N-09 가 쓴다
    # ★ 여기 없는 키는 LangGraph 가 **조용히 버린다**(CLAUDE.md "에러 없이 반쪽") — 새 입력은 먼저 여기 적는다
    messages: list[dict]              # 해석 대상 메시지
    existing: list[dict]              # [이미 정리된 주문] — chat · reply 의 연결 대상 후보
    batches: list[dict]               # N-02
    service: str | None               # N-02 가 고른 해석 서비스 — Menu · 보조 검토도 같은 서비스를 쓴다
    resumed: bool                     # N-02 가 Intake 저장본으로 재개했다 — N-03 건너뜀 · N-04 는 다시 저장하지 않는다
    # 병렬 결과를 합친다 (reducer)
    events: Annotated[list[dict], operator.add]
    matched: Annotated[list[dict], operator.add]
    llm_calls: Annotated[int, operator.add]
    degraded: Annotated[list[dict], operator.add]
    # 덮어쓰기
    rows: list[dict]                  # N-06 이후 항목 (snapshot)
    cancels: list[dict]               # N-06 이 정한 취소 대상
    targets: dict                     # N-06 결과 (chat · reply)
    result: dict                      # N-09 결과 — 호출부에 돌려준다
    guard: dict                       # N-10 결과


class BatchState(TypedDict):
    session: dict
    trace_id: str
    batch: dict                       # {batch_no, prev, targets, use_llm}
    existing: list[dict]


class EventState(TypedDict):
    session: dict
    event: dict
    index: int                        # 메시지 순서 — 항목 번호를 매길 때 순서를 지킨다
    events: list[dict]                # 참조 주문이 앞 메시지를 찾을 때 본다(읽기 전용)
    route: str                        # P-03 3절 슬러그 — event.event_type 과 같은 값
    service: str | None               # Menu Agent 가 부를 해석 서비스 (None 이면 규칙만)
    agent_ok: bool                    # 분석 1회 상한(MENU_AGENT_MAX_ITEMS) 안인가
    trace_id: str | None              # Menu Agent 호출 이력을 분석 1회로 묶는다 — 빠지면 llm_history.trace_id 가 빈 문자열
