from __future__ import annotations

import pytest

from theseus.config import Settings


def make(**env: str) -> Settings:
    """Settings from the given environment only, never from a developer's .env file."""
    return Settings(_env_file=None, **{k.lower(): v for k, v in env.items()})


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(Settings.model_fields):
        monkeypatch.delenv(name.upper(), raising=False)


def test_defaults_match_the_spec() -> None:
    s = make()
    assert s.theseus_mode == "replay"
    assert s.llm_model == "openai/zai-org/GLM-5.3"
    assert s.llm_fast_model == "openai/zai-org/GLM-5.3-Flash"
    assert s.llm_api_base == "https://api.inference.crusoecloud.com/v1"
    assert s.jev_base_url == "https://api.typesafe.ai"
    assert s.jev_model == "jev-latest"
    assert (s.falkordb_host, s.falkordb_port, s.falkordb_tls) == ("localhost", 6379, False)
    assert s.theseus_world_root == "demo-infra"
    assert s.repos == []


def test_environment_overrides_a_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THESEUS_MODE", "live")
    monkeypatch.setenv("FALKORDB_PORT", "6390")
    monkeypatch.setenv("FALKORDB_TLS", "true")
    s = Settings(_env_file=None)
    assert s.theseus_mode == "live"
    assert s.falkordb_port == 6390
    assert s.falkordb_tls is True


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        make(THESEUS_MODE="sometimes")


def test_repos_are_split_and_trimmed() -> None:
    assert make(THESEUS_REPOS=" owner/theseus , other/repo ").repos == ["owner/theseus", "other/repo"]


def test_secrets_never_show_in_repr() -> None:
    s = make(LLM_API_KEY="sk-not-real", FALKORDB_PASSWORD="hunter2")
    assert "sk-not-real" not in repr(s)
    assert "hunter2" not in repr(s)
    assert s.llm_api_key is not None
    assert s.llm_api_key.get_secret_value() == "sk-not-real"


def test_switching_models_is_only_settings() -> None:
    s = make(LLM_MODEL="anthropic/claude-opus-5-5", LLM_API_BASE="https://api.anthropic.com")
    assert (s.llm_model, s.llm_api_base) == ("anthropic/claude-opus-5-5", "https://api.anthropic.com")


def test_blank_values_mean_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_API_BASE", "LLM_API_KEY", "FALKORDB_PORT", "FALKORDB_PASSWORD"):
        monkeypatch.setenv(name, "")
    s = Settings(_env_file=None)
    assert s.llm_api_base == "https://api.inference.crusoecloud.com/v1"
    assert s.falkordb_port == 6379
    assert s.llm_api_key is None and s.falkordb_password is None
