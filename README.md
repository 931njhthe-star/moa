# Moa — OrderOps AI Auto Healing

단톡방 대화를 붙여넣으면 누가 무엇을 시켰는지 사람별로 정리해 주는 서비스입니다.
FastAPI 에이전트 서버가 분석을 하고, Streamlit 화면이 입력 · 정리 · 주문서 · 운영 대시보드를 보여줍니다.

## 폴더 구조

```
2026_aio2_moa/
├── backend/                 # FastAPI (API 서버, 8000 포트)
│   ├── app/
│   │   ├── main.py          # 앱 생성 · trace_id · 오류 포장 · 라우터 등록
│   │   ├── api/             # HTTP 층 — D-02 엔드포인트 31개 (인증 · 입력 검사 · 포장)
│   │   └── services/        # 업무 로직 — 매장 판별 · 해석 · 메뉴 매칭 · 검증 · 정산 · 사건
│   ├── sql/                 # 스키마 · 시드 · run_sql.py (DB 초기화)
│   ├── tools/seed_demo.py   # 시연 세션 3건
│   ├── tests/
│   ├── requirements.txt     # 운영용
│   ├── requirements-dev.txt # 테스트용 (pytest 등)
│   └── Dockerfile
├── frontend/                # Streamlit (화면, 8501 포트)
│   ├── app.py               # 페이지 등록만 한다 (st.navigation)
│   ├── api_client.py        # 에이전트 서버 호출 (D-02 API스펙 · BACKEND_URL 환경변수)
│   ├── screens/             # 화면 4종 — start · review · order · ops
│   ├── moa/                 # 토큰 · 문구 · 레이아웃 · 컴포넌트 · 대화상자 · 상태 · 모의 응답
│   ├── .streamlit/          # 테마 (D-01 토큰)
│   ├── tests/
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── Dockerfile
├── docker-compose.yml       # 배포 구성 — 밖으로 여는 포트는 화면 8501 하나 (D-03 v1.2)
├── docker-compose.dev.yml   # 로컬 개발용 덧씌우기 — 백엔드 8000 도 연다
└── .github/workflows/ci.yml # CI: 테스트 + 이미지 빌드
```

프론트엔드는 백엔드 코드를 import하지 않고 HTTP로만 통신합니다. 호출 계약은 `03.구현문서/API스펙.md`(D-02)입니다.
`backend/` 폴더만 따로 받아도 실행 · 테스트 · DB 초기화가 됩니다 — 방법은 [backend/README.md](backend/README.md)에 있습니다.

## 화면 (P-06 화면설계서 v3.0)

정본 시안은 `Moa_화면설계_v3.0_간소화_변경.svg`(23케이스)입니다.

| URL | 화면 | 내용 |
|-----|------|------|
| `/` | SCR-001 주문 시작 | 서비스 소개 대화 · 예시 채우기 · `.txt` 올리기 · 대화 미리보기 · [정리하기] · 매장 되묻기 모달 |
| `/s?s={관리 토큰}` | SCR-002 주문 정리 | 왼쪽 주문서 패널(400px) + 오른쪽 채팅 · 진행 4단계 · 확인 질문(한 번에 하나) · 채팅 수정 · 행 편집 |
| `/order?s={관리 토큰}` | SCR-005 주문서 | 묶음 목록 · 이름 눌러 바꾸기 · 답장 반영 · 공유하기(= 완료 처리) |
| `/ops` | SCR-006 운영 대시보드 | O-0 비밀번호 · 승인 필요 · 지금 상태 · 사건 · 지표 · 주문 처리 기록 · 장애 주입 |

세션 관리 토큰은 **쿼리 파라미터로 받아 `X-Session-Token` 헤더로** 보냅니다. API 경로에 넣지 않습니다(D-02 1.1).

### 화면 미리보기 모드 (`MOA_UI_PREVIEW`)

**기본은 꺼짐입니다.** 켜면 에이전트 서버가 응답하지 않는 구간을 예시 데이터로 채워 서버 없이 화면을 볼 수 있습니다.
예시로 채운 구간은 화면 맨 아래 한 줄로 알립니다. 서버와 함께 쓸 때는 켜지 않습니다 — 켜 두면 세션을 잃었을 때(새로고침 ·
화면 재시작) 오류 대신 예시 주문서가 그려져 가짜 데이터로 답하고 공유하게 됩니다(2026-11-04).

