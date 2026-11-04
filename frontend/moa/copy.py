# 화면 문구 상수 — 출처는 P-06 화면설계서 v3.0과 정본 시안
# `Moa_전체화면.svg`(23케이스, 2026-11-03 판)다.
#
# 여기에 두는 것은 **화면 틀의 고정 문구**뿐이다.
# 서버가 만드는 문구(상태 줄 · 매장 기준 근거 · 반영 안내 · 공유 불가 이유 ·
# 가격 기준 고지)는 상수로 두지 않고 API 응답 필드를 그대로 그린다
# (P-06 프론트엔드 원칙 · D-02 2.2 `user_message`).
#
# 말투는 해요체 · 쉬운 말 한 줄이며(P-06 U-12 · NFR-014 (3)),
# 내부 용어(세션 · 토큰 · 주문 이벤트 · Snapshot · 검증 · NEEDS_REVIEW ·
# brand_id · 에이전트 이름)는 0건이다(U-7).

APP_NAME = "Moa"
LOGO_WORD = "moa"
# 헤더 단계 표시 — 누르는 탭이 아니라 지금 어느 단계인지 보여주는 표시다(P-06 U-2: 이동은 하단 바로만)
TABS = [("A", "주문 시작", "start"), ("B", "주문 정리", "review"), ("E", "주문서", "order")]

# --- 공통 (P-06 공통 레이아웃) ------------------------------------------------
OPS_ENTRY_BUTTON = "운영 대시보드"
# 가격 기준 고지는 서버가 완성 문구로 준다(API-002 `price_notice`).
# 서버에 닿지 못했을 때만 쓰는 대체 문구다.
PRICE_NOTICE_FALLBACK = "메뉴와 가격은 2026.10.29 기준이며 실제와 다를 수 있어요"

# --- SCR-001. A. 주문 시작 (케이스 01 ~ 07) -----------------------------------
S1_STATUS = "단톡방 대화를 붙여넣고 [정리하기]만 누르면 돼요"
S1_HERO_KICKER = "모임 커피 주문 정리"
S1_HERO_TITLE = ["흩어진 주문을", "한 장으로 모아요"]
S1_GREETING = "안녕하세요! 모임 커피 주문을 대신 정리해 주는 Moa예요"
S1_WHAT = (
    "단톡방 대화를 붙여넣고 **[정리하기]** 만 누르면 누가 뭘 시켰는지 사람별로 "
    "정리해 드려요. 매장은 따로 고르지 않아도 대화에서 찾아요."
)
S1_STEPS_TITLE = "이렇게 진행돼요"
S1_STEPS = [
    "대화 붙여넣기 또는 .txt 파일 올리기",
    "확인이 필요한 주문만 골라 주기",
    "주문서 · 정산을 텍스트나 이미지로 공유",
    "단톡방에 공유하고 바꿀 것만 답장 받기",
]
S1_FORMAT_TITLE = "대화는 이런 형식이면 돼요"
S1_FORMAT_EXAMPLES = [
    "[김민수] 아이스 아메리카노 톨 2잔이요",
    "[이지연] 바닐라라떼 큰 거 얼음 적게요",
]
S1_QUICK_SAMPLE = "예시로 채워보기"
S1_PREVIEW_TITLE_PASTE = "넣은 대화 미리보기"
S1_PREVIEW_TITLE_SAMPLE = "예시 대화"
S1_PREVIEW_BADGE_SAMPLE = "예시"
S1_PREVIEW_CLEAR = "지우기"
S1_PREVIEW_LOADING = "대화를 불러오고 있어요"
S1_UNREADABLE_LABEL = "읽지 못한 줄"
S1_INPUT_PLACEHOLDER = "단톡방 대화를 붙여넣거나 .txt 파일을 끌어다 놓아 주세요"
S1_FILE_LABEL = "대화 불러오기"
# Streamlit은 드래그 상태를 감지해 자리표시를 바꿀 수 없다 → 드롭 영역 안내로 대신한다
# (P-06 Streamlit 구현 대응 "입력창 위 드롭 자리표시 전환" 행)
S1_DROP_HINT = "여기에 .txt 대화 파일을 놓아도 돼요"
S1_SUBMIT = "정리하기"
# 누르는 동안 문구를 띄우지 않는다 — 돌아가는 표시만 남긴다(2026-11-03 요청)
S1_SUBMIT_DISABLED_REASON = "대화를 먼저 넣어 주세요"
S1_STORE_CAPTION = '매장 요청은 선택이에요 · 대화 끝에 "스타벅스 기준으로 정리해줘"처럼 적으면 돼요'
S1_SAMPLE_REPLACE_ASK = "지금 내용을 바꿀까요?"
# Ctrl/Cmd + Enter는 값 반영까지만 하고 버튼을 누르지 않는다(P-06 Streamlit 구현 대응)
S1_SUBMIT_HELP = "Enter는 줄바꿈이에요. 정리는 [정리하기]를 눌러 시작해 주세요"

