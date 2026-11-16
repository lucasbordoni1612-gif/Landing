"""Claude API wrapper.

Two call shapes are used by the agent:

* ``json()``     - one request, response constrained by ``output_config.format``
                   (extraction, drafting, e-mail classification). No server tools.
* ``research()`` - web search / web fetch server tools plus one "report" tool the
                   model calls with its findings. Tool input is validated in code.

Server-side refusal fallback is on by default (``fallbacks = "default"``).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import anthropic

from .config import LLMConfig
from .schemas import SchemaError, validate

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def json(self, *, purpose: str, system: str, prompt: str, schema: dict, effort: str) -> dict: ...

    def research(self, *, purpose: str, system: str, prompt: str, report_tool: dict,
                 server_tools: list[dict], effort: str) -> dict | None: ...


def web_search_tool(max_uses: int, allowed_domains: list[str] | None = None) -> dict:
    tool: dict[str, Any] = {"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}
    if allowed_domains:
        tool["allowed_domains"] = allowed_domains
    return tool


def web_fetch_tool(max_uses: int, allowed_domains: list[str] | None = None) -> dict:
    tool: dict[str, Any] = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_uses}
    if allowed_domains:
        tool["allowed_domains"] = allowed_domains
    return tool


class ClaudeLLM:
    def __init__(self, cfg: LLMConfig, client: anthropic.Anthropic | None = None):
        self.cfg = cfg
        self.client = client or anthropic.Anthropic(max_retries=4)

    def _create(self, *, purpose: str, effort: str, **kwargs: Any):
        params: dict[str, Any] = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "thinking": {"type": "adaptive"},
            **kwargs,
        }
        params["output_config"] = {"effort": effort, **params.get("output_config", {})}
        if self.cfg.fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = self.cfg.fallbacks
        try:
            resp = self.client.beta.messages.create(**params)
        except anthropic.BadRequestError as exc:
            raise LLMError(f"[{purpose}] requisição inválida: {exc.message}") from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMError(f"[{purpose}] credencial da API do Claude inválida ou sem permissão") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(f"[{purpose}] limite de requisições atingido; tente mais tarde") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"[{purpose}] erro da API ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"[{purpose}] sem conexão com a API do Claude") from exc
        log.debug("%s: stop=%s usage=%s", purpose, resp.stop_reason, getattr(resp, "usage", None))
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            raise LLMError(f"[{purpose}] o modelo recusou a solicitação ({getattr(details, 'category', None)})")
        return resp

    def json(self, *, purpose: str, system: str, prompt: str, schema: dict, effort: str) -> dict:
        resp = self._create(
            purpose=purpose,
            effort=effort,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason == "max_tokens":
            raise LLMError(f"[{purpose}] resposta cortada por max_tokens")
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            data = json.loads(text)
            validate(data, schema)
        except (json.JSONDecodeError, SchemaError) as exc:
            raise LLMError(f"[{purpose}] JSON inválido: {exc}") from exc
        return data

    def research(self, *, purpose: str, system: str, prompt: str, report_tool: dict,
                 server_tools: list[dict], effort: str, max_rounds: int = 6) -> dict | None:
        tools = [*server_tools, report_tool]
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        nudged = False
        for _ in range(max_rounds):
            resp = self._create(purpose=purpose, effort=effort, system=system, messages=messages, tools=tools)
            for block in resp.content:
                if block.type == "tool_use" and block.name == report_tool["name"]:
                    try:
                        validate(block.input, report_tool["input_schema"])
                    except SchemaError as exc:
                        raise LLMError(f"[{purpose}] ferramenta {report_tool['name']} com dados inválidos: {exc}")
                    return block.input
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "pause_turn":
                continue  # server-side loop paused; resend so it resumes
            if resp.stop_reason == "max_tokens":
                raise LLMError(f"[{purpose}] resposta cortada por max_tokens")
            if nudged:
                break
            nudged = True
            messages.append({
                "role": "user",
                "content": f"Now call the {report_tool['name']} tool with your findings.",
            })
        return None
