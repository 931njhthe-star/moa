"""그래프 조립 · 실행 — D-12 3절 다이어그램 그대로 (D-15).

    START → N-01 입력 가드 → N-02 묶음 → (Send × 묶음) N-03 의도분류 → N-04 경로 분기
          → (Send × add) N-05 메뉴 매칭 · (Send × ignore) N-08 → N-06 대상 연결 → N-07 규칙 검증
          → N-09 결과 반영 → N-10 출력 가드 → END
          (재개: N-02 가 Intake 저장본을 읽으면 N-03 을 건너뛰고 N-04 로 — D-12 10.4)

체크포인터를 붙이지 않는다 — 턴 사이 기억은 DB 주문 항목, 장애 재개는 order_session.checkpoint 다(D-12 10절).
상한: recursion_limit = config.GRAPH_RECURSION_LIMIT(25) · max_concurrency = config.BATCH_CONCURRENCY(4).
"""

import functools

from langgraph.graph import END, START, StateGraph

from app import config
from app.graph import nodes
from app.graph.state import RunState


@functools.lru_cache(maxsize=1)
def build():
    g = StateGraph(RunState)
    g.add_node("input_guard", nodes.input_guard_node)        # N-01
    g.add_node("batch", nodes.batch_node)                    # N-02
    g.add_node("intake", nodes.intake_node)                  # N-03
    g.add_node("route", nodes.route_node)                    # N-04
    g.add_node("menu", nodes.menu_node)                      # N-05
    g.add_node("target", nodes.target_node)                  # N-06
    g.add_node("validation", nodes.validation_node)          # N-07
    g.add_node("ignore", nodes.ignore_node)                  # N-08
    g.add_node("apply", nodes.apply_node)                    # N-09
    g.add_node("output_guard", nodes.output_guard_node)      # N-10

    g.add_edge(START, "input_guard")
    g.add_edge("input_guard", "batch")
    g.add_conditional_edges("batch", nodes.dispatch_batches_edge, ["intake", "route"])   # 재개면 N-03 건너뜀
    g.add_edge("intake", "route")
    g.add_conditional_edges("route", nodes.route_edge, ["menu", "ignore", "target"])
    g.add_edge("menu", "target")
    g.add_edge("ignore", "target")
    g.add_edge("target", "validation")
    g.add_edge("validation", "apply")
    g.add_edge("apply", "output_guard")
    g.add_edge("output_guard", END)
    return g.compile()


def run(source: str, session: dict, *, trace_id: str | None = None, text: str | None = None,
        messages: list[dict] | None = None, expected_version: int | None = None) -> dict:
    """분석(snapshot) · 채팅(chat) · 답장(reply)이 모두 여기로 들어온다 — 단일 진입 N-01 · 단일 출구 N-10."""
    if source not in ("snapshot", "chat", "reply"):
        raise ValueError(f"모르는 source: {source}")
    state = {"session": session, "source": source, "trace_id": trace_id, "text": text or "",
             "messages": messages or [], "messages_in": messages or [],
             "expected_version": expected_version}
    return build().invoke(state, config={"recursion_limit": config.GRAPH_RECURSION_LIMIT,
                                         "max_concurrency": config.BATCH_CONCURRENCY})
