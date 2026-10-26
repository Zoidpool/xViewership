"""Foundry Local, driven through its CLI.

The `foundry-local-sdk` 0.5 that agent-framework-foundry-local pins still calls
`foundry service ...`, which Foundry Local 0.12 renamed to `foundry server`.
So we start the daemon and load the model with the CLI, then point Agent
Framework's OpenAI-compatible chat client at the local endpoint.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess


def _foundry() -> str:
    exe = shutil.which("foundry")
    if exe:
        return exe
    guess = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\foundry.exe")
    if os.path.exists(guess):
        return guess
    raise RuntimeError("Foundry Local is not installed: winget install Microsoft.FoundryLocal")


def _json(*args: str, timeout: int = 600) -> dict:
    out = subprocess.run([_foundry(), *args, "-o", "json"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=timeout).stdout
    # progress lines may precede the JSON object
    start = out.rfind("\n{")
    return json.loads(out[start + 1:] if start >= 0 else out[out.find("{"):])


def start_and_load(alias: str) -> tuple[str, str]:
    """Start the daemon if needed, load `alias`, return (base_url, model_id)."""
    status = _json("server", "status", timeout=60)
    if not status.get("running"):
        subprocess.run([_foundry(), "server", "start"], capture_output=True, timeout=300)
        status = _json("server", "status", timeout=60)
    url = status["webUrls"][0].rstrip("/")
    loaded = _json("model", "load", alias)
    if not loaded.get("success"):
        raise RuntimeError(f"foundry model load {alias}: {loaded.get('message')}")
    m = re.search(r"variant '([^']+)'", loaded.get("message", ""))
    return url + "/v1", m.group(1) if m else alias


def build_local_client(alias: str):
    from agent_framework.openai import OpenAIChatCompletionClient
    base_url, model_id = start_and_load(alias)
    client = OpenAIChatCompletionClient(model=model_id, base_url=base_url,
                                        api_key="foundry-local")
    client.backend = f"foundry-local:{alias}"
    return client
