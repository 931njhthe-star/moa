"""계약 클래스 — 에이전트와 주문 해석 서비스가 주고받는 산출물의 모양 (교안코드규약 3.2 ~ 3.4).

규약 3가지
  1 이름은 산출물 명사다 (OrderEvent · MenuMatch · ValidationResult)
  2 모든 필드에 description 을 붙인다 — **설명이 곧 지시다.** 출력 형식을 프롬프트에 쓰지 않는다
  3 근거 필드를 판정 필드보다 먼저 둔다 — 필드 순서가 생각 순서다
     (OrderEvent: evidence_message_ids → target_message_id → reason → event_type → person)

이 파일의 모델이 `llm.generate_structured(..., schema)` 의 스키마이자, 서비스가 돌려준 값을
**우리 쪽에서 다시 검증하는 기준**이다(D-03 1.3 · F-011). 서비스 · 모델을 믿지 않는다.

이벤트 경로 5종 슬러그는 P-03 3절이 정본이다 — State · 분류기 라벨 · Q-02 가 같은 문자열을 쓴다.
"""

from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal["add", "update", "cancel", "confirm", "ignore"]


class OrderItemDraft(BaseModel):
    """메시지 한 건에서 읽은 주문 항목 하나. 메뉴판과 맞추기 전 원문 표현이다."""

    menu_text: str = Field(description="메시지에 적힌 메뉴 표현 원문. 줄임말(아아 · 아바라)도 고치지 말고 그대로")
    temperature_text: str | None = Field(
        description="온도 표현 원문(아이스 · 따뜻한 · 차가운 등). 말하지 않았으면 null")
    size_text: str | None = Field(
        description="사이즈 표현 원문(톨 · 그란데 · 큰 거 등). 말하지 않았으면 null. 추정하지 않는다")
    quantity: int = Field(description="잔 수. 적힌 숫자를 그대로 쓴다(0 · 음수도 고치지 않는다). 말하지 않았으면 1")
    option_texts: list[str] = Field(
        description="메뉴판 옵션으로 보이는 표현 원문 목록(샷 추가 · 얼음 적게 · 두유 등). 없으면 빈 목록")
    custom_request: str | None = Field(
        description="메뉴판에 없는 부탁 원문(빨대 빼기 · 텀블러에 담기 등). 금액과 무관. 없으면 null")


class OrderEvent(BaseModel):
    """주문 의도 하나의 해석 결과 — 주문 이벤트 (P-03 3절 경로 5종 · 1.1 의도 단위)."""

    message_id: str = Field(description="해석한 메시지의 message_id. 입력에 있던 값을 그대로")
    evidence_message_ids: list[str] = Field(
        description="이 판단의 근거가 된 메시지 id 목록. 자기 메시지 + '그걸로' 같은 말이 가리키는 앞 메시지")
    target_message_id: str | None = Field(
        description="update · cancel · confirm 이 가리키는 기존 주문의 message_id. add · ignore 는 null")
    reason: str = Field(description="event_type 을 그렇게 정한 이유 한 줄. 한국어")
    event_type: EventType = Field(
        description="add=새 주문 · update=이미 한 주문 변경 · cancel=이미 한 주문 빼기 · "
                    "confirm=이미 한 주문을 그대로 둔다는 대답 · ignore=질문 · 잡담 · 주문과 무관한 말")
    person: str | None = Field(
        description="그 주문을 받을 사람(가명). 보통 발신자, '서연이 것도'처럼 다른 사람을 가리키면 그 사람")
    person_unclear: bool = Field(description="주문을 받을 사람이 확실하지 않으면 true")
    target_unclear: bool = Field(
        description="가리키는 기존 주문이 둘 이상일 수 있으면 true. 임의로 하나를 고르지 않는다")
    is_reference: bool = Field(
        description="'그걸로' · '나도 같은 걸로'처럼 앞 메시지의 메뉴를 가리키면 true")
    items: list[OrderItemDraft] = Field(
        description="add · update 일 때 읽은 항목. cancel 은 일부를 뺄 때만 뺄 잔. confirm · ignore 는 빈 목록")


class OrderEvents(BaseModel):
    """extract_events 작업의 결과 — 주문 의도마다 이벤트 하나씩."""

    events: list[OrderEvent] = Field(
        description="주문 의도마다 하나씩 — 메시지 하나가 여럿을 낼 수 있다. "
                    "[이번에 해석할 메시지]의 메시지마다 하나 이상, [앞 메시지]는 만들지 않는다")


class MenuCandidate(BaseModel):
    """메뉴 후보 하나 — 툴(search_menu · find_menu_by_traits)이 돌려준 값만."""

    menu_id: str = Field(description="툴 결과에 있던 menu_id. 툴 결과에 없는 값을 쓰지 않는다")
    reason_tags: list[str] = Field(description="이 후보를 고른 근거(별칭 일치 · 특성 태그 등)")


class OptionChoice(BaseModel):
    """옵션 값 하나. strict 스키마는 자유 키 사전을 받지 않으므로 그룹 · 값 쌍으로 쓴다."""

    group: str = Field(description="get_menu 가 돌려준 옵션 그룹 이름")
    value: str = Field(description="get_menu 의 값 중 표현과 분명히 같은 것")


