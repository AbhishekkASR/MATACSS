"""Shared test boundaries."""

import pytest

import app.core.config as config
from app.core.llm_provider import LLMFailureKind, LLMProviderError


@pytest.fixture(autouse=True)
def isolate_jwt_configuration():
    """Keep local .env authentication settings out of legacy unit-test fixtures."""
    original_secret = config.settings.jwt_secret
    object.__setattr__(config.settings, "jwt_secret", "")
    try:
        yield
    finally:
        object.__setattr__(config.settings, "jwt_secret", original_secret)


@pytest.fixture(autouse=True)
def no_external_llm_provider(monkeypatch):
    """Prevent backend tests from constructing or contacting the real provider."""

    class DisabledLLMProvider:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def complete(self, _messages):
            raise LLMProviderError(
                LLMFailureKind.CONFIGURATION,
                "LLM provider is disabled in tests.",
            )

    monkeypatch.setattr(
        "app.services.assessment_orchestration_service.OpenAILLMProvider",
        DisabledLLMProvider,
    )
