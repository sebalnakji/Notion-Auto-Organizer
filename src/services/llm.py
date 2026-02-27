import logging
from abc import ABC, abstractmethod
from typing import Generator

from openai import OpenAI
import anthropic
import google.generativeai as genai

import os
from database.schema import get_setting, get_available_llm_providers

token_logger = logging.getLogger('token_usage')

logger = logging.getLogger(__name__)


# ── Base ──────────────────────────────────────────────────────────────────────

class BaseLLMClient(ABC):
    """모든 LLM 클라이언트가 구현해야 하는 공통 인터페이스"""

    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> str:
        """단일 응답 반환"""
        ...

    @abstractmethod
    def stream(self, messages: list[dict], **kwargs) -> Generator[str, None, None]:
        """스트리밍 응답 반환"""
        ...


# ── Clients ───────────────────────────────────────────────────────────────────

class OpenAIClient(BaseLLMClient):
    def __init__(self, model: str = None):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.2")
        api_key = get_setting("openai_api_key")
        if not api_key:
            raise ValueError("[LLM] OpenAI API 키가 등록되지 않았습니다.")
        self.client = OpenAI(api_key=api_key)
        logger.info("[LLM] OpenAI 클라이언트 초기화 완료 - model: %s", self.model)

    def chat(self, messages: list[dict], **kwargs) -> str:
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, **kwargs,
        )
        usage = response.usage
        token_logger.info(
            "[TOKEN] provider=openai model=%s input=%d output=%d total=%d",
            self.model, usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
        )
        return response.choices[0].message.content

    def stream(self, messages: list[dict], **kwargs) -> Generator[str, None, None]:
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, stream=True, **kwargs,
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class ClaudeClient(BaseLLMClient):
    def __init__(self, model: str = None):
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        api_key = get_setting("anthropic_api_key")
        if not api_key:
            raise ValueError("[LLM] Anthropic API 키가 등록되지 않았습니다.")
        self.client = anthropic.Anthropic(api_key=api_key)
        logger.info("[LLM] Claude 클라이언트 초기화 완료 - model: %s", self.model)

    def chat(self, messages: list[dict], **kwargs) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=kwargs.pop("max_tokens", 4096),
            messages=messages,
            **kwargs,
        )
        token_logger.info(
            "[TOKEN] provider=claude model=%s input=%d output=%d total=%d",
            self.model, response.usage.input_tokens, response.usage.output_tokens,
            response.usage.input_tokens + response.usage.output_tokens,
        )
        return response.content[0].text

    def stream(self, messages: list[dict], **kwargs) -> Generator[str, None, None]:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=kwargs.pop("max_tokens", 4096),
            messages=messages,
            **kwargs,
        ) as stream:
            for text in stream.text_stream:
                yield text


class GeminiClient(BaseLLMClient):
    def __init__(self, model: str = None):
        self.model = model or os.getenv("GOOGLE_MODEL", "gemini-3.1-pro-preview")
        api_key = get_setting("google_api_key")
        if not api_key:
            raise ValueError("[LLM] Google API 키가 등록되지 않았습니다.")
        genai.configure(api_key=api_key)
        self.client = genai.GenerativeModel(self.model)
        logger.info("[LLM] Gemini 클라이언트 초기화 완료 - model: %s", self.model)

    def _to_gemini_format(self, messages: list[dict]) -> tuple[str, list]:
        """openai 포맷 messages -> gemini 포맷 변환"""
        system_prompt = ""
        history = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            elif msg["role"] == "user":
                history.append({"role": "user", "parts": [msg["content"]]})
            elif msg["role"] == "assistant":
                history.append({"role": "model", "parts": [msg["content"]]})
        return system_prompt, history

    def chat(self, messages: list[dict], **kwargs) -> str:
        _, history = self._to_gemini_format(messages)
        chat = self.client.start_chat(history=history[:-1])
        last_user_msg = history[-1]["parts"][0] if history else ""
        return chat.send_message(last_user_msg).text

    def stream(self, messages: list[dict], **kwargs) -> Generator[str, None, None]:
        _, history = self._to_gemini_format(messages)
        chat = self.client.start_chat(history=history[:-1])
        last_user_msg = history[-1]["parts"][0] if history else ""
        for chunk in chat.send_message(last_user_msg, stream=True):
            yield chunk.text


# ── Factory ───────────────────────────────────────────────────────────────────

PROVIDER_MAP = {
    "openai": OpenAIClient,
    "claude": ClaudeClient,
    "gemini": GeminiClient,
}


def get_llm_client(provider: str | None = None, model: str | None = None) -> BaseLLMClient:
    """
    provider 미지정 시 등록된 API 키 기준으로 자동 선택.
    우선순위: claude → openai → gemini
    """
    if provider:
        provider = provider.lower()
    else:
        available = get_available_llm_providers()
        if not available:
            raise ValueError("[LLM] 등록된 API 키가 없습니다. 설정에서 먼저 등록해주세요.")
        provider = available[0]

    client_cls = PROVIDER_MAP.get(provider)
    if not client_cls:
        raise ValueError(f"[LLM] 지원하지 않는 provider: {provider}. 가능한 값: {list(PROVIDER_MAP.keys())}")
    return client_cls(model=model) if model else client_cls()