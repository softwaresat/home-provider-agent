"""Inspect DeepSeek connection errors without printing the API key."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from openai import OpenAI

from app import config


def dump_exc(label: str, exc: BaseException) -> None:
    print(label, type(exc).__name__, str(exc)[:300])
    cause = getattr(exc, "__cause__", None)
    if cause:
        print("  cause", type(cause).__name__, str(cause)[:300])
    context = getattr(exc, "__context__", None)
    if context and context is not cause:
        print("  context", type(context).__name__, str(context)[:300])


def try_base(url: str) -> None:
    print("--- openai client", url)
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=url, timeout=30.0)
    try:
        response = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": "Say hi in 3 words"}],
            temperature=0,
        )
        print("ok", (response.choices[0].message.content or "")[:200])
    except Exception as exc:  # noqa: BLE001
        dump_exc("fail", exc)


def try_httpx(url: str) -> None:
    print("--- httpx", url)
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
            timeout=20.0,
        )
        print("status", resp.status_code, resp.text[:300])
    except Exception as exc:  # noqa: BLE001
        dump_exc("fail", exc)


def main() -> int:
    try_httpx("https://api.deepseek.com/v1/models")
    try_base("https://api.deepseek.com")
    try_base("https://api.deepseek.com/v1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
