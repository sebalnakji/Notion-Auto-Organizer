import logging
import os
import shutil
import tempfile
from pathlib import Path
from dataclasses import dataclass

from git import Repo, InvalidGitRepositoryError
from database.schema import load_prompt, get_setting

token_logger = logging.getLogger('token_usage')
from services.llm import BaseLLMClient

logger = logging.getLogger(__name__)

# ── 설정 ──────────────────────────────────────────────────────────────────────

# 분석에서 제외할 디렉토리
EXCLUDE_DIRS = {
    ".git", ".github", "node_modules", "__pycache__", ".venv", "venv",
    "env", "dist", "build", ".next", ".nuxt", "coverage", ".pytest_cache",
    ".mypy_cache", ".tox", "eggs", "*.egg-info",
}

# 분석에서 제외할 파일 확장자 (바이너리/미디어)
EXCLUDE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".mp4", ".mp3", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".exe", ".bin", ".dll", ".so", ".dylib",
    ".lock", ".sum",
}

# 파일 크기 제한 (기본 50KB)
MAX_FILE_BYTES = int(os.getenv("GITHUB_MAX_FILE_BYTES", 50_000))

# 토큰 초과 경고 기준 (누적 문자 수)
MAX_TOTAL_CHARS = int(os.getenv("GITHUB_MAX_TOTAL_CHARS", 200_000))


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────

@dataclass
class FileStatus:
    path: str
    skipped: bool = False
    reason: str = ""      # 'size' | 'binary' | 'excluded'
    summary: str = ""


# ── 레포 클론 및 파일 수집 ─────────────────────────────────────────────────────

def clone_repo(url: str) -> Path:
    """GitHub 레포를 로컬 임시 디렉토리에 클론. 임시 경로 반환."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="nao_github_"))
    logger.info("[GITHUB] 레포 클론 시작 - url: %s", url)
    try:
        # GitHub Personal Access Token이 있으면 URL에 삽입
        token = get_setting("github_token")
        clone_url = url
        if token and url.startswith("https://github.com"):
            clone_url = url.replace("https://", f"https://{token}@")

        Repo.clone_from(clone_url, tmp_dir, depth=1)
        logger.info("[GITHUB] 레포 클론 완료")
        return tmp_dir
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"레포 클론 실패: {e}") from e


def collect_files(repo_path: Path) -> tuple[list[Path], list[FileStatus]]:
    """
    분석 대상 파일 수집 및 사전 필터링.
    반환: (분석할 파일 목록, 스킵된 파일 목록)
    """
    target_files, skipped = [], []

    for file_path in sorted(repo_path.rglob("*")):
        if not file_path.is_file():
            continue

        rel = file_path.relative_to(repo_path)
        parts = set(rel.parts[:-1])  # 상위 디렉토리들

        # 제외 디렉토리 체크
        if parts & EXCLUDE_DIRS:
            continue

        # 제외 확장자 체크
        if file_path.suffix.lower() in EXCLUDE_EXTENSIONS:
            skipped.append(FileStatus(str(rel), skipped=True, reason="binary"))
            continue

        # 파일 크기 체크
        size = file_path.stat().st_size
        if size > MAX_FILE_BYTES:
            skipped.append(FileStatus(str(rel), skipped=True, reason="size"))
            continue

        target_files.append(file_path)

    logger.info("[GITHUB] 파일 수집 완료 - 분석 대상: %d개, 스킵: %d개", len(target_files), len(skipped))
    return target_files, skipped


def get_dir_structure(repo_path: Path, max_depth: int = 3) -> str:
    """레포 디렉토리 구조를 트리 형태 문자열로 반환"""
    lines = []

    def _walk(path: Path, depth: int, prefix: str):
        if depth > max_depth:
            return
        items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        for i, item in enumerate(items):
            if item.name in EXCLUDE_DIRS or item.name.startswith("."):
                continue
            connector = "└── " if i == len(items) - 1 else "├── "
            lines.append(f"{prefix}{connector}{item.name}")
            if item.is_dir():
                extension = "    " if i == len(items) - 1 else "│   "
                _walk(item, depth + 1, prefix + extension)

    lines.append(repo_path.name + "/")
    _walk(repo_path, 1, "")
    return "\n".join(lines)


# ── 파일 분석 ─────────────────────────────────────────────────────────────────

def _analyze_file(
    llm: BaseLLMClient,
    file_path: Path,
    rel_path: str,
    accumulated: str,
) -> str:
    """단일 파일을 LLM으로 분석하여 요약 반환"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.warning("[GITHUB] 파일 읽기 실패 - %s: %s", rel_path, e)
        return ""

    prompt = f"""현재까지 분석된 프로젝트 내용:
{accumulated if accumulated else '(없음)'}

---
다음 파일을 분석하여 역할과 주요 기능을 2~5줄로 간결하게 요약하세요.
파일 경로: {rel_path}

```
{content}
```

요약만 출력하고 다른 설명은 붙이지 마세요."""

    return llm.chat([{"role": "user", "content": prompt}])


