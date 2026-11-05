"""기준 정보와 예시 대화 — API-002 · API-010.

가격 기준 고지 문구는 **서버가 완성형으로** 준다. 화면이 날짜를 조립하면
고지 문구가 화면마다 달라진다 (P-06 규제 고지 반영).
"""

from app import config, db
from app.services import brand as brand_service

# API-010 예시 대화 — 정본 시안 SCR-001 케이스 02 (5명 · 메시지 8개)
_SAMPLE = [
    ("김민수", "아이스 아메리카노 톨 2잔, 하나는 샷 추가요."),
    ("이지연", "바닐라라떼 큰 거 얼음 적게요."),
    ("박서연", "아아 톨 한 잔이요. 빨대는 빼 주시고 개인 텀블러에 담아 주세요, "
               "얼음은 컵 반만 채워 주시면 좋겠어요!"),
    ("최유나", "여기 인기 있는 메뉴 뭐야?"),
    ("정하준", "민트 초코가 유명하대"),
    ("최유나", "그럼 난 그걸로 하나~"),
    ("김민수", "아까 샷 추가한 한 잔 취소할게요."),
    ("정하준", "나도 민수랑 같은 걸로!"),
]

# 대화 끝 매장 요청 한 줄 — 메시지가 아니다(보낸 사람 없음). 매장 기준 판별에서 대화보다 우선한다
# (PRD 2.4.1 · 8절 기준 입력과 같은 형태). 없으면 일반 카페로 정리되어 "톨" 주문이 전부 사이즈 질문이 된다
SAMPLE_STORE_REQUEST = "스타벅스로 갈 예정이야"


def meta_view() -> dict:
    """API-002 — 기준 정보. 메뉴 기준일은 DB 의 실제 적재 상태에서 읽는다."""
    as_of = config.MENU_AS_OF
    try:
        row = db.fetch_one(
            "SELECT MIN(created_at) AS first_loaded, COUNT(*) AS n FROM app.menu "
            " WHERE menu_version = %s", (config.MENU_VERSION,))
        loaded = int(row["n"]) if row else 0
    except db.DbUnavailable:
        loaded = 0

    pretty = as_of.replace("-", ".")
    return {
        "menu_as_of": as_of,
        "menu_version": config.MENU_VERSION,
        "menu_loaded": loaded,
        "price_notice": f"메뉴와 가격은 {pretty} 기준이며 실제와 다를 수 있어요",
        "brands": [{"id": key, "label": label}
                   for key, label in brand_service.BRAND_LABEL.items()],
        "limits": {
            "max_messages": config.MAX_MESSAGES,
            "max_bytes": config.MAX_INPUT_BYTES,
            "poll_interval_ms": 1000,
        },
        "ops_poll_interval_ms": 5000,
    }


def sample_conversation() -> dict:
    """API-010 — 예시 대화. 파일에서 읽지 않고 상수로 둔다(DB 를 쓰지 않는 엔드포인트)."""
    people = sorted({sender for sender, _ in _SAMPLE})
    return {
        "title": "예시 대화",
        "is_sample": True,
        "raw_text": "\n".join([f"[{sender}] {text}" for sender, text in _SAMPLE]
                              + [SAMPLE_STORE_REQUEST]),
        "store_request": SAMPLE_STORE_REQUEST,
        "messages": [{"message_id": f"m{index}", "order": index, "sender": sender, "text": text}
                     for index, (sender, text) in enumerate(_SAMPLE, start=1)],
        "summary_text": f"{len(people)}명 · 메시지 {len(_SAMPLE)}개를 읽었어요",
    }
