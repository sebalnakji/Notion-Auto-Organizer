import logging
from pathlib import Path
from database.schema import get_connection, load_prompt

token_logger = logging.getLogger('token_usage')
from services.llm import BaseLLMClient

logger = logging.getLogger(__name__)

# 중간 파일 저장 경로
DRAFTS_DIR = Path(__file__).parents[2] / "data" / "drafts"


def get_draft_path(session_id: str) -> Path:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    return DRAFTS_DIR / f"{session_id}.md"


def load_draft(session_id: str) -> str:
    """세션의 현재 문서 로드. 없으면 빈 문자열 반환."""
    path = get_draft_path(session_id)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_draft(session_id: str, content: str):
    """세션의 현재 문서 저장."""
    get_draft_path(session_id).write_text(content, encoding="utf-8")


def delete_draft(session_id: str):
    """세션 삭제 시 중간 파일도 삭제."""
    path = get_draft_path(session_id)
    if path.exists():
        path.unlink()
        logger.info("[CONCEPT] 중간 파일 삭제 완료 - session: %s", session_id)


# ── 개념 정리 서비스 ───────────────────────────────────────────────────────────

class ConceptService:
    """개념 정리 작업을 담당하는 서비스"""

    def __init__(self, llm: BaseLLMClient):
        self.llm = llm

    def _build_messages(self, session_id: str, user_input: str, type_id: str) -> list[dict]:
        """
        현재 문서(draft) + 수정 요청만 LLM에 전달.
        첫 요청이면 draft가 없으므로 일반 생성 요청으로 처리.
        """
        system = load_prompt(type_id)
        current_doc = load_draft(session_id)

        if current_doc:
            user_content = f"현재 문서:\n\n{current_doc}\n\n---\n수정 요청: {user_input}"
        else:
            user_content = user_input

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    def generate(
        self,
        user_input: str,
        session_id: str = "",
        session_name: str = "",
        type_id: str = "concept",
    ) -> str:
        """문서 생성 (단일 응답). 반환값: 마크다운 문자열"""
        messages = self._build_messages(session_id, user_input, type_id)
        logger.info("[CONCEPT] 문서 생성 시작 - 타입: %s | 세션: %s", type_id, session_name or "(unnamed)")
        result = self.llm.chat(messages)
        if session_id:
            save_draft(session_id, result)
        token_logger.info("[TOKEN] type=%s session=%s", type_id, session_name or "(unnamed)")
        logger.info("[CONCEPT] 문서 생성 완료 - 타입: %s | 세션: %s", type_id, session_name or "(unnamed)")
        return result

    def stream(
        self,
        user_input: str,
        session_id: str = "",
        session_name: str = "",
        type_id: str = "concept",
    ):
        """문서 스트리밍 생성. 반환값: 텍스트 청크 Generator"""
        messages = self._build_messages(session_id, user_input, type_id)
        logger.info("[CONCEPT] 스트리밍 시작 - 타입: %s | 세션: %s", type_id, session_name or "(unnamed)")
        token_logger.info("[TOKEN] type=%s session=%s (stream)", type_id, session_name or "(unnamed)")
        result = ""
        for chunk in self.llm.stream(messages):
            result += chunk
            yield chunk
        if session_id:
            save_draft(session_id, result)