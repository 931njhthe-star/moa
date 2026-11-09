"""대화 파싱과 파일 판정 — 형식만 본다. LLM 호출 0건 (API-011).

읽지 못한 줄을 **버리지 않고 돌려준다**. 조용히 빠뜨리면 담당자가
"내가 넣은 사람이 왜 없지"를 알 수 없다.

이름이 **한 줄도** 없는 대화는 거부하지 않고 `이름 없음` 한 사람의 주문으로 받는다
(2026-11-05 사용자 결정 1번). 줄 단위로 사람을 가를 근거가 없으므로 사람별 구분은 하지 않는다 —
메뉴 · 수량 · 옵션만 정리하고, 공유는 이름 없이 한다. 이름이 **일부라도** 있으면 예전처럼
이름 없는 줄을 읽지 못한 줄로 둔다 — 그때는 형식이 섞인 것이지 이름이 없는 대화가 아니다.
"""

import re

from app import config

# 카카오톡 PC에서 복사하면 이름 뒤에 시각이 붙는다 — "[이지연] [오후 2:31] 그란데로 바꿔주세요".
# 시각을 메시지 본문에 남기면 메뉴 표현에 섞인다(2026-11-04 · 사용자 보고 #6)
_KAKAO_TIME = re.compile(r"^\[(?:오전|오후)\s*\d{1,2}:\d{2}\]\s*")

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif")
_IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"GIF8", b"RIFF")

FILE_ERRORS = {
    "IMAGE_NOT_SUPPORTED": "사진은 읽지 못해요. 대화를 복사해 붙여넣거나 .txt 파일로 올려 주세요",
    "FILE_NOT_SUPPORTED": "이 파일은 읽을 수 없어요. 대화를 복사해 붙여넣거나 .txt 파일로 올려 주세요",
    "TOO_LARGE": "대화가 너무 길어요. 나눠서 올려 주세요",
}

# 첨부는 .txt 만 받는다 (PRD v1.1 §1 입력). 화면 업로더(st.file_uploader type=)에는 제한을 걸지 않고 —
# 걸면 설계 문구가 아니라 Streamlit 기본 오류가 뜬다 — 서버가 여기서 거른 뒤 안내 문구를 돌려준다.
_TEXT_SUFFIX = ".txt"


def judge_file(filename: str, data: bytes) -> tuple[str | None, str | None]:
    """첨부 파일을 판정한다 — 확장자는 `.txt` 만, 내용은 텍스트(UTF-8 · CP949)만.

    순서: 크기 → 이미지(확장자 또는 내용) → `.txt` 확장자 → 텍스트 디코딩.
    이미지는 확장자를 `.txt` 로 바꿔도 내용으로 걸러 사진 안내를 준다.

    돌려주는 값: (raw_text, None) 또는 (None, 에러코드)
    """
    if len(data) > config.MAX_INPUT_BYTES:
        return None, "TOO_LARGE"
    lowered = (filename or "").lower()
    if lowered.endswith(_IMAGE_SUFFIXES) or data[:4] in _IMAGE_MAGIC:
        return None, "IMAGE_NOT_SUPPORTED"
    if not lowered.endswith(_TEXT_SUFFIX):
        return None, "FILE_NOT_SUPPORTED"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp949")     # 한국 윈도우에서 저장한 .txt
        except UnicodeDecodeError:
            return None, "FILE_NOT_SUPPORTED"
    if "\x00" in text:
        return None, "FILE_NOT_SUPPORTED"
    return text, None


# 이름을 알 수 없는 참여자 — 이름이 한 줄도 없는 대화에서 주문자 칸에 들어간다(사용자 결정 1번).
# 화면 · 공유 · 질문이 모두 이 값을 보고 "이름 없는 주문"으로 다룬다
UNNAMED = "이름 없음"


