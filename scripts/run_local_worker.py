from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value

    return values


def describe_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    return f"{name} scheme={parsed.scheme} host={parsed.hostname} port={parsed.port or ''}"


def host_url(value: str) -> str:
    return (
        value.replace("redis://redis:", "redis://127.0.0.1:")
        .replace("http://api:3000", "http://127.0.0.1:3000")
        .replace("bolt://neo4j:", "bolt://127.0.0.1:")
    )


def watchfiles_command() -> list[str]:
    windows_watchfiles = ROOT / ".venv" / "Scripts" / "watchfiles.exe"
    if windows_watchfiles.exists():
        return [str(windows_watchfiles), "arq src.worker.WorkerSettings", "src"]

    unix_watchfiles = ROOT / ".venv" / "bin" / "watchfiles"
    if unix_watchfiles.exists():
        return [str(unix_watchfiles), "arq src.worker.WorkerSettings", "src"]

    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "watchfiles", "arq src.worker.WorkerSettings", "src"]

    return ["watchfiles", "arq src.worker.WorkerSettings", "src"]


def main() -> int:
    env = {
        **read_env(ROOT / ".env"),
        **os.environ,
    }

    env["REDIS_URL"] = host_url(env.get("REDIS_URL", "redis://redis:6379"))
    env["API_BASE_URL"] = host_url(env.get("API_BASE_URL", "http://api:3000/api/v1"))
    env["NEO4J_URL"] = host_url(env.get("NEO4J_URL", "bolt://neo4j:7687"))
    env["NEO4J_USERNAME"] = env.get("NEO4J_USERNAME", env.get("DOCGEN_NEO4J_USERNAME", "neo4j"))
    env["NEO4J_PASSWORD"] = env.get("NEO4J_PASSWORD", "password")
    env["ENVIRONMENT"] = env.get("ENVIRONMENT", "development")
    env["PYTHONUNBUFFERED"] = "1"

    print(describe_url("REDIS_URL", env["REDIS_URL"]), flush=True)
    print(describe_url("API_BASE_URL", env["API_BASE_URL"]), flush=True)
    print(describe_url("NEO4J_URL", env["NEO4J_URL"]), flush=True)

    return subprocess.call(watchfiles_command(), cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