class MenuMatch(BaseModel):
    """항목 하나를 메뉴판과 맞춘 결과 (D-11 4.2). 가격 칸이 없다 — 금액은 규칙이 계산한다."""

    item_ref: str = Field(description="입력 항목을 가리키는 값. 입력에 있던 값을 그대로")
    candidates: list[MenuCandidate] = Field(description="그럴듯한 후보 전부. 없으면 빈 목록")
    reason: str = Field(description="menu_id 를 채우거나 비운 이유 한 줄. 한국어")
    menu_id: str | None = Field(description="하나로 확실할 때만 채운다. 후보가 둘 이상이거나 취향만 말했으면 null")
    options: list[OptionChoice] = Field(description="표현과 분명히 같은 옵션 값만. 모호하면 넣지 않는다")
    unclear: list[str] = Field(description="확인이 필요한 칸 이름(menu · size · temperature 등). 없으면 빈 목록")
    # 메뉴 표현에 메뉴판 옵션이 아닌 요청이 섞여 메뉴를 못 정했을 때만 채운다(2026-11-04 · D-11 v1.2).
    # 둘 다 원문 발췌여야 한다 — 코드가 원문에 있는지 확인하고, 메뉴는 menu_text 로 **규칙이 다시** 맞춘다
    menu_text: str | None = Field(
        description="원문에서 메뉴를 가리키는 부분만 그대로 발췌. 요청이 섞여 있지 않으면 null")
    custom_request: str | None = Field(
        description="원문에서 메뉴판에 없는 요청(시럽 종류 · 우유 종류 · 휘핑 · 드리즐 · 펌프 등) 부분만 그대로 발췌. "
                    "맛 이름만 붙은 메뉴 표현(헤이즐넛 라떼)은 요청이 아니다. 없으면 null")


class MenuMatches(BaseModel):
    """normalize_menu 작업의 결과."""

    matches: list[MenuMatch] = Field(description="입력 항목마다 하나씩")


class ReviewVerdict(BaseModel):
    """보조 검토 의견 하나 (D-11 4.3). **판정 권한이 없다** — llm_review_verdict 로만 저장된다."""

    item_id: str = Field(description="검토한 주문 항목의 item_id. 입력에 있던 값을 그대로")
    evidence_message_ids: list[str] = Field(description="의견의 근거가 된 메시지 id 목록")
    target_item_ids: list[str] = Field(
        description="수정 · 취소가 가리키는 item_id. 하나로 좁혀지면 하나, 둘 이상이면 모두")
    reason: str = Field(description="확인이 필요한 이유 한 줄. 담당자가 알아볼 수 있게. 금액은 적지 않는다")
    verdict: Literal["agree", "disagree", "unsure"] = Field(
        description="규칙 판정에 대한 참고 의견. 통과 · 확정 결정이 아니다")


class ReviewVerdicts(BaseModel):
    """review 작업의 결과."""

    verdicts: list[ReviewVerdict] = Field(description="입력 항목마다 하나씩")


# --- 툴을 쓰는 에이전트의 한 왕복 (D-13 전문가 루프 · D-15 배선) ---------------------------------------
# 툴 호출을 해석 서비스가 중계한다 — LLM 은 "툴을 하나 더 부른다" 또는 "결론을 낸다" 중 하나를 고른다.
# 실행은 우리 코드(tools.call)가 하고, 결과를 다음 왕복의 입력에 붙인다. provider 고유의 툴 호출 기능에 기대지 않는다
# (llm.py 의 generate_structured 하나로 openai · anthropic · ollama 가 같게 돈다 — D-03 3.1).
MenuTool = Literal["search_menu", "find_menu_by_traits", "get_menu"]
ReviewTool = Literal["list_order_items", "get_order_item", "get_menu"]


class MenuStep(BaseModel):
    """normalize_menu 한 왕복 — Menu Agent. 결론(matches)은 MenuMatches 와 같은 모양이다."""

    reason: str = Field(description="이번에 툴을 부르거나 결론을 내는 이유 한 줄. 한국어")
    action: Literal["call_tool", "finish"] = Field(
        description="call_tool=툴을 하나 더 부른다 · finish=결론을 낸다. 남은 툴 왕복이 0이면 반드시 finish")
    tool: MenuTool | None = Field(description="call_tool 일 때 부를 툴 이름. finish 면 null")
    args_json: str | None = Field(
        description='툴 인자 JSON 문자열(예: {"query": "민트 초코"}). 매장 · 대화 정보는 넣지 않는다. finish 면 null')
    matches: list[MenuMatch] = Field(description="finish 일 때 항목마다 결론. call_tool 이면 빈 목록")


class ReviewStep(BaseModel):
    """review 한 왕복 — Validation 보조 검토. 결론(verdicts)은 ReviewVerdicts 와 같은 모양이다. 판정 권한이 없다."""

    reason: str = Field(description="이번에 툴을 부르거나 결론을 내는 이유 한 줄. 한국어")
    action: Literal["call_tool", "finish"] = Field(
        description="call_tool=툴을 하나 더 부른다 · finish=의견을 낸다. 남은 툴 왕복이 0이면 반드시 finish")
    tool: ReviewTool | None = Field(description="call_tool 일 때 부를 툴 이름. finish 면 null")
    args_json: str | None = Field(
        description='툴 인자 JSON 문자열(예: {"item_id": "ORD-0001-it_02"}). 인자가 없으면 "{}". finish 면 null')
    verdicts: list[ReviewVerdict] = Field(description="finish 일 때 항목마다 의견. call_tool 이면 빈 목록")


# DEP-001 task → 결과 계약. 계약이 없는 task 는 받지 않는다
TASK_CONTRACTS: dict[str, type[BaseModel]] = {
    "extract_events": OrderEvents,
    # 툴을 쓰는 두 task 는 한 왕복 계약으로 주고받는다 — 결론 부분이 MenuMatches · ReviewVerdicts 와 같다.
    # task 이름은 llm_history.task CHECK(extract_events · normalize_menu · review)와 같아야 한다 — 다르면 이력이 조용히 0건
    "normalize_menu": MenuStep,
    "review": ReviewStep,
}