def parse(raw_text: str) -> dict:
    """`[이름] 메시지` 형식만 본다 (API-011 미리보기와 API-012 가 같은 파서를 쓴다)."""
    messages, unreadable = [], []
    for line_no, line in enumerate((raw_text or "").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        sender, text = _split(line)
        if sender is None:
            unreadable.append({
                "line_no": line_no, "text": line,
                "notice_text": f"{line_no}번째 줄은 읽지 못했어요",
            })
            continue
        messages.append({
            "message_id": f"m{len(messages) + 1}",
            "order": len(messages) + 1,
            "seq": len(messages) + 1,
            "sender": sender,
            "text": text,
        })

    if not messages and unreadable:
        # 카카오톡 모바일 · 메신저 복사본처럼 이름이 **제 줄에 따로** 있는 형식 — "김민수\n아아 톨 2잔"
        # (2026-11-09 사용자 보고: 16줄이 전부 `이름 없음` 메시지로 들어가 이름 줄이 주문으로 읽혔다)
        stacked = _parse_name_lines(unreadable)
        if stacked:
            messages, unreadable = stacked

    if not messages and unreadable:
        # 이름이 한 줄도 없다 — 거부하지 않고 `이름 없음` 한 사람의 대화로 받는다
        messages = [{"message_id": f"m{n}", "order": n, "seq": n,
                     "sender": UNNAMED, "text": line["text"]}
                    for n, line in enumerate(unreadable, start=1)]
        unreadable = []

    people = sorted({m["sender"] for m in messages})
    # 이름 없는 대화는 "1명"이 아니다 — 몇 명인지 모른다는 사실을 그대로 알린다
    summary = (f"이름이 없는 대화예요 · 메시지 {len(messages)}개를 읽었어요"
               if people == [UNNAMED] else
               f"{len(people)}명 · 메시지 {len(messages)}개를 읽었어요")
    return {
        "messages": messages[: config.MAX_MESSAGES],
        "summary_text": summary,
        "unreadable_lines": unreadable,
        "can_proceed": bool(messages),
        "people": people,
        "person_count": len(people),
        "message_count": len(messages),
    }


# 제 줄에 따로 있는 이름 — 한글 2~4자 또는 영문 이름. "좋아요" 같은 짧은 대답을 이름으로 잡지 않도록
# `요`로 끝나는 줄은 뺀다
_NAME_LINE = re.compile(r"^(?:[가-힣]{2,4}|[A-Za-z][A-Za-z.]{1,15})$")


# 디스코드 복사본의 머리줄 — "이름 — 오전 10:23" · "이름 — 오늘 오후 2:31" · "이름 — 2026. 11. 9. 오전 10:23".
# 이름에는 공백 · 숫자 · `_` 가 들어갈 수 있다("AIO 2기_이성우"). 복사할 때 분이 잘려 "오전 10:" 로 끝나기도 한다
# (2026-11-09 사용자 요청: 디스코드 형식 포함)
_DISCORD_HEAD = re.compile(
    r"^(?P<name>.+?)\s+[—–-]\s+"
    r"(?:(?:오늘|어제)\s*|\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}\s*\.?\s*)?"
    r"(?:오전|오후)\s*\d{1,2}:\d{0,2}$")


def _is_name_line(text: str) -> bool:
    return _name_of(text) is not None


def _name_of(text: str) -> str | None:
    """이름 줄이면 이름을, 아니면 None 을 돌려준다 — 이름만 있는 줄과 디스코드 머리줄을 받는다."""
    head = _DISCORD_HEAD.match(text)
    if head:
        return head.group("name").strip() or None
    if _NAME_LINE.match(text) and not text.endswith("요"):
        return text
    return None


def _parse_name_lines(lines: list[dict]) -> tuple[list[dict], list[dict]] | None:
    """이름 줄 다음에 메시지 줄이 오는 형식을 읽는다. 첫 줄이 이름 줄이 아니면 None(이 형식이 아니다).

    이름 줄은 이름만 있는 줄(카카오톡 모바일 등)과 디스코드 머리줄("이름 — 오전 10:23") 두 가지다.

    이름 줄 바로 다음 줄은 이름처럼 생겨도 메시지다("최유나\n민트초코"). 이름 줄 없이 이어지는 줄은
    앞 사람의 메시지로 붙이되, **대화 맨 끝의 이어진 줄**은 읽지 못한 줄로 둔다 — 매장 요청 한 줄
    ("스타벅스로 갈 예정이야")이 마지막 사람의 주문으로 섞이지 않게 하려는 것이다(PRD 2.4.1).
    """
    if len(lines) < 2 or not _is_name_line(lines[0]["text"]):
        return None
    messages, unreadable = [], []
    sender, i = None, 0
    while i < len(lines):
        text = lines[i]["text"]
        if _DISCORD_HEAD.match(text) and i + 1 < len(lines) and _DISCORD_HEAD.match(lines[i + 1]["text"]):
            i += 1      # 본문 없는 머리줄(사진만 올린 메시지 등) — 다음 머리줄을 본문으로 먹지 않는다
            continue
        if _is_name_line(text) and i + 1 < len(lines):
            sender, body = _name_of(text), _KAKAO_TIME.sub("", lines[i + 1]["text"])
            i += 2
        elif i == len(lines) - 1:
            unreadable.append(lines[i])
            break
        else:
            body = _KAKAO_TIME.sub("", text)
            i += 1
        if not body:
            continue
        n = len(messages) + 1
        messages.append({"message_id": f"m{n}", "order": n, "seq": n, "sender": sender, "text": body})
    return (messages, unreadable) if messages else None


def _split(line: str) -> tuple[str | None, str]:
    """`[이름] 메시지` · `이름: 메시지` 두 형식을 받는다."""
    if line.startswith("[") and "]" in line:
        if _KAKAO_TIME.match(line):
            # "[오전 10:24]다음 메시지" — 디스코드에서 같은 사람이 이어 보낸 줄. 시각을 이름으로 읽지 않는다
            return None, line
        sender, _, text = line[1:].partition("]")
        sender, text = sender.strip(), _KAKAO_TIME.sub("", text.strip())
        if sender and text:
            return sender, text
        return None, line
    # 카카오톡 복사 형식에 가까운 `이름 : 메시지`
    if ":" in line:
        sender, _, text = line.partition(":")
        sender, text = sender.strip(), text.strip()
        # 이름이 길면 문장 안의 콜론일 가능성이 높다 — 읽지 못한 줄로 넘긴다
        if sender and text and len(sender) <= 12 and " " not in sender:
            return sender, text
    return None, line
