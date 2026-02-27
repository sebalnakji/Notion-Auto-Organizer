import logging
import re
from typing import Optional
from notion_client import Client

from database.schema import get_setting

logger = logging.getLogger(__name__)

# ── 지원 색상 ──────────────────────────────────────────────────────────────────
VALID_COLORS = {
    "default", "gray", "brown", "orange", "yellow", "green", "blue",
    "purple", "pink", "red",
    "gray_background", "brown_background", "orange_background",
    "yellow_background", "green_background", "blue_background",
    "purple_background", "pink_background", "red_background",
}

# ── 클라이언트 ─────────────────────────────────────────────────────────────────

def get_notion_client() -> Client:
    api_key = get_setting("notion_api_key")
    if not api_key:
        raise ValueError("Notion API 키가 등록되지 않았습니다. 설정에서 먼저 등록해주세요.")
    return Client(auth=api_key)


# ── 연결 / 페이지 확인 ──────────────────────────────────────────────────────────

def verify_connection() -> bool:
    """Notion API 연결 상태 확인"""
    try:
        get_notion_client().users.me()
        logger.info("Notion 연결 성공")
        return True
    except Exception as e:
        logger.error("Notion 연결 실패: %s", e)
        return False


def verify_page(page_id: str) -> dict | None:
    """페이지 ID 유효성 확인. 성공 시 페이지 정보 반환, 실패 시 None."""
    try:
        page = get_notion_client().pages.retrieve(page_id=_normalize_page_id(page_id))
        logger.info("Notion 페이지 확인 성공 - id: %s", page_id)
        return page
    except Exception as e:
        logger.error("Notion 페이지 확인 실패 - id: %s, 오류: %s", page_id, e)
        return None


def get_page_id(ui_page_id: Optional[str] = None) -> str:
    """UI 입력값 우선, 없으면 DB의 notion_page_id 사용."""
    page_id = ui_page_id or get_setting("notion_page_id")
    if not page_id:
        raise ValueError("Notion 페이지 ID가 설정되지 않았습니다. UI 또는 설정에서 등록해주세요.")
    return _normalize_page_id(page_id)


def _normalize_page_id(page_id: str) -> str:
    """Notion 페이지 URL 또는 raw ID → 표준 UUID 형식으로 변환"""
    page_id = page_id.strip().rstrip("/")
    match = re.search(r"[0-9a-f]{32}$", page_id.replace("-", ""))
    if match:
        raw = match.group()
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return page_id


# ── 인라인 파싱 ────────────────────────────────────────────────────────────────
#
# 커스텀 인라인 문법:
#   글씨/배경 색깔 : {color:텍스트}         예) {red:경고}, {blue_background:강조}
#   취소선         : ~~텍스트~~
#   밑줄           : __텍스트__
#   인라인 수식    : $수식$

_INLINE_PATTERN = re.compile(
    r"\{(\w+):(.+?)\}"           # {color:text}
    r"|(\*\*\*(.+?)\*\*\*)"      # bold+italic
    r"|(\*\*(.+?)\*\*)"          # bold
    r"|(\*(.+?)\*)"              # italic
    r"|(__(.+?)__)"              # underline
    r"|(~~(.+?)~~)"              # strikethrough
    r"|(`(.+?)`)"                # inline code
    r"|(\$(.+?)\$)"              # inline equation
    r"|(\[(.+?)\]\((.+?)\))"     # link
)


def _parse_inline(text: str) -> list[dict]:
    """인라인 마크다운을 Notion rich_text 리스트로 변환"""
    rich_texts = []
    last = 0

    for m in _INLINE_PATTERN.finditer(text):
        if m.start() > last:
            rich_texts.append(_text_obj(text[last:m.start()]))

        if m.group(1):    # {color:text}
            color = m.group(1) if m.group(1) in VALID_COLORS else "default"
            rich_texts.append(_text_obj(m.group(2), color=color))
        elif m.group(3):  # bold+italic
            rich_texts.append(_text_obj(m.group(4), bold=True, italic=True))
        elif m.group(5):  # bold
            rich_texts.append(_text_obj(m.group(6), bold=True))
        elif m.group(7):  # italic
            rich_texts.append(_text_obj(m.group(8), italic=True))
        elif m.group(9):  # underline
            rich_texts.append(_text_obj(m.group(10), underline=True))
        elif m.group(11): # strikethrough
            rich_texts.append(_text_obj(m.group(12), strikethrough=True))
        elif m.group(13): # inline code
            rich_texts.append(_text_obj(m.group(14), code=True))
        elif m.group(15): # inline equation
            rich_texts.append(_equation_inline_obj(m.group(16)))
        elif m.group(17): # link
            rich_texts.append(_text_obj(m.group(18), url=m.group(19)))

        last = m.end()

    if last < len(text):
        rich_texts.append(_text_obj(text[last:]))

    return rich_texts or [_text_obj(text)]


