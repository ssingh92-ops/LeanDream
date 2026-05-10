"""Beta-posterior contextual bandit with Thompson sampling for LeanDream.

Arms are identified by string keys. Two arm namespaces are used:
  "spec:<name>"    — per-spec success rate; tracks how often each spec verifies
  "macro:<name>"   — per-macro usefulness; tracks how often macros lead to verified proofs

Each arm maintains a Beta(alpha, beta) posterior (uniform prior: alpha=beta=1).
Thompson sampling draws theta_i ~ Beta(alpha_i, beta_i) for each arm and
returns them ranked highest-first. The highest-ranked macros appear first in
the LLM prompt, giving the bandit direct influence over generation quality.

Reward convention (see compute_reward()):
  reward > 0  → alpha += reward   (success weight)
  reward <= 0 → beta  += 1 + |reward|  (failure weight + optional penalty)

Info-structure reward modifiers (addendum — heuristic, not Lean-certified):
  verified + information_preserving → +0.15 bonus
  verified + cleans_garbage         → +0.15 bonus
  failed  + prefer_info_preserving
           + information_losing     → -0.20 penalty (extra failure weight)

Bandit state is persisted to data/bandit/bandit.json so learning accumulates
across runs. Missing arms default to Beta(1,1) on first access.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BANDIT_PATH = REPO_ROOT / "data" / "bandit" / "bandit.json"

_IP_BONUS = 0.15   # verified + information_preserving
_CG_BONUS = 0.15   # verified + cleans_garbage
_IL_PENALTY = 0.20 # failed  + prefer_info_preserving + information_losing


@dataclass
class BetaArm:
    alpha: float = 1.0  # prior successes  (uniform prior starts at 1)
    beta: float = 1.0   # prior failures
    # For macro arms: the truth-table key of the circuit this posterior was
    # learned against. When a macro slot (e.g. "macro_8") gets repurposed in a
    # later run for a different circuit, the installer detects the tt_key
    # mismatch and resets the arm to avoid contaminating the new circuit's
    # posterior with stale rewards. None means "untagged" — typically an arm
    # that pre-dates this field; treated as stale on next bind.
    tt_key: str | None = None

    def sample(self) -> float:
        """Draw one Thompson sample."""
        return random.betavariate(self.alpha, self.beta)

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def n(self) -> float:
        """Pseudo-observation count (alpha + beta - 2, since prior is at 1)."""
        return self.alpha + self.beta - 2.0


class ContextualBandit:
    """Dict-of-BetaArms with Thompson sampling, persistence, and reward helpers."""

    def __init__(self) -> None:
        self._arms: dict[str, BetaArm] = {}

    def _arm(self, key: str) -> BetaArm:
        if key not in self._arms:
            self._arms[key] = BetaArm()
        return self._arms[key]

    def sample(self, key: str) -> float:
        return self._arm(key).sample()

    def mean(self, key: str) -> float:
        return self._arm(key).mean

    def rank(self, keys: list[str]) -> list[str]:
        """Return keys sorted by Thompson sample, highest first.

        Calling once per iteration gives stable within-iteration ordering;
        the stochastic sampling provides exploration across iterations.
        """
        sampled = {k: self._arm(k).sample() for k in keys}
        return sorted(keys, key=lambda k: sampled[k], reverse=True)

    def update(self, key: str, reward: float) -> None:
        """Update the arm posterior.

        reward > 0  → add reward to alpha (success signal)
        reward <= 0 → add 1 + |reward| to beta (failure + penalty weight)
        """
        arm = self._arm(key)
        if reward > 0:
            arm.alpha += reward
        else:
            arm.beta += 1.0 + abs(reward)

    def bind_macro_arm(
        self, macro_name: str, tt_key: str, *, verbose: bool = False
    ) -> str:
        """Bind a macro slot to a specific circuit (identified by `tt_key`).

        Resolves three situations at install time:
          - Existing arm matches `tt_key`            → keep posterior.
          - Existing arm tagged with a *different*   → stale (different circuit
            tt_key, or untagged (legacy)               under same name); reset.
          - Another arm under a different name has   → carry that posterior
            the same `tt_key`                          over (cross-run learning
                                                       for the same function).
          - Otherwise                                → fresh prior.

        Returns one of: "kept", "reset_stale", "reset_legacy", "carry_over",
        "fresh".
        """
        key = f"macro:{macro_name}"
        existing = self._arms.get(key)
        if existing is not None:
            if existing.tt_key == tt_key:
                return "kept"
            outcome = "reset_legacy" if existing.tt_key is None else "reset_stale"
        else:
            outcome = "fresh"

        # Look for an orphan arm with the same tt_key under a different name —
        # the same Boolean function may have been mined under a different slot
        # in a prior run.
        carry_over: BetaArm | None = None
        for k, arm in self._arms.items():
            if k == key:
                continue
            if k.startswith("macro:") and arm.tt_key == tt_key:
                carry_over = arm
                break

        if carry_over is not None:
            self._arms[key] = BetaArm(
                alpha=carry_over.alpha,
                beta=carry_over.beta,
                tt_key=tt_key,
            )
            if verbose:
                print(
                    f"  [bandit] {macro_name}: carried over posterior for tt={tt_key} "
                    f"(α={carry_over.alpha:.1f}, β={carry_over.beta:.1f})"
                )
            return "carry_over"

        self._arms[key] = BetaArm(alpha=1.0, beta=1.0, tt_key=tt_key)
        if verbose and outcome != "fresh":
            print(
                f"  [bandit] {macro_name}: reset stale arm "
                f"({'tagged' if outcome == 'reset_stale' else 'untagged'} prior, "
                f"new tt={tt_key})"
            )
        return outcome

    def summary(self) -> dict[str, dict]:
        """Return a JSON-friendly summary of all arm posteriors."""
        return {
            k: {"alpha": round(a.alpha, 4), "beta": round(a.beta, 4),
                "mean": round(a.mean, 4), "n": round(a.n, 1)}
            for k, a in sorted(self._arms.items())
        }

    def save(self, path: Path | None = None) -> None:
        target = path or BANDIT_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, dict] = {}
        for k, a in self._arms.items():
            entry: dict = {"alpha": a.alpha, "beta": a.beta}
            if a.tt_key is not None:
                entry["tt_key"] = a.tt_key
            data[k] = entry
        target.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path | None = None) -> "ContextualBandit":
        bandit = cls()
        target = path or BANDIT_PATH
        if target.exists():
            try:
                for k, v in json.loads(target.read_text()).items():
                    bandit._arms[k] = BetaArm(
                        alpha=float(v["alpha"]),
                        beta=float(v["beta"]),
                        tt_key=v.get("tt_key"),
                    )
            except Exception:
                pass
        return bandit


def compute_reward(
    status: str,
    info_structure: dict | None = None,
    *,
    prefer_info_preserving: bool = False,
) -> float:
    """Compute a bandit reward value from an attempt outcome.

    Returns a float: positive = success signal, <= 0 = failure signal.
    The caller passes this directly to ContextualBandit.update().

    Info-structure bonuses apply only to verified attempts; the penalty
    applies only to failures when the caller signals info-preservation
    preference and the circuit is tagged information_losing.
    These are heuristic modifiers — not Lean-certified properties.
    """
    from ..attempts import STATUS_VERIFIED
    info = info_structure or {}
    if status == STATUS_VERIFIED:
        reward = 1.0
        if info.get("information_preserving"):
            reward += _IP_BONUS
        if info.get("cleans_garbage"):
            reward += _CG_BONUS
        return reward
    else:
        extra = 0.0
        if prefer_info_preserving and info.get("information_losing"):
            extra = _IL_PENALTY
        return -extra  # 0.0 or negative → beta gets 1.0 + extra


def _macros_used(circuit_dict: dict | None) -> set[str]:
    """Walk a serialised Circuit dict and return all referenced macro names."""
    if not circuit_dict:
        return set()
    names: set[str] = set()
    if circuit_dict.get("kind") == "mac":
        names.add(circuit_dict["name"])
    for key in ("arg", "left", "right"):
        if key in circuit_dict:
            names |= _macros_used(circuit_dict[key])
    for arg in circuit_dict.get("args", []):
        names |= _macros_used(arg)
    return names