# 매장 되묻기 모달 (케이스 06 · 07) — 질문 · 선택지 · 안내는 서버가 준다(API-012
# `brand_question`). 아래는 모달 제목처럼 틀에 속하는 문구다.
S1_BRAND_DIALOG_TITLE = "어디 기준으로 정리할까요?"
# 서버가 `subtitle_text`를 주지 않을 때만 쓰는 대체 문구
S1_BRAND_SUBTITLE_FALLBACK = "대화에 스타벅스와 다른 매장이 함께 나와요"
S1_BRAND_FOUND_LABEL = "대화에서 찾은 매장"
# 선택지 설명 — 선택지가 고정 3종이라 틀 문구로 둔다(서버가 `description`을 주면 그것이 먼저다)
S1_BRAND_OPTION_DESC = {
    "starbucks": "스타벅스 메뉴판과 가격으로 정리해요",
    "generic": "흔한 카페 메뉴로 정리하고 예상 금액으로 보여줘요",
    "other": "매장 이름을 직접 적어 주세요",
}
S1_BRAND_OTHER_TITLE = "기타 매장"
S1_BRAND_OTHER_PLACEHOLDER = "매장 이름"
S1_BRAND_OTHER_SUBMIT = "이 매장으로 정리"

# --- SCR-002. B. 주문 정리 (케이스 08 ~ 17) -----------------------------------
S2_INPUT_LABEL = "넣은 대화"
S2_INPUT_VIEW_RAW = "원본 보기"
S2_INPUT_REENTER = "다시 넣기"
S2_PROGRESS_EXPAND = "펼치기"
S2_PROGRESS_COLLAPSE = "접기"
S2_PANEL_TITLE = "주문서"
S2_PANEL_EMPTY = "정리가 끝나면 사람별 주문이 여기에 보여요"
S2_REVIEW_BADGE = "확인 {n}"
S2_ROW_REVIEW = "확인 필요"
S2_BUSY_HINT = "정리가 끝나면 볼 수 있어요"
S2_REMAINING_HINT = "확인할 것이 {n}건 남았어요"
S2_PANEL_EDIT_SAVE = "저장"
S2_PANEL_EDIT_MENU = "메뉴 바꾸기"
S2_PANEL_EDIT_REMOVE = "빼기"
S2_PANEL_CUSTOM_LABEL = "기타 요청"
S2_CHAT_PLACEHOLDER = "답하거나 고칠 것을 적어 주세요 (예: 서연이 라떼로 바꿔줘)"
S2_CHAT_PLACEHOLDER_BUSY = "정리가 끝나면 답할 수 있어요"
S2_CHAT_SEND = "보내기"
S2_QUICK_VIEW_EVIDENCE = "대화 보기"
S2_QUICK_OTHER_MENU = "다른 메뉴"
S2_UNDO = "되돌리기"
S2_BACK = "대화 넣기로"
S2_PRIMARY = "주문서 보기"
S2_BRAND_CHANGE_YES = "새로 정리"
S2_BRAND_CHANGE_NO = "아니요"
# 정본 시안 케이스 15의 제목은 "메뉴를 찾아 주세요"다(P-06 본문 그림의 "메뉴 찾기"와 다르다 — 시안이 정본)
S2_MENU_DIALOG_TITLE = "메뉴를 찾아 주세요"
S2_MENU_SEARCH_PLACEHOLDER = "메뉴 이름으로 찾기"
S2_ALL_DONE = "확인할 것을 모두 끝냈어요. 이제 단톡방에 확인 받으러 가요"
S2_LINK_COPY = "링크 복사"
S2_MOBILE_PANEL_PRIMARY = "주문서 보기"
S2_LINK_INVALID_HOME = "처음으로"
S2_LINK_INVALID = "이 링크는 더 이상 쓸 수 없어요. 처음부터 다시 정리해 주세요"
# 새로고침 · 새 탭 — 주소의 관리 토큰은 남지만 정리 결과는 브라우저 세션에만 있었다.
# 토큰으로 세션을 찾는 경로가 아직 없어(D-02 미결) 불러올 수 없다. "링크가 죽었다"고
# 말하면 담당자가 링크를 의심하며 시간을 쓴다 — 무엇이 일어났고 무엇을 하면 되는지 적는다
S2_SESSION_LOST = "새로고침하면 정리하던 내용을 다시 불러올 수 없어요. 대화를 다시 넣어 주세요"