def _text_obj(
    content: str,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
    underline: bool = False,
    strikethrough: bool = False,
    color: str = "default",
    url: str | None = None,
) -> dict:
    return {
        "type": "text",
        "text": {"content": content, "link": {"url": url} if url else None},
        "annotations": {
            "bold": bold, "italic": italic, "code": code,
            "underline": underline, "strikethrough": strikethrough,
            "color": color,
        },
    }


def _equation_inline_obj(expression: str) -> dict:
    return {
        "type": "equation",
        "equation": {"expression": expression},
        "annotations": {
            "bold": False, "italic": False, "code": False,
            "underline": False, "strikethrough": False, "color": "default",
        },
    }


# ── 블록 생성 헬퍼 ─────────────────────────────────────────────────────────────

def _block(type_: str, data: dict) -> dict:
    """블록 객체 기본 팩토리"""
    return {"object": "block", "type": type_, type_: data}


def _heading_block(text: str, level: int, toggleable: bool = False) -> dict:
    key = f"heading_{level}"
    return _block(key, {"rich_text": _parse_inline(text), "is_toggleable": toggleable})

def _paragraph_block(rich_text: list[dict]) -> dict:
    return _block("paragraph", {"rich_text": rich_text})

def _bulleted_block(rich_text: list[dict]) -> dict:
    return _block("bulleted_list_item", {"rich_text": rich_text})

def _numbered_block(rich_text: list[dict]) -> dict:
    return _block("numbered_list_item", {"rich_text": rich_text})

def _todo_block(rich_text: list[dict], checked: bool = False) -> dict:
    return _block("to_do", {"rich_text": rich_text, "checked": checked})

def _toggle_block(rich_text: list[dict]) -> dict:
    return _block("toggle", {"rich_text": rich_text})

def _quote_block(rich_text: list[dict]) -> dict:
    return _block("quote", {"rich_text": rich_text})

def _callout_block(rich_text: list[dict], emoji: str = "💡") -> dict:
    return _block("callout", {
        "rich_text": rich_text,
        "icon": {"type": "emoji", "emoji": emoji},
    })

def _code_block(code: str, language: str = "plain text") -> dict:
    return _block("code", {"rich_text": [_text_obj(code)], "language": language})

def _divider_block() -> dict:
    return _block("divider", {})

def _toc_block() -> dict:
    return _block("table_of_contents", {})

def _equation_block(expression: str) -> dict:
    return _block("equation", {"expression": expression})

def _image_block(url: str) -> dict:
    return _block("image", {"type": "external", "external": {"url": url}})

def _bookmark_block(url: str, caption: str = "") -> dict:
    data: dict = {"url": url}
    if caption:
        data["caption"] = [_text_obj(caption)]
    return _block("bookmark", data)

def _table_block(rows: list[list[str]], has_header: bool = True) -> dict:
    """표 블록 생성. rows[0]이 헤더 행."""
    if not rows:
        return _paragraph_block([_text_obj("")])
    col_count = max(len(row) for row in rows)
    table_rows = []
    for row in rows:
        cells = [_parse_inline((row[c] if c < len(row) else "").strip()) for c in range(col_count)]
        table_rows.append(_block("table_row", {"cells": cells}))
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": col_count,
            "has_column_header": has_header,
            "has_row_header": False,
            "children": table_rows,
        },
    }


# ── 마크다운 → Notion 블록 변환 ────────────────────────────────────────────────
#
# 커스텀 블록 문법:
#   토글          : >>> 텍스트
#   토글 제목     : #>1 텍스트 / #>2 텍스트 / #>3 텍스트
#   callout       : !> 텍스트  또는  !>🔥> 텍스트  (이모지 지정)
#   블록 수식     : $$수식$$  (한 줄)
#   목차          : [TOC]
#   북마크        : [bookmark](url)  또는  단독 URL 줄
#   이미지        : ![alt](url)
#   체크박스      : - [ ] 텍스트  /  - [x] 텍스트

_URL_RE = re.compile(r"^https?://\S+$")
_TABLE_ROW_RE = re.compile(r"^\|(.+\|)+$")
_TABLE_SEP_RE = re.compile(r"^\|[-| :]+\|$")


