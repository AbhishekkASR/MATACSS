"""Backend-only OpenAI adapter behind MATACSS-owned LLM interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, Sequence

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, OpenAIError

from app.core.config import Settings, settings

MessageRole = Literal["system", "developer", "user", "assistant"]


class LLMFailureKind(StrEnum):
    CONFIGURATION = "configuration"
    INVALID_REQUEST = "invalid_request"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    API = "api"
    INVALID_RESPONSE = "invalid_response"


class LLMProviderError(RuntimeError):
    """Safe application-level error for configuration, transport, or output failures."""

    def __init__(self, kind: LLMFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class LLMMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    request_id: str | None = None


class LLMProvider(Protocol):
    def complete(self, messages: Sequence[LLMMessage]) -> LLMResponse:
        """Complete a structured chat request or raise LLMProviderError."""


class OpenAILLMProvider:
    """Synchronous OpenAI/Azure OpenAI adapter behind the MATACSS interface."""

    def __init__(self, configuration: Settings | None = None) -> None:
        self._configuration = configuration or settings
        self._model = self._configuration.openai_model
        self._timeout_seconds = self._configuration.openai_timeout_seconds
        azure_values = (
            self._configuration.azure_openai_endpoint,
            self._configuration.azure_openai_api_key,
            self._configuration.azure_openai_deployment,
        )
        if any(azure_values):
            if not all(azure_values):
                raise LLMProviderError(LLMFailureKind.CONFIGURATION, "AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT must all be configured.")
            endpoint = self._configuration.azure_openai_endpoint.removesuffix("/openai/v1")
            self._model = self._configuration.azure_openai_deployment
            self._timeout_seconds = self._configuration.azure_openai_timeout_seconds
            self._client = OpenAI(api_key=self._configuration.azure_openai_api_key, base_url=f"{endpoint}/openai/v1/", timeout=self._timeout_seconds, max_retries=0)
            return
        if not self._configuration.openai_api_key:
            raise LLMProviderError(LLMFailureKind.CONFIGURATION, "OPENAI_API_KEY is required to create the OpenAI provider.")
        self._client = OpenAI(api_key=self._configuration.openai_api_key, timeout=self._timeout_seconds, max_retries=0)

    def complete(self, messages: Sequence[LLMMessage]) -> LLMResponse:
        if not messages or any(not message.content.strip() for message in messages):
            raise LLMProviderError(LLMFailureKind.INVALID_REQUEST, "At least one non-empty LLM message is required.")
        try:
            response = self._client.chat.completions.create(model=self._model, messages=[{"role": message.role, "content": message.content} for message in messages], timeout=self._timeout_seconds)
        except APITimeoutError:
            raise LLMProviderError(LLMFailureKind.TIMEOUT, "The LLM request timed out.") from None
        except APIConnectionError:
            raise LLMProviderError(LLMFailureKind.CONNECTION, "The LLM service could not be reached.") from None
        except APIStatusError:
            raise LLMProviderError(LLMFailureKind.API, "The LLM service rejected or failed the request.") from None
        except OpenAIError:
            raise LLMProviderError(LLMFailureKind.API, "The LLM request failed.") from None
        choices = getattr(response, "choices", None)
        if not isinstance(choices, (list, tuple)) or not choices:
            raise LLMProviderError(LLMFailureKind.INVALID_RESPONSE, "The LLM service returned no completion choices.")
        message = getattr(choices[0], "message", None)
        content, model, request_id = getattr(message, "content", None), getattr(response, "model", None), getattr(response, "id", None)
        if not isinstance(content, str) or not content.strip() or not isinstance(model, str) or not model or (request_id is not None and not isinstance(request_id, str)):
            raise LLMProviderError(LLMFailureKind.INVALID_RESPONSE, "The LLM service returned an empty or malformed completion.")
        return LLMResponse(content=content, model=model, request_id=request_id or None)
