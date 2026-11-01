# Moa 테스트

상품 소개문이 작성 규칙(R1~R8)을 지켰는지 검사하는 서비스입니다.
FastAPI 백엔드가 검사를 하고, Streamlit 프론트엔드가 입력 화면과 결과를 보여줍니다.

## 폴더 구조

```
moa_test/
├── backend/                 # FastAPI (API 서버, 8000 포트)
│   ├── app/
│   │   ├── main.py          # 앱 생성 + 라우터 등록
│   │   ├── api/             # 경로: GET /health, POST /check
│   │   ├── schemas.py       # 요청/응답 모델
│   │   └── services/        # 규칙 검사 로직 (checker.py)
│   ├── tests/
│   ├── requirements.txt     # 운영용
│   ├── requirements-dev.txt # 테스트용 (pytest 등)
│   └── Dockerfile
├── frontend/                # Streamlit (화면, 8501 포트)
│   ├── app.py               # 화면
│   ├── api_client.py        # 백엔드 호출 (BACKEND_URL 환경변수)
│   ├── tests/
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── Dockerfile
├── docker-compose.yml       # 둘을 함께 실행
└── .github/workflows/ci.yml # CI: 테스트 + 이미지 빌드
```

프론트엔드는 백엔드 코드를 import하지 않고 HTTP(`/check`)로만 통신합니다.

## 실행 방법

### 방법 1: Docker Compose (권장)

Docker Desktop을 켠 뒤 프로젝트 루트에서 실행합니다.

```bash
docker compose up --build
```

- 화면: http://localhost:8501
- API 문서: http://localhost:8000/docs

백엔드 `/health`가 정상 응답한 뒤에 프론트엔드가 시작됩니다. 종료는 `Ctrl+C`, 정리는 `docker compose down`입니다.

### 방법 2: 직접 실행

[uv](https://docs.astral.sh/uv/)로 가상환경을 만들고 패키지를 설치합니다.

**1. 가상환경 만들기** — 프로젝트 루트에서 한 번만 실행합니다.

```bash
uv venv -p 3.11
```

루트의 `.venv` 하나를 backend와 frontend가 함께 씁니다. `uv`는 상위 폴더의 `.venv`를 찾아 쓰므로, 각 폴더에서 `uv venv`를 다시 실행하지 않습니다.

**2. 패키지 설치** — 각 폴더에서 실행합니다.

```bash
cd backend
uv pip install -r requirements-dev.txt
```

```bash
cd frontend
uv pip install -r requirements-dev.txt
```

`requirements-dev.txt`가 첫 줄(`-r requirements.txt`)에서 운영용 패키지까지 함께 설치하므로 `requirements.txt`는 따로 설치하지 않습니다.

**3. 서버 실행** — 터미널 두 개에서 각각 실행합니다.

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
uv run streamlit run app.py
```

가상환경을 활성화했다면(`.venv\Scripts\Activate.ps1`, macOS/Linux는 `source .venv/bin/activate`) 명령 앞의 `uv run`을 빼도 됩니다.

프론트엔드는 기본으로 `http://localhost:8000`에 접속합니다. 다른 주소를 쓰려면 `BACKEND_URL` 환경변수를 지정합니다.

## 테스트

위의 직접 실행 1~2단계(가상환경, 패키지 설치)를 마친 뒤 각 폴더에서 실행합니다. CI도 같은 `pytest` 명령을 사용합니다.

```bash
cd backend
uv run pytest -q --cov=app --cov-fail-under=85
```

```bash
cd frontend
uv run pytest -q --cov=api_client --cov-fail-under=85
```

## CI

`main`, `dev` 브랜치에 push하거나 이 브랜치로 PR을 만들면 GitHub Actions가 실행됩니다.

1. `test-backend`, `test-frontend`: 각 폴더의 테스트 (동시에 실행)
2. `build`: 두 테스트가 통과하면 백엔드·프론트엔드 Docker 이미지를 빌드