def markdown_to_blocks(markdown: str) -> list[dict]:
    """마크다운 텍스트를 Notion 블록 리스트로 변환"""
    blocks = []
    lines = markdown.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        s = line.strip()

        # 코드 블록
        if s.startswith("```"):
            language = s[3:].strip() or "plain text"
            code_lines, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            blocks.append(_code_block("\n".join(code_lines), language))

        # 블록 수식 $$...$$
        elif s.startswith("$$") and s.endswith("$$") and len(s) > 4:
            blocks.append(_equation_block(s[2:-2].strip()))

        # 목차
        elif s.upper() == "[TOC]":
            blocks.append(_toc_block())

        # 토글 제목 #>1 / #>2 / #>3
        elif re.match(r"^#>([123]) ", s):
            blocks.append(_heading_block(s[4:].strip(), level=int(s[2]), toggleable=True))

        # 일반 제목
        elif s.startswith("### "):
            blocks.append(_heading_block(s[4:].strip(), level=3))
        elif s.startswith("## "):
            blocks.append(_heading_block(s[3:].strip(), level=2))
        elif s.startswith("# "):
            blocks.append(_heading_block(s[2:].strip(), level=1))

        # 구분선
        elif re.match(r"^---+$", s):
            blocks.append(_divider_block())

        # callout !>emoji> 또는 !>
        elif s.startswith("!>"):
            m = re.match(r"^!>(\S+)> (.+)$", s)
            emoji, text = (m.group(1), m.group(2)) if m else ("💡", s[2:].strip())
            blocks.append(_callout_block(_parse_inline(text), emoji=emoji))

        # 토글 >>>
        elif s.startswith(">>> "):
            blocks.append(_toggle_block(_parse_inline(s[4:].strip())))

        # 체크박스
        elif re.match(r"^- \[[ xX]\] ", s):
            blocks.append(_todo_block(_parse_inline(s[6:].strip()), checked=s[3] in ("x", "X")))

        # 번호 없는 목록
        elif re.match(r"^[-*] ", s):
            blocks.append(_bulleted_block(_parse_inline(s[2:].strip())))

        # 번호 있는 목록
        elif re.match(r"^\d+\. ", s):
            blocks.append(_numbered_block(_parse_inline(re.sub(r"^\d+\. ", "", s).strip())))

        # 인용
        elif s.startswith("> "):
            blocks.append(_quote_block(_parse_inline(s[2:].strip())))

        # 표
        elif _TABLE_ROW_RE.match(s):
            table_lines = []
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i].strip()):
                table_lines.append(lines[i].strip())
                i += 1
            i -= 1
            rows = [
                [c.strip() for c in tl.strip("|").split("|")]
                for tl in table_lines if not _TABLE_SEP_RE.match(tl)
            ]
            if rows:
                blocks.append(_table_block(rows))

        # 이미지
        elif re.match(r"^!\[.*?\]\(.+?\)$", s):
            blocks.append(_image_block(re.search(r"\((.+?)\)$", s).group(1)))

        # 북마크 [bookmark](url)
        elif re.match(r"^\[bookmark\]\(.+?\)$", s):
            blocks.append(_bookmark_block(re.search(r"\((.+?)\)$", s).group(1)))

        # 단독 URL → 북마크
        elif _URL_RE.match(s):
            blocks.append(_bookmark_block(s))

        # 빈 줄 스킵
        elif s == "":
            pass

        # 일반 단락
        else:
            blocks.append(_paragraph_block(_parse_inline(s)))

        i += 1

    return blocks


# ── Notion 업로드 ──────────────────────────────────────────────────────────────

def upload_to_notion(
    markdown: str,
    title: str,
    page_id: Optional[str] = None,
) -> str:
    """
    마크다운을 Notion 페이지의 하위 페이지로 업로드.
    생성된 페이지 URL 반환.
    """
    client = get_notion_client()
    parent_id = get_page_id(page_id)
    blocks = markdown_to_blocks(markdown)

    CHUNK_SIZE = 100
    new_page = client.pages.create(
        parent={"page_id": parent_id},
        properties={"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        children=blocks[:CHUNK_SIZE],
    )

    new_page_id = new_page["id"]
    logger.info("Notion 페이지 생성 완료 - id: %s", new_page_id)

    for i in range(CHUNK_SIZE, len(blocks), CHUNK_SIZE):
        client.blocks.children.append(
            block_id=new_page_id,
            children=blocks[i:i + CHUNK_SIZE],
        )
        logger.info("Notion 블록 추가 업로드 - %d~%d", i, i + CHUNK_SIZE)

    return new_page.get("url", f"https://notion.so/{new_page_id.replace('-', '')}")