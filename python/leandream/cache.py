"""Persistent disk-backed key-value caches for expensive operations.

All caches live under data/cache/.  Each cache is a single JSON file.
Thread-safety: writes are lock-protected; reads are lock-free.
Max-entries cap evicts the oldest quarter when exceeded.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from .verify import REPO_ROOT

CACHE_DIR: Path = REPO_ROOT / "data" / "cache"


class DiskCache:
    """Simple persistent LRU-ish cache backed by a JSON file.

    Usage::

        cache = DiskCache("lean_verify", max_entries=5000)
        key = DiskCache.digest(spec, circuit_hash, registry_hash)
        hit = cache.get(key)
        if hit is None:
            value = expensive_call()
            cache.put(key, value)
    """

    def __init__(self, name: str, max_entries: int = 5000) -> None:
        self._path: Path = CACHE_DIR / f"{name}.json"
        self._max: int = max_entries
        self._lock: threading.Lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._hits: int = 0
        self._misses: int = 0
        self._load()

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    def _load(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def _save(self) -> None:
        if len(self._data) > self._max:
            trim_to = self._max * 3 // 4
            excess = len(self._data) - trim_to
            for k in list(self._data.keys())[:excess]:
                del self._data[k]
        self._path.write_text(json.dumps(self._data), encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        val = self._data.get(key)
        if val is None:
            self._misses += 1
            return None
        self._hits += 1
        return val

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    def stats(self) -> dict[str, int | float]:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._data),
            "hit_rate": round(self._hits / total, 4) if total else 0.0,
        }

    def reset_stats(self) -> None:
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def digest(*parts: str) -> str:
        """First 16 hex chars of SHA-256 over pipe-joined parts."""
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Module-level singletons — created lazily so import is always safe
# ---------------------------------------------------------------------------

_lean_cache: DiskCache | None = None
_llm_cache: DiskCache | None = None
_property_cache: DiskCache | None = None


def lean_verify_cache() -> DiskCache:
    global _lean_cache
    if _lean_cache is None:
        _lean_cache = DiskCache("lean_verify", max_entries=10_000)
    return _lean_cache


def llm_response_cache() -> DiskCache:
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = DiskCache("llm_response", max_entries=2_000)
    return _llm_cache


def property_prove_cache() -> DiskCache:
    global _property_cache
    if _property_cache is None:
        _property_cache = DiskCache("property_prove", max_entries=5_000)
    return _property_cache
