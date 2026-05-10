# LeanDream

A neuro-symbolic system that teaches itself a verified Boolean-circuit macro
library.  An LLM proposes circuits; Lean certifies them; a proof forest,
contextual bandit, and RAG memory make each generation round smarter than the
last.

---

## System overview

```
         ┌───────────────────────────────────────────────────┐
         │                   PYTHON LAYER                    │
         │                                                   │
         │  Prompt ──► LLM ──► Repair? ──► Expand ──► Lean  │
         │    ▲                                      │       │
         │    │  RAG memory         Bandit           │       │
         │    │  card store  ◄────  update  ◄────────┘       │
         │    │                                              │
         │  Mine ◄── Proof forest ◄── Install ◄── Prove     │
         └───────────────────────────────────────────────────┘
                          ▲        │
                          │  LEAN  │  (trusted proof engine)
                          └────────┘
```

The boundary is strict: **Lean is the only trusted component**.  A circuit is
"verified" only when `lake build` succeeds.  Python reads exit codes, never
interprets proof content.  The LLM is a proposer that emits JSON syntax — it
never touches proofs.

---

## Lean layer

```
lean/LeanDream/
  DSL.lean          Circuit inductive type, eval, envOf, equivOn
  ProofMode.lean    `circuit_decide` tactic (decide → native_decide fallback)
  ProofRouter.lean  decideMaxArity = 4; ProofStrategy type
  SimpSets.lean     @[simp] lemmas for Circuit.eval + Bool algebra
  Specs.lean        Reference circuit library
  Macros.lean       Installed macros          ← regenerated each iteration
  Candidate.lean    Verification target       ← regenerated each attempt
  Verify.lean       `candidate_correct` theorem via native_decide
  Properties.lean   Algebraic property theorems  ← regenerated each iteration
```

`Circuit` is an inductive type with constructors `var`, `const`, `not`, `and`,
`or`, `xor`.  Macros extend this vocabulary at the DSL level — they are
ordinary Lean definitions (`def macro_N ...`) that live in `Macros.lean` and
are inlined by the Python expander before verification.

Verification discharges `Circuit.equivOn arity candidate targetSpec = true` via
`native_decide`.  Algebraic properties (commutativity, idempotence,
associativity, identity/annihilator elements, involution) are generated as
`∀ a b : Bool, ...` theorems proved with `circuit_decide`, a tactic macro that
tries the kernel `decide` first and falls back to `native_decide` for heavier
goals.  `SimpSets.lean` provides `@[simp]` eval-unfolding lemmas for manual or
semi-automated proofs.

---

## Python layer

### Orchestrator
`orchestrator.py` drives the generate–verify–mine–install loop.  Each
iteration: for every spec, it ranks macros by Thompson sample, retrieves RAG
context, calls the LLM (or mock), expands macro references, invokes
`lake build`, and logs the attempt.  After all specs, it mines the proof
forest, installs surviving candidates, proves their properties, and exports
theorem cards to the RAG store.

### Circuit representation
`ast.py` mirrors the Lean `Circuit` type as Pydantic models.  `expand_macros`
inlines Mac nodes recursively (cycle guard, depth guard, arity check).
`translate.py` renders Python ASTs to Lean syntax for `Candidate.lean` and
`Macros.lean`.

### Mining and hierarchy
`miner.py` extracts frequent subtrees from the proof forest.  Canonical form
renames free vars to occurrence order so `x5 AND x7` and `x0 AND x1` are
structurally identical.  `mine_macro_compositions` runs a second pass on raw
LLM circuits (before macro expansion) to find macro-of-macro composition
patterns.

`hierarchy.py` computes a DAG of macro dependencies and assigns
`macro_level` to each installed macro (0 = references only primitives;
1 = references level-0 macros; etc.).  The installer guarantees the DAG is
acyclic — each new macro may only reference already-installed macros.

### Installation pipeline
`installer.py` checks structural novelty (dedup by canonical hash key), then
truth-table novelty (rejects macros semantically equivalent or NOT-equivalent
to any existing macro), then appends to `Macros.lean` and calls `lake build`.
On success it records arity, truth table, macro level, body repr, and a
heuristic information-structure tag set.

### Algebraic property proving
`properties.py` generates `theorem macro_N_comm : ... := by circuit_decide`
for each candidate property.  It pre-filters with a Python truth-table check
before spending a `lake build` on it.  A fast path attempts all macros in one
build; a per-macro isolation fallback avoids one bad theorem blocking all
others.

### One-shot repair
`repair.py` classifies repairable failures (`unknown_macro`, `arity_mismatch`,
`expansion_cycle`, `expansion_depth`, `lean_failed`) and builds a compact
targeted hint string that is injected as the memory pack for a single retry.
Each spec gets at most one repair attempt per iteration.

