"""Multi-provider LLM wrapper for the city-sim agents.

Free-tier-friendly providers, picked per agent via `agent.provider`:
  - "gemini"     Google Gemini API (free tier, no card) -- needs GEMINI_API_KEY
  - "groq"       Groq API (free tier, no card, open models) -- needs GROQ_API_KEY
  - "openrouter" OpenRouter, using a ":free" tagged model (e.g. DeepSeek) --
                 needs OPENROUTER_API_KEY
  - "ollama"     Fully local, no key, needs the Ollama app running on this
                 machine with a model already pulled (`ollama pull llama3.1`)
  - "github"     GitHub Models (free, rate-limited) -- needs GITHUB_TOKEN
                 (a classic PAT with "models: read" permission)
  - "claude"     NOT called from here -- this agent's weekly turn is supplied
                 by a human (via claude_turn.py) instead of an API call.

Every provider is asked to answer with a single JSON object; parsing is
best-effort so one malformed reply doesn't crash a multi-week run.
"""
from __future__ import annotations

import json
import os

import requests

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-chat:free")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
GITHUB_MODEL = os.environ.get("GITHUB_MODEL", "openai/gpt-4o-mini")
GITHUB_MODELS_ENDPOINT = os.environ.get(
    "GITHUB_MODELS_ENDPOINT", "https://models.github.ai/inference/chat/completions"
)

_gemini_client = None
_groq_client = None


def _extract_json(text: str) -> dict:
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {"action": "нет действия", "reasoning": text[:300], "cash_delta": 0,
                 "revenue_change": 0, "cost_change": 0, "risk_flag": False, "notes": "parse_error"}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"action": "нет действия", "reasoning": text[:300], "cash_delta": 0,
                 "revenue_change": 0, "cost_change": 0, "risk_flag": False, "notes": "parse_error"}


def _ask_gemini(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    global _gemini_client
    from google import genai
    from google.genai import types

    if _gemini_client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        _gemini_client = genai.Client(api_key=api_key)

    response = _gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


def _ask_groq(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    global _groq_client
    from groq import Groq

    if _groq_client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set.")
        _groq_client = Groq(api_key=api_key)

    response = _groq_client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""


def _ask_openrouter(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": OPENROUTER_MODEL,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"] or ""


def _ask_ollama(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "stream": False,
            "options": {"num_predict": max_tokens},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"] or ""


def _ask_github(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set.")
    resp = requests.post(
        GITHUB_MODELS_ENDPOINT,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": GITHUB_MODEL,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"] or ""


_PROVIDERS = {
    "gemini": _ask_gemini,
    "groq": _ask_groq,
    "openrouter": _ask_openrouter,
    "ollama": _ask_ollama,
    "github": _ask_github,
}


def ask_json(provider: str, system_prompt: str, user_prompt: str, max_tokens: int = 1200) -> dict:
    fn = _PROVIDERS.get(provider)
    if fn is None:
        raise ValueError(f"Unknown provider: {provider}")
    try:
        text = fn(system_prompt, user_prompt, max_tokens)
    except Exception as exc:  # noqa: BLE001 -- keep the sim running, log the failure
        return {"action": "нет действия", "reasoning": f"[{provider} error] {exc}", "cash_delta": 0,
                 "revenue_change": 0, "cost_change": 0, "risk_flag": False, "notes": "provider_error"}
    return _extract_json(text)