```bash
MOA_UI_PREVIEW=1   # 켜기 — 서버 없이 화면만 볼 때. 화면 테스트(pytest)는 frontend/conftest.py 가 켠다
```

예시 데이터는 `frontend/moa/mock.py` 한 곳에 있습니다. 값은 전부 정본 시안의 예시값입니다.

## 실행 방법

### 방법 1: Docker Compose (권장)

Docker Desktop을 켠 뒤 프로젝트 루트에서 실행합니다. 백엔드는 `backend/.env`가 있으면 그 값을 씁니다(없으면 DB 없이 뜹니다).

```bash
docker compose up --build                                                    # 배포 · 시연
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build    # 개발 (API 8000 도 연다)
```

- 화면: http://localhost:8501
- API 문서: http://localhost:8000/docs — **개발용 덧씌우기를 썼을 때만** 열린다(배포는 백엔드 포트를 열지 않는다)
- 주문 해석 서비스는 기본이 **LLM 해석**(`INTERPRETER_SOURCE=llm`)이다. 같은 입력에 같은 결과가 필요하면(장애 실험 반복) `INTERPRETER_SOURCE=rules docker compose up`

백엔드 `/health`가 정상 응답한 뒤에 프론트엔드가 시작됩니다. 종료는 `Ctrl+C`, 정리는 `docker compose down`입니다.

### 방법 2: 직접 실행

[uv](https://docs.astral.sh/uv/)로 가상환경을 만들고 패키지를 설치합니다.

**1. 가상환경 만들기** — 프로젝트 루트에서 한 번만 실행합니다. **환경은 두 개입니다.**

```bash
uv venv -p 3.11                      # .venv          — backend (FastAPI)
uv venv -p 3.11 .venv-frontend       # .venv-frontend — frontend (Streamlit)
```

**왜 하나가 아닌가** — Streamlit 1.66 은 `starlette>=0.46` 을, FastAPI 0.115.6 은 `starlette<0.42` 를 요구합니다.
한 환경에 함께 설치하면 **나중에 설치한 쪽이 다른 쪽을 깨뜨립니다**(backend 는 `Router.__init__()` TypeError,
frontend 는 `DEFAULT_EXCLUDED_CONTENT_TYPES` ImportError). 둘을 한 환경에 넣으려면 FastAPI 를 올려야 하고,
그것은 D-03 1절 확정 스택 변경입니다.

**2. 패키지 설치** — 각 폴더에서, 그 폴더의 환경을 지정해 실행합니다.

```bash
cd backend
uv pip install --python ../.venv/Scripts/python.exe -r requirements-dev.txt
```

```bash
cd frontend
uv pip install --python ../.venv-frontend/Scripts/python.exe -r requirements-dev.txt
```

macOS · Linux 는 `../.venv/bin/python` 입니다.

`requirements-dev.txt`가 첫 줄(`-r requirements.txt`)에서 운영용 패키지까지 함께 설치하므로 `requirements.txt`는 따로 설치하지 않습니다.

**3. 서버 실행** — 터미널 두 개에서 각각 실행합니다.

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
../.venv-frontend/Scripts/python.exe -m streamlit run app.py
```

`uv run` 은 상위 폴더의 `.venv` 를 집으므로 frontend 에서는 쓰지 않습니다 — 위처럼 환경의 파이썬을 직접 부릅니다.

프론트엔드는 기본으로 `http://localhost:8000`에 접속합니다. 다른 주소를 쓰려면 `BACKEND_URL` 환경변수를 지정합니다.

## 테스트

위의 직접 실행 1~2단계(가상환경, 패키지 설치)를 마친 뒤 각 폴더에서 실행합니다. CI도 같은 `pytest` 명령을 사용합니다.

```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q                   # 계약 테스트 (DB 없이)
MOA_LIVE_DB=1 ../.venv/Scripts/python.exe -m pytest -q --cov=app --cov-fail-under=75   # .env 의 DB 로 전체 흐름까지
```

```bash
cd frontend
../.venv-frontend/Scripts/python.exe -m pytest -q --cov=api_client --cov-fail-under=85
```

## CI

`main`, `dev` 브랜치에 push하거나 이 브랜치로 PR을 만들면 GitHub Actions가 실행됩니다.

1. `test-backend`, `test-frontend`: 각 폴더의 테스트 (동시에 실행). 백엔드는 일회용 PostgreSQL에 스키마를 올려 전체 흐름까지 돌린다
2. `build`: 두 테스트가 통과하면 백엔드·프론트엔드 Docker 이미지를 빌드