### Contextual bandit
`learning/contextual_bandit.py` maintains Beta(α, β) arms for every macro and
spec (uniform prior α=β=1).  Before each LLM call, Thompson sampling
(`random.betavariate`) ranks macros — the highest-ranked appear first in the
prompt, giving the bandit direct influence over generation quality.  Rewards:
verified = 1.0 (+0.15 for `information_preserving`, +0.15 for
`cleans_garbage`); failed = 0.0 (−0.20 extra if `information_losing` and
caller sets `prefer_info_preserving`).  State persists across runs in
`data/bandit/bandit.json`.

### RAG memory
`memory/` is a self-contained retrieval package.  Five card types:
`proof_trace`, `failure`, `macro`, `theorem_property`, `dsl_action`.  The
indexer creates cards from proof records, attempt logs, the macro registry, and
proven properties.  The retriever scores candidates by tag-overlap ÷ query
size, multiplied by a card-type weight and an optional info-structure boost
(0.10 per preferred key).  `prompt_pack.py` enforces a character budget
(default 600) before injecting into the user prompt.
`memory/theorem_exporter.py` is an idempotent pump: after each property-proof
round it pushes new `theorem_property` cards into the store.

### Information-structure tagging
Every macro, attempt, and card carries a lightweight heuristic tag set:
`information_preserving`, `information_losing`, `reversible_embedding`,
`uses_ancilla`, `cleans_garbage`.  These are Python heuristics (arity-1
bijection → IP; multi-output → IL), **not Lean-certified**.  They influence
bandit rewards and RAG retrieval boost but are never asserted as theorems.

---

## Layout

```
lean/           Lake project (see above)
python/leandream/
  orchestrator.py  learning/  memory/  ← main packages
  ast.py  miner.py  hierarchy.py  installer.py
  properties.py  proof_router.py  repair.py
  forest.py  attempts.py  verify.py
  translate.py  truthtable.py
  llm.py  mock_llm.py  prompts.py  promptlog.py
  web.py  web_static/   bootstrap.py  doctor.py
specs/          Curated spec library (JSON truth tables)
proofs/         Proof forest             [generated, gitignored]
prompts/        LLM prompt audit log     [generated, gitignored]
macros/         Macro registry JSON      [generated, gitignored]
runs/           Per-run attempt JSONL    [generated, gitignored]
data/bandit/    Bandit posterior JSON    [persists across runs]
data/cards/     RAG card store JSONL     [persists across runs]
```

---

## Prerequisites

- **Lean 4** via elan — tested with 4.29.1
- **Python 3.11+** (3.13 recommended)
- **OpenAI API key** — not required for `--mock` runs

## Setup

```sh
cp .env.example .env          # add OPENAI_API_KEY=sk-...
python3.13 -m venv venv && venv/bin/pip install -e python/
leandream-bootstrap            # scaffold dirs + check .env
leandream-doctor               # verify Lean + Python deps
cd lean && lake build          # pre-compile Lean toolchain (~2 min first time)
```

## Run

```sh
# Offline demo — full pipeline, no API key
leandream --mock --specs all --iterations 3

# Live run with real LLM
leandream --specs all --iterations 3

# Single spec
leandream --specs half_adder_sum --iterations 1

# Clean slate before running
leandream --reset --mock --specs all --iterations 4

# Tune mining
leandream --mock --specs all --iterations 5 --min-support 3 --min-size 4
```

State accumulates across runs by default — proof forest grows, bandit learns,
macro library expands.  Use `--reset` for a fresh start.

## Dashboard

```sh
leandream-web                  # http://127.0.0.1:8765
```

| Tab | Content |
|-----|---------|
| **Specs** | Truth table + accepted-proof count per spec |
| **Macros** | Macro ladder (sorted by level) — level badge, arity, TT, support, proven-property badges, info-structure tags, Lean body |
| **Proof Forest** | Accepted circuits per spec — raw AST (with mac refs) and expanded AST |
| **Prompts** | Full audit of every LLM call — prompts, response, reasoning, timing |
| **Timeline** | Every attempt across all runs — status badges, repair pass, LLM/Lean timing |
| **Bandit** | Spec and macro arm posteriors — mean, n, α, β, mean bar |
| **RAG** | Memory card store — type-filtered, tag pills, payload summary |
| **DSL Source** | Live `Macros.lean` |

## Key generated files

| Path | Contents |
|------|----------|
| `macros/registry.json` | Installed macros: arity, AST, TT, support, properties, macro_level, info_structure |
| `proofs/<spec>/<ts>.json` | Accepted proof records (raw + expanded AST) |
| `runs/<run_id>/attempts.jsonl` | Every attempt: status, timings, circuit, repair_pass |
| `data/bandit/bandit.json` | Bandit posterior state (persists across runs) |
| `data/cards/cards.jsonl` | RAG memory card store |
| `lean/LeanDream/Macros.lean` | Live macro definitions — diff across iterations to watch DSL grow |
| `lean/LeanDream/Properties.lean` | Proven algebraic theorems |
