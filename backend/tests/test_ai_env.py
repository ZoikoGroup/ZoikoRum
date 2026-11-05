from __future__ import annotations

import pytest

from zoikorum.ai_env import ConfigError, apply, merge, parse


@pytest.mark.unit
def test_parse_accepts_the_allow_listed_ai_settings():
    updates = parse(
        "# deploy-time AI settings\n"
        "ZK_AI_PROVIDER=anthropic\n"
        "ZK_ANTHROPIC_API_KEY=sk-ant-example\n"
        "ZK_AI_MODEL=claude-sonnet-4-5\n"
    )
    assert updates == {
        "ZK_AI_PROVIDER": "anthropic",
        "ZK_ANTHROPIC_API_KEY": "sk-ant-example",
        "ZK_AI_MODEL": "claude-sonnet-4-5",
    }


@pytest.mark.unit
def test_parse_rejects_non_ai_settings():
    with pytest.raises(ConfigError):
        parse("ZK_DATABASE_URL=postgresql://production\n")


@pytest.mark.unit
def test_parse_rejects_an_unknown_provider():
    with pytest.raises(ConfigError):
        parse("ZK_AI_PROVIDER=somewhere\n")


@pytest.mark.unit
def test_parse_requires_a_key_for_anthropic():
    with pytest.raises(ConfigError):
        parse("ZK_AI_PROVIDER=anthropic\n")


@pytest.mark.unit
def test_merge_replaces_only_the_supplied_keys():
    existing = "ZK_DATABASE_URL=postgresql://db\nZK_AI_PROVIDER=offline\nZK_AI_MODEL=old\n"
    merged = merge(existing, {"ZK_AI_PROVIDER": "ollama", "ZK_OLLAMA_MODEL": "qwen2.5:0.5b"})
    assert "ZK_DATABASE_URL=postgresql://db" in merged
    assert "ZK_AI_PROVIDER=ollama" in merged
    assert "ZK_AI_MODEL=old" in merged
    assert "ZK_OLLAMA_MODEL=qwen2.5:0.5b" in merged
    assert merged.count("ZK_AI_PROVIDER=") == 1


@pytest.mark.unit
def test_apply_creates_a_private_env_file(tmp_path):
    env_path = tmp_path / ".env"
    apply("ZK_AI_PROVIDER=offline\n", env_path)
    assert env_path.read_text() == "ZK_AI_PROVIDER=offline\n"