# ── 최종 문서 생성 ─────────────────────────────────────────────────────────────

def _generate_final_doc(
    llm: BaseLLMClient,
    repo_url: str,
    dir_structure: str,
    file_summaries: list[FileStatus],
    system_prompt: str,
) -> str:
    """누적된 파일 요약을 바탕으로 최종 마크다운 문서 생성"""
    summaries_text = "\n\n".join(
        f"**{fs.path}**\n{fs.summary}"
        for fs in file_summaries if fs.summary
    )

    prompt = f"""다음 GitHub 프로젝트를 분석한 결과를 바탕으로 완성된 마크다운 문서를 작성하세요.

## 레포지토리 URL
{repo_url}

## 디렉토리 구조
```
{dir_structure}
```

## 파일별 분석 요약
{summaries_text}

---
아래 구조로 마크다운 문서를 작성하세요:
1. 프로젝트 개요
2. 기술 스택
3. 디렉토리 구조
4. 주요 기능
5. 파일별 역할

마크다운만 출력하고 다른 설명은 붙이지 마세요."""

    return llm.chat([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ])


# ── 깃허브 정리 서비스 ─────────────────────────────────────────────────────────

class GithubService:
    """GitHub 프로젝트 분석 및 문서화를 담당하는 서비스"""

    def __init__(self, llm: BaseLLMClient):
        self.llm = llm

    def analyze(
        self,
        repo_url: str,
        on_progress: callable = None,
        on_large_file: callable = None,
        session_name: str = "",
        type_id: str = "github",
    ) -> tuple[str, list[FileStatus]]:
        """
        GitHub 레포 분석 및 마크다운 문서 생성.

        Args:
            repo_url: GitHub 레포지토리 URL
            on_progress: 진행 상황 콜백 (current, total, filename) → None
                         UI 진행률 표시에 사용
            on_large_file: 대용량 파일 발견 시 콜백 (FileStatus) → str
                           반환값: 'skip' | 'manual:요약내용' | 'cancel'

        Returns:
            (최종 마크다운 문자열, 전체 FileStatus 목록)
        """
        repo_path = None
        try:
            # 1. 클론
            repo_path = clone_repo(repo_url)
            dir_structure = get_dir_structure(repo_path)

            # 2. 파일 수집
            target_files, skipped = collect_files(repo_path)
            all_statuses = list(skipped)

            # 3. 파일별 순차 분석
            accumulated = ""
            total = len(target_files)

            for idx, file_path in enumerate(target_files):
                rel_path = str(file_path.relative_to(repo_path))

                # 진행률 콜백
                if on_progress:
                    on_progress(idx + 1, total, rel_path)

                # 누적 컨텍스트 초과 경고
                if len(accumulated) > MAX_TOTAL_CHARS and on_large_file:
                    status = FileStatus(rel_path, skipped=True, reason="size")
                    action = on_large_file(status)
                    if action == "cancel":
                        return "", all_statuses
                    elif action == "skip":
                        all_statuses.append(status)
                        continue
                    elif action and action.startswith("manual:"):
                        status.summary = action[7:]
                        status.skipped = False
                        all_statuses.append(status)
                        accumulated += f"\n{rel_path}: {status.summary}"
                        continue

                summary = _analyze_file(self.llm, file_path, rel_path, accumulated)
                fs = FileStatus(rel_path, summary=summary)
                all_statuses.append(fs)
                accumulated += f"\n{rel_path}: {summary}"
                logger.info("[GITHUB] 파일 분석 (%d/%d) - %s", idx + 1, total, rel_path)

            # 4. 최종 문서 생성
            system_prompt = load_prompt("github")
            final_doc = _generate_final_doc(
                self.llm, repo_url, dir_structure, all_statuses, system_prompt
            )

            token_logger.info("[TOKEN] type=%s session=%s files=%d", type_id, session_name or repo_url.split("/")[-1], len(all_statuses))
            return final_doc, all_statuses

        finally:
            # 5. 임시 디렉토리 정리
            if repo_path and repo_path.exists():
                shutil.rmtree(repo_path, ignore_errors=True)
                logger.info("[GITHUB] 임시 디렉토리 삭제 완료")

    def chat(
        self,
        user_input: str,
        history: list[dict] | None = None,
    ) -> str:
        """분석 완료 후 추가 대화 (수정/보완 요청)"""
        history = history or []
        messages = [{"role": "system", "content": load_prompt("github")}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        return self.llm.chat(messages)

    def stream(
        self,
        user_input: str,
        history: list[dict] | None = None,
    ):
        """분석 완료 후 추가 대화 스트리밍"""
        history = history or []
        messages = [{"role": "system", "content": load_prompt("github")}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        yield from self.llm.stream(messages)