import re
import time
import streamlit as st
from database.schema import get_setting, set_setting, get_connection, apply_theme


# ── DB 헬퍼 (타입 관리) ────────────────────────────────────────────────────────

def _get_task_types() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT type_id, type_name, base_type, is_default FROM task_types ORDER BY sort_order"
    ).fetchall()
    conn.close()
    return rows


def _add_task_type(type_id: str, type_name: str, base_type: str):
    conn = get_connection()
    max_order = conn.execute("SELECT MAX(sort_order) FROM task_types").fetchone()[0] or 0
    conn.execute(
        "INSERT INTO task_types (type_id, type_name, base_type, is_default, sort_order) VALUES (?, ?, ?, 0, ?)",
        (type_id, type_name, base_type, max_order + 1),
    )
    base_prompt = get_setting(f"{base_type}_prompt")
    set_setting(f"{type_id}_prompt", base_prompt)
    conn.commit()
    conn.close()


def _delete_task_type(type_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM task_types WHERE type_id = ? AND is_default = 0", (type_id,))
    conn.commit()
    conn.close()


# ── 렌더 ──────────────────────────────────────────────────────────────────────

def render():
    # 상단 네비게이션
    col_back, col_title = st.columns([1, 8])
    with col_back:
        if st.button("← 뒤로"):
            st.session_state.page = st.session_state.get("prev_page", "main")
            st.rerun()
    with col_title:
        st.title("⚙️ 설정")

    st.divider()

    tab_user, tab_api, tab_prompt, tab_type = st.tabs(["사용자", "API 키", "프롬프트", "타입 관리"])

    # ── 사용자 탭 ──────────────────────────────────────────────────────────────
    with tab_user:
        st.subheader("사용자 정보")
        nickname = st.text_input("닉네임 (선택)", value=get_setting("nickname"), placeholder="예: 태완")
        if st.button("저장", key="save_nickname"):
            set_setting("nickname", nickname.strip())
            st.success("저장되었습니다.")

        st.divider()
        st.subheader("테마")
        current_theme = get_setting("theme") or "light"
        theme = st.radio(
            "테마 선택",
            options=["light", "dark"],
            format_func=lambda x: "☀️ 라이트" if x == "light" else "🌙 다크",
            index=0 if current_theme == "light" else 1,
            horizontal=True,
        )
        if st.button("테마 저장 및 적용", key="save_theme"):
            set_setting("theme", theme)
            apply_theme()
            st.success("테마가 변경되었습니다. 페이지를 새로고침하면 적용됩니다.")

        st.divider()
        st.subheader("출력 방식")
        output_style = st.radio(
            "정리 방식",
            options=["default", "toggle"],
            format_func=lambda x: "기본 방식" if x == "default" else "토글 방식",
            index=0 if get_setting("output_style") != "toggle" else 1,
            horizontal=True,
        )
        if st.button("저장", key="save_style"):
            set_setting("output_style", output_style)
            st.success("저장되었습니다.")

    # ── API 키 탭 ──────────────────────────────────────────────────────────────
    with tab_api:
        st.subheader("LLM API 키")
        st.caption("등록된 API 키가 있는 LLM만 대화에서 선택 가능합니다.")

        for key, label in [
            ("anthropic_api_key", "Claude (Anthropic)"),
            ("openai_api_key",    "OpenAI"),
            ("google_api_key",    "Google Gemini"),
        ]:
            with st.expander(label):
                val = st.text_input(
                    "API 키",
                    value=get_setting(key),
                    type="password",
                    key=f"input_{key}",
                    label_visibility="collapsed",
                    placeholder="API 키 입력",
                )
                if st.button("저장", key=f"save_{key}"):
                    set_setting(key, val.strip())
                    st.success(f"저장되었습니다.")

        st.divider()
        st.subheader("Notion")
        notion_key = st.text_input(
            "Notion API 키",
            value=get_setting("notion_api_key"),
            type="password",
            placeholder="secret_...",
        )
        notion_page = st.text_input(
            "기본 업로드 페이지 ID",
            value=get_setting("notion_page_id"),
            placeholder="페이지 URL 또는 ID",
        )
        if st.button("저장", key="save_notion"):
            set_setting("notion_api_key", notion_key.strip())
            set_setting("notion_page_id", notion_page.strip())
            st.success("저장되었습니다.")

        st.divider()
        st.subheader("GitHub")
        st.caption("Private 레포지토리 접근 시 필요합니다. Public 레포는 없어도 됩니다.")
        github_token = st.text_input(
            "GitHub Personal Access Token",
            value=get_setting("github_token"),
            type="password",
            placeholder="ghp_...",
        )
        if st.button("저장", key="save_github"):
            set_setting("github_token", github_token.strip())
            st.success("저장되었습니다.")

    # ── 프롬프트 탭 ────────────────────────────────────────────────────────────
    with tab_prompt:
        st.subheader("메인 프롬프트 (공통)")
        main_prompt = st.text_area(
            "메인 프롬프트",
            value=get_setting("main_prompt"),
            height=120,
            label_visibility="collapsed",
        )
        if st.button("저장", key="save_main_prompt"):
            set_setting("main_prompt", main_prompt.strip())
            st.success("저장되었습니다.")

        st.divider()
        st.subheader("토글 방식 프롬프트")
        toggle_prompt = st.text_area(
            "토글 프롬프트",
            value=get_setting("toggle_prompt"),
            height=80,
            label_visibility="collapsed",
        )
        if st.button("저장", key="save_toggle_prompt"):
            set_setting("toggle_prompt", toggle_prompt.strip())
            st.success("저장되었습니다.")

        st.divider()
        st.subheader("타입별 프롬프트")
        types = _get_task_types()
        type_options = {
            f"{t['type_name']} ({'기본' if t['is_default'] else '커스텀'})": t["type_id"]
            for t in types
        }
        selected_label = st.selectbox("타입 선택", list(type_options.keys()))
        selected_type_id = type_options[selected_label]
        type_prompt = st.text_area(
            "타입별 프롬프트",
            value=get_setting(f"{selected_type_id}_prompt"),
            height=120,
            label_visibility="collapsed",
            key=f"ta_{selected_type_id}",
        )
        if st.button("저장", key=f"save_type_prompt_{selected_type_id}"):
            set_setting(f"{selected_type_id}_prompt", type_prompt.strip())
            st.success("저장되었습니다.")

    # ── 타입 관리 탭 ──────────────────────────────────────────────────────────
    with tab_type:
        st.subheader("타입 목록")
        types = _get_task_types()
        for t in types:
            col_name, col_badge, col_del = st.columns([5, 2, 1])
            with col_name:
                st.write(t["type_name"])
            with col_badge:
                if t["is_default"]:
                    st.caption("🔒 기본")
                else:
                    st.caption(f"베이스: {t['base_type']}")
            with col_del:
                if not t["is_default"]:
                    if st.button("삭제", key=f"del_type_{t['type_id']}"):
                        _delete_task_type(t["type_id"])
                        st.rerun()

        st.divider()
        st.subheader("새 타입 추가")
        default_types = [t for t in types if t["is_default"]]
        base_options = {t["type_name"]: t["type_id"] for t in default_types}
        new_type_name = st.text_input("타입 이름", placeholder="예: 논문 정리")
        new_base = st.selectbox("베이스 타입", list(base_options.keys()), key="new_base_type")
        if st.button("타입 추가", type="primary"):
            if new_type_name.strip():
                slug = re.sub(r"[^a-z0-9]", "_", new_type_name.strip().lower())
                type_id = f"custom_{slug}_{int(time.time()) % 10000}"
                _add_task_type(type_id, new_type_name.strip(), base_options[new_base])
                st.success(f"'{new_type_name}' 타입이 추가되었습니다.")
                st.rerun()
            else:
                st.warning("타입 이름을 입력해주세요.")