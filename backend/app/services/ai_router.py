"""Provider-agnostic AI gateway.

Why a router and not a single SDK: the tasks in this product have genuinely
different cost/latency profiles. Classifying 4,000 inbound messages a day is a
cheap-and-fast job; drafting a reply in the user's voice is a quality job. The
router picks by *task*, falls back down a chain when a provider errors, and
records spend so the analytics page can show cost per resolved thread.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import StrEnum

import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger()


class Task(StrEnum):
    CLASSIFY = "classify"        # high volume, low cost
    SUMMARISE = "summarise"
    DRAFT_REPLY = "draft_reply"  # quality first
    CONTENT = "content"
    ASSISTANT = "assistant"      # tool use + reasoning
    EMBED = "embed"


@dataclass(frozen=True)
class Model:
    provider: str
    name: str
    input_per_mtok: float
    output_per_mtok: float


CATALOG: dict[str, Model] = {
    "claude-opus": Model("anthropic", "claude-opus-4-5", 5.0, 25.0),
    "claude-sonnet": Model("anthropic", "claude-sonnet-4-6", 3.0, 15.0),
    "claude-haiku": Model("anthropic", "claude-haiku-4-5", 0.8, 4.0),
    "gpt": Model("openai", "gpt-4.1", 2.0, 8.0),
    "gemini-flash": Model("google", "gemini-2.5-flash", 0.3, 1.2),
    "groq-llama": Model("groq", "llama-3.3-70b-versatile", 0.59, 0.79),
    "ollama-local": Model("ollama", "llama3.1:8b", 0.0, 0.0),
}

# Ordered fallback chains. First available provider wins.
ROUTES: dict[Task, tuple[str, ...]] = {
    Task.CLASSIFY: ("groq-llama", "gemini-flash", "claude-haiku", "ollama-local"),
    Task.SUMMARISE: ("claude-haiku", "gemini-flash", "groq-llama", "ollama-local"),
    Task.DRAFT_REPLY: ("claude-sonnet", "gpt", "claude-haiku", "ollama-local"),
    Task.CONTENT: ("claude-sonnet", "gpt", "gemini-flash"),
    Task.ASSISTANT: ("claude-sonnet", "gpt", "gemini-flash"),
    Task.EMBED: ("openai-embed",),
}


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float = field(default=0.0)

    def as_json(self) -> dict:
        """Parse a JSON-only response, tolerating stray fences."""
        cleaned = self.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        return json.loads(cleaned)


class ProviderUnavailable(RuntimeError):
    pass


class AIRouter:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=60.0)

    def _available(self, key: str) -> bool:
        provider = CATALOG[key].provider
        return {
            "anthropic": bool(settings.anthropic_api_key),
            "openai": bool(settings.openai_api_key),
            "google": bool(settings.google_api_key),
            "groq": bool(settings.groq_api_key),
            "ollama": True,
        }.get(provider, False)

    async def complete(
        self,
        task: Task,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> Completion:
        errors: list[str] = []
        for key in ROUTES[task]:
            if not self._available(key):
                continue
            model = CATALOG[key]
            started = time.perf_counter()
            try:
                text, tin, tout = await self._call(model, system, prompt, max_tokens, temperature)
            except (httpx.HTTPError, KeyError) as exc:  # noqa: PERF203
                errors.append(f"{key}: {exc}")
                log.warning("ai.fallback", model=key, error=str(exc))
                continue
            latency = int((time.perf_counter() - started) * 1000)
            return Completion(
                text=text,
                model=model.name,
                input_tokens=tin,
                output_tokens=tout,
                latency_ms=latency,
                cost_usd=(tin * model.input_per_mtok + tout * model.output_per_mtok) / 1_000_000,
            )
        raise ProviderUnavailable(
            "No AI provider answered. Add a key in Settings → AI, or start Ollama for local models. "
            + "; ".join(errors)
        )

    async def _call(
        self, model: Model, system: str, prompt: str, max_tokens: int, temperature: float
    ) -> tuple[str, int, int]:
        if model.provider == "anthropic":
            r = await self._client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key or "",
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": model.name,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            data = r.json()
            text = "".join(b["text"] for b in data["content"] if b["type"] == "text")
            u = data["usage"]
            return text, u["input_tokens"], u["output_tokens"]

        if model.provider in {"openai", "groq"}:
            base = (
                "https://api.openai.com/v1"
                if model.provider == "openai"
                else "https://api.groq.com/openai/v1"
            )
            key = settings.openai_api_key if model.provider == "openai" else settings.groq_api_key
            r = await self._client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model.name,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            r.raise_for_status()
            data = r.json()
            u = data["usage"]
            return (
                data["choices"][0]["message"]["content"],
                u["prompt_tokens"],
                u["completion_tokens"],
            )

        if model.provider == "ollama":
            r = await self._client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": model.name,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            r.raise_for_status()
            data = r.json()
            return data["message"]["content"], 0, 0

        raise ProviderUnavailable(f"Unsupported provider {model.provider}")

    async def fan_out(self, task: Task, jobs: list[tuple[str, str]], limit: int = 8) -> list[Completion]:
        """Run many small jobs (e.g. nightly reclassification) with bounded concurrency."""
        sem = asyncio.Semaphore(limit)

        async def one(system: str, prompt: str) -> Completion:
            async with sem:
                return await self.complete(task, system=system, prompt=prompt)

        return await asyncio.gather(*(one(s, p) for s, p in jobs))
