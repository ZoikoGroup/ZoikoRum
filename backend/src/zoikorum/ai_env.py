"""Merge the deploy-time AI settings into backend/.env.

The deploy workflow passes a repository secret on standard input. Only AI
settings are accepted so the secret cannot rewrite database, auth or billing
configuration. Values are never printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ALLOWED_KEYS = frozenset({
    "ZK_AI_PROVIDER",
    "ZK_ANTHROPIC_API_KEY",
    "ZK_AI_MODEL",
    "ZK_OLLAMA_URL",
    "ZK_OLLAMA_MODEL",
})
PROVIDERS = frozenset({"offline", "anthropic", "ollama"})


class ConfigError(ValueError):
    pass


def parse(text: str) -> dict[str, str]:
    updates: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"invalid line: {raw!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_KEYS:
            raise ConfigError(f"unsupported key: {key}")
        updates[key] = value.strip()
    if not updates:
        raise ConfigError("no AI settings found")
    provider = updates.get("ZK_AI_PROVIDER")
    if provider is not None:
        if provider not in PROVIDERS:
            raise ConfigError(f"invalid ZK_AI_PROVIDER: {provider}")
        if provider == "anthropic" and not updates.get("ZK_ANTHROPIC_API_KEY"):
            raise ConfigError("ZK_ANTHROPIC_API_KEY is required for the anthropic provider")
    return updates


def merge(existing: str, updates: dict[str, str]) -> str:
    keys = set(updates)
    kept = [
        line
        for line in existing.splitlines()
        if line.split("=", 1)[0].strip() not in keys
    ]
    kept.extend(f"{key}={value}" for key, value in updates.items())
    return "\n".join(kept).rstrip("\n") + "\n"


def apply(text: str, env_path: Path) -> None:
    updates = parse(text)
    existed = env_path.exists()
    existing = env_path.read_text() if existed else ""
    env_path.write_text(merge(existing, updates))
    if not existed:
        env_path.chmod(0o600)


def main() -> int:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    try:
        apply(sys.stdin.read(), env_path)
    except (ConfigError, OSError) as exc:
        print(f"AI configuration not applied: {exc}", file=sys.stderr)
        return 1
    print(f"AI configuration applied to {env_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
