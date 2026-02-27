import uuid
import streamlit as st
from database.schema import get_connection, auto_session_name


def _get_sessions(task_type: str) -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT session_id, session_name, is_favorite, updated_at
           FROM sessions WHERE task_type = ?
           ORDER BY is_favorite DESC, updated_at DESC""",
        (task_type,),
    ).fetchall()
    conn.close()
    return rows


def _create_session(task_type: str) -> str:
    session_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO sessions (session_id, session_name, task_type) VALUES (?, ?, ?)",
        (session_id, "새 세션", task_type),
    )
    conn.commit()
    conn.close()
    return session_id


def _rename_session(session_id: str, new_name: str):
    conn = get_connection()
    conn.execute(
        "UPDATE sessions SET session_name = ?, updated_at = datetime('now','localtime') WHERE session_id = ?",
        (new_name, session_id),
    )
    conn.commit()
    conn.close()


def _toggle_favorite(session_id: str, current: int):
    conn = get_connection()
    conn.execute(
        "UPDATE sessions SET is_favorite = ? WHERE session_id = ?",
        (0 if current else 1, session_id),
    )
    conn.commit()
    conn.close()


def _delete_session(session_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def render(active_type: str):
    with st.sidebar:
        if st.button("← 메인으로", use_container_width=True):
            st.session_state.page = "main"
            st.rerun()

        st.divider()

        if st.button("＋ 새 세션", use_container_width=True, type="primary"):
            new_id = _create_session(active_type)
            st.session_state.session_id = new_id
            st.session_state.session_name = "새 세션"
            st.session_state.chat_history = []
            st.rerun()

        st.caption("세션 목록")
        sessions = _get_sessions(active_type)

        if not sessions:
            st.caption("세션이 없습니다.")
        else:
            for row in sessions:
                sid    = row["session_id"]
                sname  = row["session_name"]
                is_fav = row["is_favorite"]
                is_active = st.session_state.get("session_id") == sid

                col_name, col_fav, col_del = st.columns([6, 1, 1])
                with col_name:
                    label = f"{'▶ ' if is_active else ''}{sname}"
                    if st.button(label, key=f"sess_{sid}", use_container_width=True):
                        st.session_state.session_id = sid
                        st.session_state.session_name = sname
                        conn = get_connection()
                        msgs = conn.execute(
                            "SELECT role, content FROM chat_history WHERE session_id = ? ORDER BY message_id",
                            (sid,),
                        ).fetchall()
                        conn.close()
                        st.session_state.chat_history = [
                            {"role": m["role"], "content": m["content"]} for m in msgs
                        ]
                        st.rerun()
                with col_fav:
                    if st.button("★" if is_fav else "☆", key=f"fav_{sid}"):
                        _toggle_favorite(sid, is_fav)
                        st.rerun()
                with col_del:
                    if st.button("✕", key=f"del_{sid}"):
                        _delete_session(sid)
                        if st.session_state.get("session_id") == sid:
                            st.session_state.session_id = None
                            st.session_state.session_name = None
                            st.session_state.chat_history = []
                        st.rerun()

        st.divider()

        if st.session_state.get("session_id"):
            st.caption("세션 이름 변경")
            new_name = st.text_input(
                "세션명",
                value=st.session_state.get("session_name", ""),
                label_visibility="collapsed",
                key="rename_input",
            )
            if st.button("변경", use_container_width=True):
                if new_name.strip():
                    _rename_session(st.session_state.session_id, new_name.strip())
                    st.session_state.session_name = new_name.strip()
                    st.rerun()