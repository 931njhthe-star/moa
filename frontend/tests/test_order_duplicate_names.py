# 2026-11-04 사용자 보고 — 주문서에서 한 사람이 같은 메뉴를 두 잔 시키면 StreamlitDuplicateElementKey('name_g2_정하준')
#
# 이름 칩은 순번으로 가른다(components.names_row). 두 번째 칩을 누르면 두 번째 잔(item_ids[1])이 고쳐져야 한다.
from streamlit.testing.v1 import AppTest


def _names_app():
    import streamlit as st

    from moa import components as c

    group = {"group_id": "g2", "people": ["정하준", "정하준", "이지연"],
             "item_ids": ["it_04", "it_13", "it_01"]}
    picked = st.session_state.setdefault("_picked", [])
    c.names_row(group, editable=True, editing_index=st.session_state.get("_editing"),
                on_pick=lambda g, index: picked.append(index))


def test_same_person_twice_in_a_group_renders():
    at = AppTest.from_function(_names_app).run()
    assert not at.exception
    assert [b.label for b in at.button] == ["정하준", "정하준", "이지연"]


def test_second_chip_picks_second_cup():
    at = AppTest.from_function(_names_app).run()
    at.button[1].click().run()
    assert at.session_state["_picked"] == [1]       # 순번 1 → item_ids[1] = it_13 (두 번째 잔)
