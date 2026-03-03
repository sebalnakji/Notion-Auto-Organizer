import sqlite3
import logging
import logging.config
import yaml
from pathlib import Path
from cryptography.fernet import Fernet

# 로깅 설정
def setup_logging():
    config_path = Path(__file__).parents[2] / "logging.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            log_dir = Path(__file__).parents[2] / "logs"
            log_dir.mkdir(exist_ok=True)
            logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

# DB 경로: 프로젝트 루트/data/nao.db
DB_PATH = Path(__file__).parents[2] / "data" / "nao.db"

# 암호화 키 파일 경로
SECRET_KEY_PATH = Path(__file__).parents[2] / ".secret.key"

# 암호화 대상 키 목록
_ENCRYPT_KEYS = {
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "notion_api_key",
    "github_token",
}


def _get_fernet() -> Fernet:
    """암호화 키 로드 또는 신규 생성."""
    if SECRET_KEY_PATH.exists():
        key = SECRET_KEY_PATH.read_bytes()
    else:
        key = Fernet.generate_key()
        SECRET_KEY_PATH.write_bytes(key)
        logger.info("[DB] 암호화 키 생성 완료 - 경로: %s", SECRET_KEY_PATH)
    return Fernet(key)


def _encrypt(value: str) -> str:
    """값 암호화 후 문자열 반환."""
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    """암호화된 값 복호화. 실패 시 원본 반환 (기존 평문 데이터 호환)."""
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except Exception:
        return value


# 기본 타입 (수정/삭제 불가)
DEFAULT_TASK_TYPES = [
    ("concept", "개념정리", True),
    ("github",  "깃허브",   True),
    ("file",    "파일",     True),
    ("research","연구자료",  True),
]


def get_connection() -> sqlite3.Connection:
    """DB 연결 반환"""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_db():
    """DB 및 테이블 초기화"""
    logger.info("[DB] 초기화 시작")
    conn = get_connection()
    cursor = conn.cursor()

    # TaskTypes 테이블
    # base_type: 커스텀 타입이 어떤 기본 타입 구조를 베이스로 하는지
    # is_default: 기본 4개 타입 여부 (수정/삭제 불가)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_types (
            type_id    TEXT PRIMARY KEY,
            type_name  TEXT NOT NULL,
            base_type  TEXT NOT NULL REFERENCES task_types(type_id),
            is_default INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 기본 타입 초기값 삽입 (이미 존재하면 무시)
    cursor.executemany(
        """INSERT OR IGNORE INTO task_types (type_id, type_name, base_type, is_default, sort_order)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("concept",  "개념정리", "concept",  1, 0),
            ("github",   "깃허브",   "github",   1, 1),
            ("file",     "파일",     "file",     1, 2),
            ("research", "연구자료", "research", 1, 3),
        ],
    )

    # Sessions 테이블
    # task_type: task_types.type_id 참조 (커스텀 타입도 허용)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id   TEXT PRIMARY KEY,
            session_name TEXT NOT NULL,
            task_type    TEXT NOT NULL REFERENCES task_types(type_id),
            is_favorite  INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # ChatHistory 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            message_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            role        TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content     TEXT NOT NULL,
            timestamp   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        )
    """)

    # Settings 테이블 (키-값 형태로 프롬프트 설정 저장)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 기본 프롬프트 초기값 삽입 (이미 존재하면 무시)
    cursor.executemany(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        [
            # 프롬프트
            ("main_prompt",     "당신은 지식 큐레이션 전문가입니다. 사용자의 요청을 분석하여 명확하고 구조화된 마크다운 문서로 정리합니다."),
            ("concept_prompt",  "개념과 키워드를 분석하여 개요, 핵심 개념, 상세 설명, 예시 순으로 문서를 작성합니다."),
            ("github_prompt",   "GitHub 레포지토리를 분석하여 프로젝트 개요, 디렉토리 구조, 주요 기능, 기술 스택 순으로 문서를 작성합니다."),
            ("file_prompt",     "업로드된 파일을 분석하여 핵심 내용, 주요 데이터, 인사이트 순으로 문서를 작성합니다."),
            ("research_prompt", "연구 자료를 분석하여 연구 목적, 방법론, 주요 결과, 결론 순으로 문서를 작성합니다."),
            ("output_style",    "default"),
            ("toggle_prompt",   "문서의 각 섹션을 토글 형식으로 작성하세요. 섹션 제목은 '>>> 제목' 형식으로 시작하고 내용은 그 아래에 작성합니다."),
            # 사용자 설정
            ("nickname",        ""),
            # API 키 (빈 값으로 초기화)
            ("openai_api_key",    ""),
            ("anthropic_api_key", ""),
            ("google_api_key",    ""),
            ("notion_api_key",    ""),
            ("notion_page_id",    ""),
            ("github_token",      ""),
        ],
    )

    conn.commit()
    conn.close()
    logger.info("[DB] 초기화 완료 - 경로: %s", DB_PATH)


