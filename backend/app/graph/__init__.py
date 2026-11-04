"""업무 층 그래프 — D-12 에이전트흐름설계서의 노드 N-01 ~ N-10 (D-15).

    state.py   RunState · BatchState · EventState
    nodes.py   노드 함수 10개 + 조건부 엣지 2개 + 출력 가드 함수(그래프 밖 호출부도 같은 함수를 쓴다)
    build.py   그래프 조립 · 실행 — run(source, session, ...) 하나로 분석 · 채팅 · 답장이 들어온다

장애 대응 층은 여기 없다 — LangGraph 를 쓰지 않는 결정적 상태기계다(D-03 1.2 · D-12 9절).
"""

from app.graph.build import run

__all__ = ["run"]
