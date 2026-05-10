"""OpenAI client for circuit generation."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ConfigDict, Field, TypeAdapter

from . import promptlog
from .ast import Circuit, _Node
from .prompts import SYSTEM_PROMPT, build_user_prompt

load_dotenv()


def _prompt_digest(system: str, user: str, model: str) -> str:
    """16-char SHA-256 digest used as LLM cache key."""
    payload = f"{model}||{system}||{user}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class ProgramResponse(_Node):
    """Top-level response wrapper. The `Circuit` AST lives inside."""

    reasoning: str = Field(
        description="One short sentence at most; can be empty.",
    )
    circuit: Circuit


def default_model() -> str:
    return os.environ.get("LEANDREAM_MODEL", "gpt-5")


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        _client = OpenAI()
    return _client


_CIRCUIT_ADAPTER: TypeAdapter[Circuit] = TypeAdapter(Circuit)


def generate_circuit(
    spec: dict[str, Any],
    installed_macros: dict[str, dict[str, Any]] | None = None,
    *,
    model: str | None = None,
    iteration: int = 0,
    memory_pack: str = "",
    use_cache: bool = True,
) -> tuple[Circuit, str]:
    """Ask the LLM for a program. Returns (circuit, reasoning).

    Checks a persistent disk cache keyed by (model, system_prompt, user_prompt)
    before making an API call.  Set ``use_cache=False`` to always call the API
    (e.g. during repair passes where context changes each time).

    Every call (success or failure) is appended to ``prompts/<spec>/<ts>.json``
    so the full conversation history is auditable from the web viewer.
    """
    from .cache import llm_response_cache

    client = _get_client()
    macros = installed_macros or {}
    user_prompt = build_user_prompt(spec, macros, memory_pack=memory_pack)
    chosen_model = model or default_model()

    # --- LLM response cache ---------------------------------------------------
    cache_key = _prompt_digest(SYSTEM_PROMPT, user_prompt, chosen_model)
    if use_cache:
        llm_cache = llm_response_cache()
        cached = llm_cache.get(cache_key)
        if cached is not None:
            circuit = _CIRCUIT_ADAPTER.validate_python(cached["circuit"])
            return circuit, cached.get("reasoning", "")

    # --- Live API call --------------------------------------------------------
    t0 = time.monotonic()
    try:
        resp = client.responses.parse(
            model=chosen_model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            text_format=ProgramResponse,
        )
        elapsed = time.monotonic() - t0
        program = resp.output_parsed
        if program is None:
            raise RuntimeError(f"LLM returned no parsed output: {resp}")
        circuit_dict = _CIRCUIT_ADAPTER.dump_python(program.circuit, mode="json")
        promptlog.record(
            spec=spec["name"],
            iteration=iteration,
            model=chosen_model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            macros_in_prompt=sorted(macros.keys()),
            elapsed_seconds=elapsed,
            ok=True,
            response_circuit=circuit_dict,
            reasoning=program.reasoning,
        )
        if use_cache:
            llm_response_cache().put(cache_key, {
                "circuit": circuit_dict,
                "reasoning": program.reasoning,
            })
        return program.circuit, program.reasoning
    except Exception as e:
        elapsed = time.monotonic() - t0
        promptlog.record(
            spec=spec["name"],
            iteration=iteration,
            model=chosen_model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            macros_in_prompt=sorted(macros.keys()),
            elapsed_seconds=elapsed,
            ok=False,
            error=f"{type(e).__name__}: {e}",
        )
        raise
