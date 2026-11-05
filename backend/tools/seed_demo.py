"""시연용 업무 데이터 — 주문 세션 3건을 **서비스 계층을 태워** 만든다.

SQL 로 직접 넣지 않는 이유: order_item · order_event · review_question ·
settlement_line 이 서로 맞아야 하고(v_settlement_check · 금지 조합 검사),
손으로 넣으면 정합성이 어긋난 데이터가 들어가 검수가 거짓 통과한다.

    python tools/seed_demo.py           # 3건 생성
    python tools/seed_demo.py --clean   # 시연 세션 삭제

세션 3건의 성격을 일부러 다르게 둔다.
  1 스타벅스 · 확인 필요 남음        — 화면 B 확인 질문을 볼 수 있다
  2 일반 카페 · 전부 해소 후 공유 완료 — 화면 E · O-6 "주문 확정"을 볼 수 있다
  3 매장 되묻기 대기                  — 되묻기 모달을 볼 수 있다
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import db, logging_setup                                     # noqa: E402
from app.services import brand_flow, completion, edits                # noqa: E402
from app.services import order_sheet, questions, sessions             # noqa: E402

CONVERSATIONS = [
    # 1 스타벅스 — 확인 필요가 남는다 (모호한 사이즈 · 참조 주문)
    ("스타벅스 세션 · 확인 필요", "\n".join([
        "[김민수] 아이스 아메리카노 톨 2잔, 하나는 샷 추가요.",
        "[이지연] 바닐라라떼 큰 거 얼음 적게요.",
        "[박서연] 아아 톨 한 잔이요. 빨대는 빼 주시고 개인 텀블러에 담아 주세요.",
        "[최유나] 여기 인기 있는 메뉴 뭐야?",
        "[정하준] 민트 초코가 유명하대",
        "[최유나] 그럼 난 그걸로 하나~",
        "스타벅스로 갈 예정이야",
    ]), "leave_review"),

    # 2 일반 카페 — 전부 해소하고 공유 완료까지 간다
    ("일반 카페 세션 · 공유 완료", "\n".join([
        "[한소희] 아이스 아메리카노 레귤러 한 잔",
        "[오태민] 아이스 라떼 라지 얼음 많이요",
        "[윤가람] 아이스티 한 잔이요",
        "동네카페에서 사올게",
    ]), "resolve_and_share"),

    # 3 매장이 2종 이상 — 되묻기 대기로 남긴다
    ("되묻기 대기 세션", "\n".join([
        "[서지후] 스타벅스 아아 한 잔",
        "[임나래] 나는 메가커피 아이스티",
    ]), "leave_awaiting"),
]


def clean() -> None:
    rows = db.fetch_all(
        "SELECT s.session_id FROM app.order_session s "
        "  JOIN app.snapshot sn ON sn.session_id = s.session_id "
        " WHERE sn.raw_text LIKE '%스타벅스로 갈 예정이야%' "
        "    OR sn.raw_text LIKE '%동네카페에서 사올게%' "
        "    OR sn.raw_text LIKE '%메가커피 아이스티%'")
    for row in rows:
        db.execute("DELETE FROM app.order_session WHERE session_id = %s",
                   (row["session_id"],))
    print(f"시연 세션 {len(rows)}건 삭제")


def resolve_all(session_id: str, token: str) -> None:
    """확인 질문을 전부 답해 공유 가능 상태로 만든다.

    **항목을 지우지 않는다.** 지우면 주문이 사라져 시연 데이터가 "1잔짜리 주문"이 되고,
    검수에서 금액 · 묶음을 볼 수 없다. 질문에 후보가 없으면 메뉴를 직접 지정한다.
    """
    for _ in range(12):
        pack = questions.projection(session_id)
        question = pack.get("question")
        if not question:
            break
        options = question.get("options") or []
        answered = False
        if options:
            try:
                edits.answer_question(sessions.load(session_id, token),
                                      question["question_id"], options[0]["value"],
                                      expected_version=None)
                answered = True
            except edits.NotApplicable:
                answered = False
        if not answered:
            # 후보가 없거나 답이 반영되지 않는 질문 — 항목에 메뉴 · 사이즈를 직접 지정한다
            session = sessions.load(session_id, token)
            _force_resolve(session, question["item_id"])
            db.execute("UPDATE app.review_question SET status = 'voided' "
                       " WHERE question_id = %s", (question["question_id"],))

    for row in sessions.items(session_id):
        if row["validation_status"] != "passed":
            _force_resolve(sessions.load(session_id, token), row["item_id"])


def _force_resolve(session: dict, item_id: str) -> None:
    """메뉴와 사이즈를 지정해 확인 필요를 해소한다. 매장 기준에 맞는 용어를 쓴다."""
    size = "tall" if session["brand_id"] == "starbucks" else "regular"
    for name in ("아이스 아메리카노", "아이스 카페 라떼"):
        try:
            edits.patch_item(session, item_id,
                             {"menu_name": name, "options": {"size": size}},
                             expected_version=None)
            return
        except edits.NotApplicable:
            continue


def main() -> None:
    logging_setup.setup()
    if "--clean" in sys.argv:
        clean()
        return

    clean()
    made = []
    for label, raw_text, mode in CONVERSATIONS:
        trace_id = logging_setup.new_trace_id()
        started = brand_flow.start(raw_text, source="sample", trace_id=trace_id)

        if started["kind"] == "awaiting_brand":
            print(f'[생성] {started["session_id"]}  {label}  (status=awaiting_brand_answer)')
            print(f'       X-Session-Token: {started["session_token"]}')
            made.append(started["session_id"])
            continue

        session_id, token = started["session_id"], started["session_token"]
        sessions.run_pipeline(session_id, trace_id=trace_id)

        if mode == "resolve_and_share":
            resolve_all(session_id, token)
            gate = order_sheet.can_share(session_id)
            if gate["can_share"]:
                completion.complete(sessions.load(session_id, token), "text")
            else:
                print(f'  [주의] 공유 불가: {gate["blocked_reason_text"]}')

        session = sessions.load(session_id, token)
        pending = sessions.review_count(session_id)
        print(f'[생성] {session_id}  {label}  status={session["status"]} '
              f'항목={len(sessions.items(session_id))} 확인필요={pending}')
        # 토큰은 해시로만 저장된다 — 여기서 놓치면 이 세션을 API 로 다시 열 수 없다
        print(f"       X-Session-Token: {token}")
        made.append(session_id)

    print(f"\n업무 세션 {len(made)}건: {', '.join(made)}")
    print("운영 대시보드 사건 데이터는 sql/14_seed_demo.sql 이 넣는다")


if __name__ == "__main__":
    main()
