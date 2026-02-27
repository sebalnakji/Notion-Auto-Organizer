import logging
from database.schema import get_connection, load_prompt

token_logger = logging.getLogger('token_usage')
from services.llm import BaseLLMClient

logger = logging.getLogger(__name__)


# ── 개념 정리 서비스 ───────────────────────────────────────────────────────────

class ConceptService:
    """개념 정리 작업을 담당하는 서비스"""

    def __init__(self, llm: BaseLLMClient):
        self.llm = llm

    def _build_messages(self, history: list[dict], user_input: str) -> list[dict]:
        """매 호출마다 DB에서 최신 프롬프트를 읽어 UI 설정 변경이 즉시 반영됨."""
        messages = [{"role": "system", "content": load_prompt("concept")}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        return messages

    def generate(
        self,
        user_input: str,
        history: list[dict] | None = None,
        session_name: str = "",
        type_id: str = "concept",
    ) -> str:
        """개념 정리 문서 생성 (단일 응답). 반환값: 마크다운 문자열"""
        history = history or []
        messages = self._build_messages(history, user_input)
        logger.info("[CONCEPT] 문서 생성 시작 - 타입: %s | 세션: %s", type_id, session_name or "(unnamed)")
        result = self.llm.chat(messages)
        token_logger.info("[TOKEN] type=%s session=%s", type_id, session_name or "(unnamed)")
        logger.info("[CONCEPT] 문서 생성 완료 - 타입: %s | 세션: %s", type_id, session_name or "(unnamed)")
        return result

    def stream(
        self,
        user_input: str,
        history: list[dict] | None = None,
        session_name: str = "",
        type_id: str = "concept",
    ):
        """개념 정리 문서 스트리밍 생성. 반환값: 텍스트 청크 Generator"""
        history = history or []
        messages = self._build_messages(history, user_input)
        logger.info("[CONCEPT] 스트리밍 시작 - 타입: %s | 세션: %s", type_id, session_name or "(unnamed)")
        token_logger.info("[TOKEN] type=%s session=%s (stream)", type_id, session_name or "(unnamed)")
        yield from self.llm.stream(messages)