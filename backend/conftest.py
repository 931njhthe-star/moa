# backend/ 를 import 경로에 올린다 (pytest rootdir conftest).
#
# 계약 테스트는 DB 없이 돈다 — CI 에 DB 가 없고, 로컬 .env 가 있어도 결과가 같아야 한다.
# load_dotenv 는 이미 있는 환경변수를 덮지 않으므로, app 을 import 하기 전에 비워 둔다.
# 실제 DB 로 전체 흐름을 보려면 MOA_LIVE_DB=1 로 실행한다 (tests/test_live_flow.py).
import os

if os.getenv("MOA_LIVE_DB") != "1":
    os.environ["DATABASE_URL"] = ""
    # 주문 해석 서비스도 띄우지 않은 상태가 기준이다 — 로컬 .env 의 주소로 실제 호출하지 않게
    os.environ["ORDER_INTERPRETER_PRIMARY_URL"] = ""
    os.environ["ORDER_INTERPRETER_BACKUP_URL"] = ""
os.environ.setdefault("OPS_DASHBOARD_PASSWORD", "test-ops")

# 테스트가 저장소의 logs/ 에 쓰지 않게 한다 (app.logging_setup 이 import 시점에 파일을 연다)
import tempfile

os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="moa-test-logs-"))

