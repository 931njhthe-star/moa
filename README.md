<div align="center">

<img src="https://931njhthe-star.github.io/assets/moa-banner-ko.png" alt="MOA — 단톡방 주문을 AI가 분석하여 하나의 주문서로 정리" width="100%">

# MOA — Multi-Agent Order Assistant
**단톡방 주문을 하나의 주문서로. 장애가 나도 복구할 수 있도록.**

`FastAPI` · `LangGraph` · `Multi-Agent` · `Auto Healing` · `HAProxy` · `PostgreSQL` · `Docker Compose`

[**프로젝트 소개 (한국어)**](https://931njhthe-star.github.io/moa/) · [**Project Page (English)**](https://931njhthe-star.github.io/en/moa/) · [**전체 기술 문서**](docs/README.md)

</div>

---

## 프로젝트 소개

MOA는 단체 채팅방의 자연어 주문을 읽고 **메뉴·옵션·수량·변경·취소**를 반영한 최종 주문서를 만드는 **5인 팀 프로젝트**입니다.

예를 들어 "아아 톨 2잔, 하나는 샷 추가" 이후 "샷 추가한 한 잔 취소"가 들어오면, 앞선 주문과 연결해 최종 수량을 정리합니다. LLM이 해석과 후보 생성을 돕지만, **메뉴 확정·가격 계산·검증 통과는 규칙으로 제어**합니다.

서비스의 또 다른 축은 장애가 발생해도 복구할 수 있도록 업무 앱과 분리한 **Auto Healing 시스템**입니다.

## 멀티 에이전트 처리 흐름

```text
단톡방 대화 입력
    ↓
Orchestrator (LangGraph · 규칙 기반 실행 순서)
    ↓
Intake Agent ── 추가 / 취소 / 변경 의도 추출
    ↓
Menu Agent ─── 메뉴 약칭·옵션 매칭 (규칙 우선, 필요 시 LLM·도구)
    ↓
규칙 검증 ───── 변경·취소 대상 연결, 수량·옵션 확인
    ↓
정산 + Review Agent ── 주문 반영·가격 계산, 모호한 항목 확인
    ↓
최종 주문서
```


**핵심은 LLM과 규칙의 역할 분리입니다.** LLM은 자연어 해석과 후보 제안에 집중하고, 메뉴 확정·가격 계산·검증 통과는 정해진 규칙으로 처리합니다. 처리 상태를 체크포인트에 저장해 장애 시 재개할 수 있도록 구성했습니다.

## 핵심 구조

<img src="https://931njhthe-star.github.io/assets/moa-autohealing.png" alt="MOA 이중화 애플리케이션, 주문 해석기 Primary/Backup 및 독립 Auto Healing 시스템" width="100%">

| 영역 | 핵심 기능 |
| --- | --- |
| **주문 처리** | Intake · Menu · Review 에이전트, 규칙 검증, 정산 및 주문서 생성 |
| **가용성** | HAProxy 게이트웨이, App A/B 복제본, Interpreter Primary/Backup |
| **장애 대응** | 독립 Healing 서비스: Monitor → Diagnosis → Recovery Worker → Verification |
| **배포·품질** | Docker Compose, GitHub Actions 기반 자동 테스트 및 배포 지원 |

> **설계 원칙:** LLM은 자연어를 해석하고 제안합니다. 복구 판단과 허용된 조치, 주문 확정은 명시적인 규칙으로 처리합니다. 요청 내부 폴백과 서비스 수준 복구도 구분합니다.

## My Contribution — Auto Healing

**담당: 노지훈 / Auto Healing 시스템**  
이 프로젝트는 팀 공동 작업이며, 전체 서비스·멀티 에이전트·QA·CI/CD를 혼자 구현한 것으로 표현하지 않습니다.

- **장애 감지와 진단:** 헬스체크·로그·응답 실패를 관찰하고 장애 유형과 사건 상태 관리
- **복구 워크플로:** 장애 종류에 따른 재시도·대체 경로·재시작·회로 차단·캐시 폴백을 연결하고 복구 조치 범위를 제한
- **독립 검증:** 복구 조치 이후 정상 상태와 기능을 별도 검증하고 실패 시 상태 보존 또는 운영자 이관
- **장애 주입 및 관측:** 모의 장애 시험, 사건 기록, 운영 화면 및 복구 지표를 통한 동작 확인

핵심적으로 **서비스 내부에 장애 테스트·복구 기능을 묶으면 서비스 장애 시 제어 기능도 함께 중단될 수 있다**는 점을 고려하여, 운영·복구 계층을 애플리케이션과 분리했습니다.

### 장애 대응 시나리오

| ID | 장애 유형 | 대응 전략 |
| --- | --- | --- |
| F-1 | HTTP 5xx | 제한된 재시도 후 대체 주문 해석기로 전환 |
| F-2 | 응답 지연 | Timeout 처리 후 대체 해석 경로 |
| F-3 | 앱 프로세스·복제본 중단 | 트래픽 전환 → 재시작 → 체크포인트 재개 |
| F-4 | 반복 장애 | 회로 차단 → 단일 Probe → 결과에 따라 승인 대기 |
| F-5 | 잘못된 AI 출력 | 재생성 → 형식·규칙 검증 |
| F-6 | 메뉴 DB 실패 | 재연결 → 캐시 폴백 |

구현과 한계에 대한 상세 내용은 [장애 복구 보고서](docs/배포_및_장애_복구_보고서.md)를 참고하세요.

## 검증 결과

| 항목 | 보고된 결과 |
| --- | --- |
| 장애 시나리오 | **6종** (F-1 ~ F-6) |
| 장애 시험 | **150회** (유형별 25회) |
| 성공 | **148회 / 150회 (98.67%)** |
| 실패 | **F-4 2회** (Primary → Backup 전환 관련) |

**수치의 범위:** 위 결과는 **시험자 보고 기준**입니다. 회차별 원본 실행 로그와 감지·복구 소요 시간은 제공되지 않아 독립 재현 결과나 운영 환경 가용성으로 해석하지 않습니다. MTTD/MTTR 실측치로 제시하지도 않습니다. 실패 2회의 정확한 원인은 추가 검증이 필요합니다.

## 기술 스택과 실행

- **AI / Application:** Python, FastAPI, LangGraph, Streamlit
- **Recovery / Infrastructure:** HAProxy, Docker Compose, PostgreSQL, 별도 Healing Worker
- **Quality / Delivery:** GitHub Actions, 테스트 및 장애 주입 워크플로

로컬 실행은 Docker Desktop과 환경 변수가 필요합니다. 민감한 값은 저장소에 커밋하지 말고 `.env.example` 및 `backend/.env.example`을 참고해 설정합니다.

```bash
sh scripts/init-networks.sh
docker compose -f docker-compose.core.yml -p moa-core up -d --build
docker compose -f docker-compose.app.yml -p moa-a run --rm backend python sql/run_sql.py
docker compose -f docker-compose.app.yml -p moa-a up -d
docker compose -f docker-compose.app.yml -p moa-b up -d
docker compose -f docker-compose.app.yml -f docker-compose.ops.yml -p moa-ops up -d
```

- 서비스: `http://localhost:8501`
- 운영 대시보드: `http://localhost:8502`
- 개발용 설정·직접 실행·EC2 배포·테스트 세부 절차는 [문서 안내](docs/README.md)와 원본 개발 브랜치 `dev`를 참고하세요.
- 데이터 유실을 막기 위해 DB 볼륨을 삭제하는 `docker compose down -v`는 사용하지 마세요.

## 문서 및 소스

- [핵심 기술 문서 바로가기](docs/README.md)
- [자동 복구 보고서](docs/배포_및_장애_복구_보고서.md)
- [멀티 에이전트 설계서](docs/멀티에이전트%20아키텍처%20설계서.md)
- [원본 개발 브랜치](https://github.com/931njhthe-star/moa/tree/dev)

> 이 저장소의 `main`은 **개인 포트폴리오 관점의 안내·문서 구성**을 우선하며, `dev`는 팀 개발 기록을 보존합니다. 구현 범위는 팀 협업 결과와 개인 담당 영역을 구분해 기술했습니다.