# --- SCR-005. E. 주문서 (케이스 18 ~ 21) --------------------------------------
S5_SUMMARY_PEOPLE = "함께한 사람"
S5_SUMMARY_CUPS = "모은 음료"
S5_ORDER_TITLE = "주문서"
S5_ORDER_HINT = "메뉴별로 묶었어요 · 이름을 누르면 고칠 수 있어요"
S5_TOTAL_LABEL = "합계"
S5_NAMES_MORE = "{n}명 더 보기"
S5_NAMES_FOLD = "접기"
S5_REPLY_TITLE = "단톡방 답장 반영하기"
S5_REPLY_SUB = "답장을 붙여넣으면 바뀐 주문을 찾아 줘요"
S5_REPLY_PLACEHOLDER = "[이름] 바꿀 내용 형식으로 붙여넣어 주세요"
S5_REPLY_ANALYZE = "바뀐 주문 찾기"
S5_REPLY_AI_NOTICE = "AI가 찾은 내용이에요"
S5_REPLY_APPLY = "반영"
S5_REPLY_IGNORE = "무시"
S5_REPLY_OPEN = "보기"
S5_REPLY_APPLY_ALL = "모두 반영"
S5_EDIT_REMOVE_PERSON = "이 사람 빼기"
S5_SHARE = "공유하기"
S5_SHARE_TITLE = "주문서 공유하기"
S5_SHARE_CAPTION = "복사하거나 저장하면 주문이 완료돼요"
S5_SHARE_NAMES = "이름 같이 보내기"
S5_SHARE_NAMES_OFF = "이름 없이 메뉴와 수량만 보내요"
S5_SHARE_COPY = "텍스트 복사"
S5_SHARE_IMAGE = "이미지 저장"
S5_SHARE_IMAGE_LOADING = "이미지를 만들고 있어요"
S5_BACK = "주문 정리로"
S5_CARD_FOOT = "Moa · 비공식 시연 서비스"

# --- SCR-006. O. 운영 대시보드 (케이스 04 · 05 · 22 · 23) ---------------------
O0_DIALOG_TITLE = "운영 대시보드"
O0_PROMPT = "운영자 비밀번호를 입력해 주세요"
O0_PLACEHOLDER = "비밀번호"
O0_LABEL = "비밀번호"
O0_SUBMIT = "들어가기"
O0_CANCEL = "취소"
# 사유를 구분하지 않는다(P-06 O-0 · NFR-003 · D-02 `OPS_AUTH_FAILED`)
O0_ERROR_FALLBACK = "비밀번호가 맞지 않아요"
O6_LOGOUT = "나가기"
O_ENV_BADGE = "실습 환경"
O_REFRESH_NOTE = "{at} 갱신 · 5초마다"
O4_TITLE = "승인 필요 ({n})"
O4_EMPTY = "승인 필요 없음"
O4_APPROVE = "승인"
O4_REJECT = "거부"
O3_TITLE = "지금 상태"
O1_TITLE = "사건"
O1_EMPTY = "발생한 사건이 없어요"
O1_COLUMNS = ["ID", "장애 코드", "상태", "탐지", "정상화"]
O5_TITLE = "지표"
O5_METRIC_LABELS = ["MTTD", "MTTR", "성공률", "에스컬레이션"]
O5_FAULT_TITLE = "장애 주입"
O5_FAULT_NOTE = "실습 전용"
O5_FAULT_CODES = ["F-1", "F-2", "F-3", "F-4", "F-5", "F-6"]
O5_FAULT_CLEAR = "해제"
O6_TITLE = "주문 처리 기록"
O6_SEARCH_HINT = "주문 찾기: 확정 시각 · 매장"
O6_COLUMNS = ["주문", "매장", "상태", "확정 시각", "변경", "복구"]
O6_DETAIL_COLUMNS = ["시각", "누구", "전 → 후", "방법"]
O6_SHARE_LABEL = "공유 기록"

# --- 통신 실패 안내 ------------------------------------------------------------
# 서버가 `user_message`를 주면 그것을 그대로 보여주고(D-02 2.2),
# 서버에 닿지 못해 응답 자체가 없을 때만 아래를 쓴다.
NETWORK_FAILED = "잠시 후 다시 눌러 주세요"
RETRY_FETCH = "다시 불러오기"
