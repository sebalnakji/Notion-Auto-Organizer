import uuid
import streamlit as st
from database.schema import (
    get_connection, get_setting, set_setting,
    load_prompt, auto_session_name, get_available_llm_providers,
)
from services.llm import get_llm_client
from services.concept import ConceptService
from services.github import GithubService
from services.notion import upload_to_notion, get_page_id
from components.sidebar import render as render_sidebar


# ── DB 헬퍼 ───────────────────────────────────────────────────────────────────

def _get_task_types() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT type_id, type_name, base_type, is_default FROM task_types ORDER BY sort_order"
    ).fetchall()
    conn.close()
    return rows


def _save_message(session_id: str, role: str, content: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content),
    )
    conn.execute(
        "UPDATE sessions SET updated_at = datetime('now','localtime') WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def _ensure_session(active_type: str) -> str:
    if not st.session_state.get("session_id"):
        session_id = str(uuid.uuid4())
        conn = get_connection()
        conn.execute(
            "INSERT INTO sessions (session_id, session_name, task_type) VALUES (?, ?, ?)",
            (session_id, "새 세션", active_type),
        )
        conn.commit()
        conn.close()
        st.session_state.session_id = session_id
        st.session_state.session_name = "새 세션"
        st.session_state.chat_history = []
    return st.session_state.session_id


def _update_session_name(session_id: str, name: str):
    conn = get_connection()
    conn.execute(
        "UPDATE sessions SET session_name = ? WHERE session_id = ?",
        (name, session_id),
    )
    conn.commit()
    conn.close()
    st.session_state.session_name = name


# ── 렌더 ──────────────────────────────────────────────────────────────────────

def render():
    # 세션 상태 초기화
    if "active_type" not in st.session_state:
        st.session_state.active_type = "concept"
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = None
        st.session_state.session_name = None

    active_type = st.session_state.active_type
    types = _get_task_types()

    # 사이드바
    render_sidebar(active_type)

    # ── 타입 버튼 ─────────────────────────────────────────────────────────────
    type_cols = st.columns(len(types))
    for i, t in enumerate(types):
        with type_cols[i]:
            is_active = t["type_id"] == active_type
            if st.button(
                t["type_name"],
                key=f"type_btn_{t['type_id']}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                base = t["base_type"]
                if base == "github" and not get_setting("github_token"):
                    st.session_state.github_token_warn = True
                else:
                    st.session_state.active_type = t["type_id"]
                    st.session_state.session_id = None
                    st.session_state.chat_history = []
                    st.session_state.github_token_warn = False
                    st.rerun()

    if st.session_state.get("github_token_warn"):
        st.warning("⚠️ 설정에서 GitHub Personal Access Token을 먼저 등록해주세요.")

    st.divider()

    # 현재 타입 정보
    active_type_info = next((t for t in types if t["type_id"] == active_type), None)
    base_type = active_type_info["base_type"] if active_type_info else "concept"

    # ── 좌우 레이아웃 ─────────────────────────────────────────────────────────
    col_left, col_right = st.columns([1, 2], gap="large")

    # ── 왼쪽 패널 ─────────────────────────────────────────────────────────────
    with col_left:
        st.subheader("프롬프트")
        current_prompt = get_setting(f"{active_type}_prompt")
        edited_prompt = st.text_area(
            "타입별 프롬프트",
            value=current_prompt,
            height=200,
            label_visibility="collapsed",
            key=f"prompt_edit_{active_type}",
        )
        if st.button("저장", key="save_prompt", use_container_width=True):
            set_setting(f"{active_type}_prompt", edited_prompt.strip())
            st.success("저장되었습니다.")

        # 깃허브 타입: 레포 URL
        if base_type == "github":
            st.divider()
            st.subheader("레포지토리 URL")
            repo_url = st.text_input(
                "GitHub 레포 URL",
                value=st.session_state.get("repo_url", ""),
                placeholder="https://github.com/user/repo",
                label_visibility="collapsed",
                key="repo_url_input",
            )
            if st.button("저장", key="save_repo_url", use_container_width=True):
                st.session_state.repo_url = repo_url.strip()
                st.success("저장되었습니다.")

        # LLM 선택
        st.divider()
        st.subheader("LLM")
        available = get_available_llm_providers()
        all_providers = ["claude", "openai", "gemini"]
        provider_labels = {"claude": "Claude", "openai": "OpenAI", "gemini": "Gemini"}

        if available:
            current_provider = st.session_state.get("llm_provider", available[0])
            selected = st.radio(
                "LLM 선택",
                options=available,
                format_func=lambda p: provider_labels[p],
                index=available.index(current_provider) if current_provider in available else 0,
                label_visibility="collapsed",
            )
            st.session_state.llm_provider = selected
        else:
            st.caption("등록된 LLM API 키가 없습니다.")

        # Notion 페이지 ID
        st.divider()
        st.subheader("Notion 업로드")
        notion_page = st.text_input(
            "페이지 ID",
            value=st.session_state.get("notion_page_override", ""),
            placeholder="비워두면 기본값 사용",
            label_visibility="collapsed",
        )
        st.session_state.notion_page_override = notion_page.strip()

    # ── 오른쪽 패널: 대화창 ───────────────────────────────────────────────────
    with col_right:
        st.subheader("대화")

        # 대화 히스토리 표시
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # 예시 주제 토글
        with st.expander("💡 예시 주제"):
            for ex in _get_examples(base_type):
                if st.button(ex, key=f"ex_{ex[:20]}"):
                    st.session_state.prefill_input = ex
                    st.rerun()

        # 입력창
        prefill = st.session_state.pop("prefill_input", "")
        user_input = st.chat_input("정리할 내용을 입력하세요...")
        if prefill and not user_input:
            user_input = prefill

        send_col, notion_col = st.columns([3, 1])
        with notion_col:
            upload = st.button("📤 Notion 저장", use_container_width=True)

        # ── 전송 처리 ─────────────────────────────────────────────────────────
        if user_input and user_input.strip():
            available = get_available_llm_providers()
            provider = st.session_state.get("llm_provider", available[0] if available else None)
            if not provider:
                st.error("LLM API 키를 먼저 설정에서 등록해주세요.")
                st.stop()

            if base_type == "github" and not st.session_state.get("repo_url"):
                with st.chat_message("assistant"):
                    st.warning("왼쪽 패널에서 GitHub 레포지토리 URL을 먼저 입력해주세요.")
                st.stop()

            session_id = _ensure_session(active_type)

            if not st.session_state.chat_history:
                _update_session_name(session_id, auto_session_name(user_input))

            _save_message(session_id, "user", user_input.strip())
            st.session_state.chat_history.append({"role": "user", "content": user_input.strip()})

            with st.chat_message("user"):
                st.markdown(user_input.strip())

            try:
                llm = get_llm_client(provider)

                if base_type == "github" and len(st.session_state.chat_history) == 1:
                    # 첫 메시지: 깃허브 레포 분석
                    service = GithubService(llm)
                    with st.spinner("레포지토리 분석 중..."):
                        result, _ = service.analyze(
                            repo_url=st.session_state.repo_url,
                            session_id=session_id,
                            session_name=st.session_state.session_name,
                            type_id=active_type,
                        )
                    with st.chat_message("assistant"):
                        st.markdown(result)
                elif base_type == "github":
                    # 이후 메시지: draft 기반 수정
                    service = GithubService(llm)
                    with st.chat_message("assistant"):
                        result = st.write_stream(service.stream(
                            user_input=user_input.strip(),
                            session_id=session_id,
                            type_id=active_type,
                        ))
                else:
                    # 개념/파일/연구 타입: draft 기반
                    service = ConceptService(llm)
                    with st.chat_message("assistant"):
                        result = st.write_stream(service.stream(
                            user_input=user_input.strip(),
                            session_id=session_id,
                            session_name=st.session_state.session_name,
                            type_id=active_type,
                        ))

            except Exception as e:
                result = f"오류가 발생했습니다: {e}"
                with st.chat_message("assistant"):
                    st.error(result)

            _save_message(session_id, "assistant", result)
            st.session_state.chat_history.append({"role": "assistant", "content": result})
            st.rerun()

        # ── Notion 업로드 ────────────────────────────────────────────────────
        if upload:
            from services.concept import load_draft
            draft = load_draft(st.session_state.get("session_id", ""))
            if not draft:
                st.warning("업로드할 내용이 없습니다.")
            else:
                try:
                    page_id = get_page_id(st.session_state.get("notion_page_override") or None)
                    with st.spinner("Notion에 업로드 중..."):
                        url = upload_to_notion(draft, st.session_state.get("session_name", "정리 문서"), page_id)
                    st.success(f"업로드 완료! [Notion에서 보기]({url})")
                except Exception as e:
                    st.error(f"업로드 실패: {e}")


# ── 예시 주제 ─────────────────────────────────────────────────────────────────

def _get_examples(base_type: str) -> list[str]:
    examples = {
        "concept":  ["Docker와 VM의 차이점", "JWT 인증 방식", "REST API vs GraphQL", "객체지향 4가지 원칙", "CAP 이론"],
        "github":   ["전체 구조를 정리해줘", "주요 기능을 요약해줘", "기술 스택을 분석해줘"],
        "file":     ["핵심 내용을 정리해줘", "주요 데이터를 표로 정리해줘", "인사이트를 도출해줘"],
        "research": ["핵심 주장을 정리해줘", "연구 방법론을 요약해줘", "결론과 한계점을 정리해줘"],
    }
    return examples.get(base_type, examples["concept"])