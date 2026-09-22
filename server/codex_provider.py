"""Fail-closed boundary for the optional ChatGPT / Codex integration.

App-server supports account/login/start but is an agent execution protocol. We
have no verified version/capability combination that disables every execution
tool. Starting a generic agent is therefore not an acceptable text-only provider.
This module never launches Codex, reads a user's auth cache, or modifies it.

Reviewed interfaces: https://learn.chatgpt.com/docs/app-server and
https://learn.chatgpt.com/docs/auth (2026-09-21).
"""
from __future__ import annotations

import shutil


MESSAGE = (
    "ChatGPT login is not enabled in this Helios version: the supported Codex "
    "app-server protocol has not been verified to disable all execution tools "
    "for text-only interviewing. Use Ollama or LM Studio for offline practice, "
    "or disable Offline mode and configure an OpenAI API key. ChatGPT login "
    "does not provide general OpenAI API or audio access."
)


async def status(settings: dict | None = None) -> dict:
    return {
        "available": False,
        "connected": False,
        "authenticated": False,
        "login_enabled": False,
        "safe_text_only": False,
        "installed": shutil.which("codex") is not None,
        "reason": "text_only_compatibility_unverified",
        "message": MESSAGE,
        "auth_url": None,
        "alternatives": ["ollama", "lmstudio", "openai_compatible", "openai"],
        "documentation_url": "https://learn.chatgpt.com/docs/app-server",
    }


async def login(settings: dict | None = None) -> dict:
    return {**await status(settings), "ok": False}


async def logout(settings: dict | None = None) -> dict:
    result = await status(settings)
    result.update({
        "ok": True,
        "message": "Helios has no ChatGPT credentials to remove. Your existing Codex login is unchanged. " + MESSAGE,
    })
    return result
