# 상품 소개문 검사 화면 — Streamlit (백엔드 /check를 호출해 결과를 보여준다)
import httpx
import streamlit as st

from api_client import BACKEND_URL, check_copy, is_backend_alive

st.set_page_config(page_title="상품 소개문 검사기")
st.title("상품 소개문 검사기")

with st.sidebar:
    st.caption(f"백엔드: {BACKEND_URL}")
    if is_backend_alive():
        st.success("백엔드 연결됨")
    else:
        st.error("백엔드에 연결할 수 없습니다")

with st.form("check_form"):
    name = st.text_input("상품명", placeholder="숲속 캠핑 의자")
    price = st.text_input("가격", placeholder="29,900원")
    text = st.text_area("소개문", height=150)
    submitted = st.form_submit_button("검사하기")

if submitted:
    if not (name and price and text):
        st.warning("상품명, 가격, 소개문을 모두 입력하세요.")
    else:
        try:
            result = check_copy(text, name, price)
        except httpx.HTTPError as e:
            st.error(f"검사 요청에 실패했습니다: {e}")
        else:
            if result["passed"]:
                st.success("모든 규칙을 지켰습니다.")
            else:
                st.error(f"위반 {len(result['violations'])}건")
                for v in result["violations"]:
                    st.write(f"- {v}")
