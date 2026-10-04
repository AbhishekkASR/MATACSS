"""Focused tests for the OpenAI and Azure provider foundation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from openai import APITimeoutError, OpenAIError

import app.core.llm_provider as llm_provider
from app.core.config import Settings
from app.core.llm_provider import LLMFailureKind, LLMMessage, LLMProviderError, OpenAILLMProvider


class FakeCompletions:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response, self.error = response, error
        self.request: dict[str, Any] | None = None

    def create(self, **request: Any) -> object:
        self.request = request
        if self.error:
            raise self.error
        return self.response


def configured_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    values = {
        "APP_ENV": "development", "OPENAI_API_KEY": "test-openai-secret",
        "OPENAI_MODEL": "test-model", "OPENAI_TIMEOUT_SECONDS": "7.5",
        "AZURE_OPENAI_ENDPOINT": "", "AZURE_OPENAI_API_KEY": "",
        "AZURE_OPENAI_DEPLOYMENT": "", "AZURE_OPENAI_TIMEOUT_SECONDS": "30",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return Settings()


def make_provider(monkeypatch: pytest.MonkeyPatch, configuration: Settings, completions: FakeCompletions, constructor_args: dict[str, object] | None = None) -> OpenAILLMProvider:
    def fake_client(**kwargs: object) -> object:
        if constructor_args is not None:
            constructor_args.update(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(llm_provider, "OpenAI", fake_client)
    return OpenAILLMProvider(configuration=configuration)


def response(content: object = "completion", model: str = "test-model") -> object:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], model=model, id="req-1")


def test_direct_openai_provider_uses_configured_model_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    completions = FakeCompletions(response())
    provider = make_provider(monkeypatch, configured_settings(monkeypatch), completions)
    result = provider.complete([LLMMessage(role="user", content="hello")])
    assert result.content == "completion"
    assert completions.request == {"model": "test-model", "messages": [{"role": "user", "content": "hello"}], "timeout": 7.5}


def test_direct_openai_client_has_no_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    constructor_args: dict[str, object] = {}
    make_provider(monkeypatch, configured_settings(monkeypatch), FakeCompletions(response()), constructor_args)
    assert constructor_args == {"api_key": "test-openai-secret", "timeout": 7.5, "max_retries": 0}


def test_azure_provider_overrides_model_endpoint_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = configured_settings(monkeypatch, AZURE_OPENAI_ENDPOINT="https://matacss-test.openai.azure.com/openai/v1/", AZURE_OPENAI_API_KEY="test-azure-secret", AZURE_OPENAI_DEPLOYMENT="deployment-v2", AZURE_OPENAI_TIMEOUT_SECONDS="11.5")
    constructor_args: dict[str, object] = {}
    completions = FakeCompletions(response("Azure completion", "deployment-v2"))
    provider = make_provider(monkeypatch, settings, completions, constructor_args)
    assert provider.complete([LLMMessage(role="user", content="hello")]).model == "deployment-v2"
    assert constructor_args == {"api_key": "test-azure-secret", "base_url": "https://matacss-test.openai.azure.com/openai/v1/", "timeout": 11.5, "max_retries": 0}


@pytest.mark.parametrize("missing", ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"])
def test_partial_azure_configuration_is_rejected(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    values = {
        "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "test-secret",
        "AZURE_OPENAI_DEPLOYMENT": "deployment",
    }
    values[missing] = ""
    configuration = configured_settings(monkeypatch, **values)
    with pytest.raises(LLMProviderError) as error:
        OpenAILLMProvider(configuration)
    assert error.value.kind == LLMFailureKind.CONFIGURATION


def test_missing_direct_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(LLMProviderError, match="OPENAI_API_KEY"):
        OpenAILLMProvider(configured_settings(monkeypatch, OPENAI_API_KEY=""))


@pytest.mark.parametrize("timeout_name", ["OPENAI_TIMEOUT_SECONDS", "AZURE_OPENAI_TIMEOUT_SECONDS"])
def test_timeouts_must_be_positive_and_finite(monkeypatch: pytest.MonkeyPatch, timeout_name: str) -> None:
    monkeypatch.setenv(timeout_name, "inf")
    with pytest.raises(ValueError, match=timeout_name):
        Settings()


def test_credentials_are_redacted_from_settings_representation(monkeypatch: pytest.MonkeyPatch) -> None:
    configuration = configured_settings(monkeypatch, OPENAI_API_KEY="never-print-this", AZURE_OPENAI_API_KEY="")
    assert "never-print-this" not in repr(configuration)


@pytest.mark.parametrize("error", [APITimeoutError(request=None), OpenAIError("private detail")])
def test_provider_maps_sdk_errors_without_leaking_details(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    provider = make_provider(monkeypatch, configured_settings(monkeypatch), FakeCompletions(error=error))
    with pytest.raises(LLMProviderError) as raised:
        provider.complete([LLMMessage(role="user", content="private prompt")])
    assert raised.value.kind in {LLMFailureKind.TIMEOUT, LLMFailureKind.API}
    assert "private" not in str(raised.value)


def test_provider_rejects_empty_input_and_malformed_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = make_provider(monkeypatch, configured_settings(monkeypatch), FakeCompletions(response(None)))
    with pytest.raises(LLMProviderError) as error:
        provider.complete([])
    assert error.value.kind == LLMFailureKind.INVALID_REQUEST
    with pytest.raises(LLMProviderError) as error:
        provider.complete([LLMMessage(role="user", content="hello")])
    assert error.value.kind == LLMFailureKind.INVALID_RESPONSE
