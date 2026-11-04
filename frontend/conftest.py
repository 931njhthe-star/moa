# pytest가 이 폴더를 프로젝트 루트로 인식하게 한다 (api_client import용)
#
# 화면 테스트는 서버 없이 미리보기 대역으로 돈다 — 미리보기 모드 기본값이 꺼짐이라(moa/mock.py) 여기서 켠다.
# moa 를 import 하기 전에 정해야 한다(PREVIEW_ENABLED 는 import 시점에 읽는다)
import os

os.environ.setdefault("MOA_UI_PREVIEW", "1")
