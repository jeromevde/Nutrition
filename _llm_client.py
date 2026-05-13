"""_llm_client.py
================
Shared LLM client factory for the Nutrition pipeline.

Priority:
  1. OPENROUTER_API_KEY in environment  →  OpenRouter (original behaviour)
  2. Copilot Proxy reachable at 127.0.0.1:3000  →  local VS Code bridge
  3. Neither available  →  print setup instructions and sys.exit(1)

Usage
-----
    from _llm_client import make_client

    client, model = make_client("google/gemini-2.0-flash-001")
    # `model` is either the openrouter model (case 1) or COPILOT_PROXY_MODEL (case 2)
"""

from __future__ import annotations

import os
import sys

import httpx
import openai

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
COPILOT_PROXY_URL   = "http://127.0.0.1:3000/v1"

# Model used when falling back to the Copilot Proxy.
# Change to any model your Copilot subscription exposes (see GET /v1/models).
COPILOT_PROXY_MODEL = "gpt-4o-mini"


def _proxy_reachable() -> bool:
    """Return True if the Copilot Proxy is already running."""
    try:
        r = httpx.get(f"{COPILOT_PROXY_URL}/models", timeout=3.0)
        return r.status_code < 500
    except Exception:
        return False


def _print_proxy_instructions() -> None:
    print(
        "\n" + "=" * 60 + "\n"
        "OPENROUTER_API_KEY is not set and the Copilot Proxy is not running.\n\n"
        "Option A – VS Code extension (recommended when inside VS Code):\n"
        "  1. Install the .vsix from:\n"
        "       https://github.com/hyorman/copilot-proxy/releases\n"
        "  2. Open the Command Palette (Shift+Cmd+P) and run:\n"
        "       Copilot Proxy: Start Server\n\n"
        "Option B – headless / terminal (no VS Code needed):\n"
        "  npx @hyorman/copilot-proxy-cli\n\n"
        "Then re-run this script.\n"
        + "=" * 60
    )


def make_client(openrouter_model: str) -> tuple[openai.OpenAI, str]:
    """Return (configured OpenAI-compatible client, model name to use).

    Parameters
    ----------
    openrouter_model:
        The model string to use when routing through OpenRouter
        (e.g. ``"google/gemini-2.0-flash-001"`` or
        ``"qwen/qwen-2-vl-7b-instruct"``).  Ignored when the Copilot Proxy
        is used instead.

    Returns
    -------
    (client, model_str)
        ``model_str`` is either *openrouter_model* (OpenRouter path) or
        ``COPILOT_PROXY_MODEL`` (proxy path).
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        client = openai.OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            timeout=120,
            max_retries=2,
        )
        return client, openrouter_model

    if _proxy_reachable():
        print(
            f"[llm] OPENROUTER_API_KEY not set – using Copilot Proxy at "
            f"{COPILOT_PROXY_URL} (model: {COPILOT_PROXY_MODEL})"
        )
        client = openai.OpenAI(
            base_url=COPILOT_PROXY_URL,
            api_key="copilot",  # proxy ignores the key value; must be non-empty
            timeout=120,
            max_retries=2,
        )
        return client, COPILOT_PROXY_MODEL

    _print_proxy_instructions()
    sys.exit(1)
