"""One-shot DeepSeek JSON smoke check. Safe to run without a key (reports fallback)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, llm
from app.models import ChatMessage


def main() -> int:
    print(f"model={config.DEEPSEEK_MODEL}")
    print(f"deepseek_configured={config.deepseek_configured()}")
    history = [
        ChatMessage(
            role="user",
            content="Water started coming into my basement last night after the storm.",
        )
    ]
    analysis, used_fallback = llm.analyze(history)
    print(f"used_fallback={used_fallback}")
    print(analysis.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
