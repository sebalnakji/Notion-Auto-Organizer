import streamlit as st
from database.schema import initialize_db, setup_logging, get_setting, get_available_llm_providers

setup_logging()

st.set_page_config(
    page_title="Notion Auto Organizer",
    page_icon="📝",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── DB 초기화 ──────────────────────────────────────────────────────────────────

initialize_db()

# ── 세션 상태 초기화 ───────────────────────────────────────────────────────────

if "page" not in st.session_state:
    st.session_state.page = "main"

# ── 페이지 라우팅 ──────────────────────────────────────────────────────────────

if st.session_state.page == "workspace":
    from views.workspace import render
    render()
    st.stop()

if st.session_state.page == "settings":
    from views.settings import render
    render()
    st.stop()

# ── 메인 페이지 ────────────────────────────────────────────────────────────────

st.markdown("<br><br>", unsafe_allow_html=True)
st.title("📝 Notion Auto Organizer")
st.caption("LLM으로 정리하고 Notion에 바로 저장")
st.divider()

# API 키 미등록 경고
available_llm = get_available_llm_providers()
notion_key = get_setting("notion_api_key")

if not available_llm:
    st.warning("⚠️ LLM API 키가 등록되지 않았습니다. 설정에서 먼저 등록해주세요.")
if not notion_key:
    st.warning("⚠️ Notion API 키가 등록되지 않았습니다. 설정에서 먼저 등록해주세요.")

st.markdown("<br>", unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    if st.button("✦ 정리하기", use_container_width=True, type="primary"):
        if not available_llm or not notion_key:
            st.session_state.show_key_warning = True
            st.rerun()
        else:
            st.session_state.page = "workspace"
            st.session_state.active_type = "concept"
            st.session_state.show_key_warning = False
            st.rerun()
with col2:
    if st.button("⚙️ 설정", use_container_width=True):
        st.session_state.prev_page = "main"
        st.session_state.page = "settings"
        st.rerun()

if st.session_state.get("show_key_warning"):
    st.error("API 키를 먼저 등록해주세요. [⚙️ 설정] 버튼을 눌러 이동하세요.")