def get_setting(key: str) -> str:
    """settings 테이블에서 단일 값 조회. 민감 키는 복호화하여 반환."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return ""
        value = row["value"]
        return _decrypt(value) if key in _ENCRYPT_KEYS and value else value
    except Exception as e:
        logger.error("[DB] 설정 조회 실패 - key: %s, 오류: %s", key, e)
        return ""


# 민감 키 목록 (로그에 값 대신 등록 여부만 표시)
_SENSITIVE_KEYS = {
    "openai_api_key":    "OpenAI",
    "anthropic_api_key": "Claude",
    "google_api_key":    "Google",
    "notion_api_key":    "Notion",
    "github_token":      "GitHub",
}


def set_setting(key: str, value: str) -> bool:
    """settings 테이블에 값 저장 (upsert). 성공 시 True 반환."""
    try:
        conn = get_connection()
        store_value = _encrypt(value) if key in _ENCRYPT_KEYS and value else value
        conn.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, datetime('now', 'localtime'))
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 updated_at = excluded.updated_at""",
            (key, store_value),
        )
        conn.commit()
        conn.close()

        # 민감 키는 등록 여부만 로그에 기록
        if key in _SENSITIVE_KEYS:
            label = _SENSITIVE_KEYS[key]
            status = "등록되었습니다" if value else "삭제되었습니다"
            logger.info("[DB] %s API 키가 %s.", label, status)
        else:
            logger.info("[DB] 설정 저장 완료 - key: %s", key)
        return True
    except Exception as e:
        logger.error("[DB] 설정 저장 실패 - key: %s, 오류: %s", key, e)
        return False


def get_available_llm_providers() -> list[str]:
    """API 키가 등록된 LLM provider 목록 반환."""
    providers = []
    if get_setting("anthropic_api_key"):
        providers.append("claude")
    if get_setting("openai_api_key"):
        providers.append("openai")
    if get_setting("google_api_key"):
        providers.append("gemini")
    return providers


def load_prompt(type_key: str) -> str:
    """
    main_prompt + 타입별 프롬프트 + 닉네임 지침(있을 때만) + (토글 방식이면 toggle_prompt) 조합하여 반환.
    type_key: 'concept' | 'github' | 'file' | 'research' | 커스텀 base_type
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT key, value FROM settings WHERE key IN (?, 'main_prompt', 'output_style', 'toggle_prompt', 'nickname')",
            (f"{type_key}_prompt",),
        )
        rows = {row["key"]: row["value"] for row in cursor.fetchall()}
        conn.close()

        main     = rows.get("main_prompt", "")
        type_    = rows.get(f"{type_key}_prompt", "")
        style    = rows.get("output_style", "default")
        toggle   = rows.get("toggle_prompt", "") if style == "toggle" else ""
        nickname = rows.get("nickname", "").strip()
        nickname_guide = f"사용자의 호칭은 '{nickname}님'입니다. 대화 시 자연스럽게 호칭을 사용하세요." if nickname else ""

        return "\n\n".join(filter(None, [main, type_, nickname_guide, toggle]))
    except Exception as e:
        logger.error("[DB] 프롬프트 로드 실패 - type: %s, 오류: %s", type_key, e)
        return "당신은 지식 큐레이션 전문가입니다. 사용자의 요청을 마크다운 문서로 정리합니다."


if __name__ == "__main__":
    initialize_db()


def auto_session_name(first_message: str) -> str:
    """첫 메시지 앞 10글자로 세션명 자동 생성."""
    name = first_message.strip().replace("\n", " ")
    return name[:10] if len(name) > 10 else name


def apply_theme():
    """
    DB에 저장된 테마(light/dark)를 읽어 config.toml에 반영.
    Streamlit은 런타임 테마 변경을 지원하지 않으므로
    config.toml을 재작성 후 rerun으로 적용.
    """
    import os
    theme = get_setting("theme") or "light"
    config_path = Path(__file__).parents[2] / ".streamlit" / "config.toml"
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(
        f"[server]\nport = 8501\n\n[theme]\nbase = \"{theme}\"\n",
        encoding="utf-8",
    )