# Notion-Auto-Organizer

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)
![Notion](https://img.shields.io/badge/Notion_API-000000?logo=notion&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-412991?logo=openai&logoColor=white)
![Anthropic](https://img.shields.io/badge/Anthropic-Claude-D97757?logoColor=white)
![Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?logo=google&logoColor=white)

LLM을 활용하여 개념, GitHub 레포지토리, 파일, 연구자료를 자동으로 정리하고 **Notion 페이지에 바로 업로드**하는 로컬 유틸리티입니다.

## 주요 기능

- **다중 LLM 지원** — Claude, OpenAI GPT, Google Gemini 중 선택하여 사용
- **타입별 정리** — 개념정리 / 깃허브 / 파일 / 연구자료 4가지 기본 타입 + 커스텀 타입 추가 가능
- **GitHub 레포 분석** — 레포지토리를 클론하여 구조, 기능, 기술 스택을 자동 문서화
- **Notion 자동 업로드** — 마크다운 → Notion 블록 변환 후 지정 페이지에 업로드
- **세션 관리** — 타입별 대화 세션 저장, 즐겨찾기, 이름 자동 생성
- **중간 파일 저장** — 세션별 draft 파일 관리로 수정 시 토큰 효율 최적화
- **프롬프트 커스터마이징** — 메인/타입별 프롬프트 UI에서 직접 수정 가능
- **토큰 사용량 로깅** — 타입·세션별 토큰 사용량 별도 로그 파일로 기록

## 기술 스택

| 구분 | 기술 |
|------|------|
| **Backend** | Python 3.11, Streamlit |
| **Database** | SQLite (API 키, 프롬프트, 세션, 대화 이력 저장) |
| **LLM** | OpenAI API, Anthropic API, Google Gemini API |
| **외부 연동** | Notion API, GitHub (GitPython) |

## 실행 방법

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

streamlit run src/main.py
```

`http://localhost:8501` 에서 확인할 수 있습니다.

초기 실행 후 **설정** 화면에서 아래 항목을 등록해주세요:

- LLM API 키 (Claude / OpenAI / Gemini 중 하나 이상)
- Notion API 키 및 업로드 대상 페이지 ID
- GitHub Personal Access Token (Private 레포 분석 시)

## 워크플로우

1. **타입 선택** — 정리할 내용에 맞는 타입을 선택합니다.
   - **개념정리** — 개념, 키워드, 기술 등을 개요·핵심 개념·예시 순으로 문서화
   - **깃허브** — GitHub 레포지토리 URL을 입력하면 구조·기능·기술 스택을 자동 분석하여 문서화
   - **파일** — 업로드한 파일의 핵심 내용, 주요 데이터, 인사이트를 정리
   - **연구자료** — 주제를 입력하면 웹 리서치를 통해 관련 자료를 수집하고 목적·방법론·결과·결론 순으로 정리
2. **정리 요청** — 대화창에 내용을 입력하면 LLM이 결과물을 생성하여 UI에 바로 표시됩니다.
3. **수정·보완** — 결과물을 확인하며 LLM과 추가 대화로 내용을 조율합니다.
4. **Notion 업로드** — 최종 결과물이 완성되면 **Notion 저장** 버튼으로 지정한 페이지에 업로드합니다.

수정 요청 시에는 전체 대화 히스토리가 아닌 현재 문서와 수정 요청만 LLM에 전달되어 토큰 낭비 없이 효율적으로 조율할 수 있습니다.

## 설계 포인트

**API 키 보안** — API 키는 `.env`가 아닌 로컬 SQLite DB에 Fernet(AES-128) 방식으로 암호화하여 저장되며, `.gitignore`로 `data/` 디렉토리 전체를 제외합니다.

**토큰 효율 최적화** — 수정 요청 시 전체 대화 히스토리 대신 `data/drafts/{session_id}.md`의 현재 문서와 수정 요청만 LLM에 전달합니다.

**동적 타입 시스템** — 기본 4개 타입(개념정리/깃허브/파일/연구자료)은 수정·삭제 불가하며, 기본 타입을 베이스로 커스텀 타입을 자유롭게 추가할 수 있습니다.

**멀티 LLM 팩토리** — `get_llm_client(provider)`로 통일된 인터페이스를 제공하며, 등록된 API 키 기준으로 사용 가능한 LLM만 UI에 노출됩니다.

## ⚠️ 프로젝트 조기 중단

본 프로젝트는 기능 구현 및 테스트 단계에서 개발을 중단하였습니다.

**중단 이유**

LLM 서비스의 구독(Claude Pro, Gemini Pro 등)과 API 사용 비용은 완전히 별개입니다. 구독 플랜으로는 API를 사용할 수 없으며, API 호출은 별도의 크레딧 구매가 필요합니다. 무료 티어의 경우 분당 요청 수와 일일 한도가 매우 제한적이어서 실사용 수준의 응답 품질을 기대하기 어려웠습니다.

이러한 이유로 핵심 기능(LLM 연동, Notion 업로드, GitHub 분석, 세션 관리, 드래프트 저장)의 구현과 동작 검증까지만 진행하였으며, UI 개편 및 추가 기능 고도화는 진행하지 않았습니다.