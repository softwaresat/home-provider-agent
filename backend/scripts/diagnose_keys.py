"""Check DeepSeek and Places without printing secrets."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from openai import OpenAI

from app import config


def redact(value: object) -> str:
    text = str(value)
    text = re.sub(r"sk-[A-Za-z0-9_\-]+", "sk-REDACTED", text)
    text = re.sub(r"AIza[A-Za-z0-9_\-]+", "AIza-REDACTED", text)
    return text[:800]


def main() -> int:
    print("deepseek_key_len", len(config.DEEPSEEK_API_KEY))
    print("places_key_len", len(config.GOOGLE_PLACES_API_KEY))
    print("base_url", config.DEEPSEEK_BASE_URL)
    print("model", config.DEEPSEEK_MODEL)

    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
        timeout=30.0,
    )
    try:
        response = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": 'Reply with JSON {"ok": true} only'}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        print("llm_ok", True)
        print("llm_content", (response.choices[0].message.content or "")[:200])
    except Exception as exc:  # noqa: BLE001
        print("llm_ok", False)
        print("llm_error_type", type(exc).__name__)
        print("llm_error", redact(exc))
        try:
            response = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": "Say hi"}],
                temperature=0,
            )
            print("llm_plain_ok", True)
            print("llm_plain", (response.choices[0].message.content or "")[:200])
        except Exception as exc2:  # noqa: BLE001
            print("llm_plain_ok", False)
            print("llm_plain_error", redact(exc2))

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress",
    }
    try:
        resp = httpx.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers=headers,
            json={
                "textQuery": "plumber in Austin, TX",
                "pageSize": 3,
                "includePureServiceAreaBusinesses": True,
            },
            timeout=20.0,
        )
        print("places_status", resp.status_code)
        data = resp.json()
        if resp.status_code != 200:
            print("places_error", redact(json.dumps(data)))
        else:
            names = []
            for place in data.get("places") or []:
                display = place.get("displayName") or {}
                names.append(display.get("text") if isinstance(display, dict) else str(display))
            print("places_ok", True)
            print("places_count", len(names))
            print("places_names", names)
    except Exception as exc:  # noqa: BLE001
        print("places_exception", redact(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
