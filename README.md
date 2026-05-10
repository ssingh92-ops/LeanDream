# LeanDream

**A neuro-symbolic system that grows a Lean-verified library of Boolean-circuit macros from natural-language specs.** An LLM proposes circuits as JSON; the Lean 4 theorem prover decides whether each one is correct; every accepted macro is itself certified by Lean before entering the DSL; the loop repeats with the larger library available to the next prompt.

---

## Scope and aims

LeanDream is a closed-loop research / hackathon system that demonstrates how a large language model and a proof assistant can cooperate to build up a *machine-verified domain-specific language* without an architect ever hand-writing the macros. The aims are:

1. **Bootstrap a DSL by proof**, not by intent. Every macro that lands in the DSL has been formally verified by Lean — both that it computes the truth-table the spec demanded *and* that the algebraic properties claimed about it (commutativity, associativity, etc.) actually hold.
2. **Make the LLM strictly a proposer.** The LLM never sees a proof, never produces a proof, and is never trusted. It emits JSON. Trust lives entirely in Lean's kernel.
3. **Make verification the gate at every transition.** A circuit is "verified" iff `lake build` succeeds. A macro is "installed" iff `lake build` succeeds on the file containing its definition. A property is "proven" iff `lake build` succeeds on the theorem stating it.
4. **Learn across iterations.** The system mines verified circuits for reusable substructure (parameterized macros), surfaces those macros to the next prompt, and uses a contextual bandit to rank macros by their downstream reward signal.

The current scope is **single-output combinational Boolean circuits**. Out of scope: sequential circuits, multi-output specs, arithmetic over Nat / Int, propositions that aren't decidable by truth-table enumeration. The architecture would extend to those, but they require additional Lean tactics and aren't part of this build.

---

## Lean is the only trusted component

```
         ┌───────────────────────────────────────────────────┐
         │                   PYTHON LAYER                    │
         │                                                   │
         │  Prompt ──► LLM ──► Repair? ──► Expand ──► Lean   │
         │    ▲                                       │      │
         │    │  RAG memory         Bandit            │      │
         │    │  card store  ◄────  update  ◄─────────┘      │
         │    │                                              │
         │  Mine ◄── Proof forest ◄── Install ◄── Prove      │
         └───────────────────────────────────────────────────┘
                          ▲        │
                          │  LEAN  │  (trusted proof engine)
                          └────────┘
```

There are exactly **three Lean-gated transitions** in the loop. Nothing in the Python layer trusts itself — every claim flows through Lean before being acted on:

| Gate | Where | Lean obligation | Failure → |
|---|---|---|---|
| **Spec verification** | every LLM attempt | `theorem candidate_correct : Circuit.equivOn arity candidate targetSpec = true := by native_decide` | attempt rejected; no proof entered into forest |
| **Macro installation** | every mined candidate | macro's `def` is appended to `Macros.lean`; the whole library must `lake build` cleanly | macro removed from registry; Macros.lean reverted |
| **Property certification** | every claimed property | `theorem macro_N_comm : ∀ a b : Bool, … := by circuit_decide` | property dropped from registry, never surfaced to prompt or RAG |

`native_decide` enumerates the truth table inside Lean's compiled kernel — it cannot emit a proof unless every input row matches. `decide` does the same in the kernel directly (used for arity ≤ 4 via the `circuit_decide` tactic in `ProofMode.lean`). Cache keys for the Lean verifier include the Lean toolchain version, so upgrading Lean automatically invalidates every cached "verified" verdict.

The LLM never produces a proof term, never modifies a `.lean` file, and never sees a verification result other than the binary outcome. The only thing it can influence is *what circuit to propose* — the proof obligation is independent of how the proposal was made.

---

## What's been completed

The system is fully operational end-to-end. Concrete capabilities currently shipping:

### Lean layer

- ✅ **Deep-embedded DSL** (`DSL.lean`): `Circuit` as an inductive type with `var`, `const`, `not`, `and`, `or`, `xor`. `eval`, `envOf`, `equivOn` defined.
- ✅ **`circuit_decide` tactic** (`ProofMode.lean`): tries `decide` first, falls back to `native_decide` — chooses the right kernel verification path for the spec arity.
- ✅ **Proof router** (`ProofRouter.lean`): `decideMaxArity = 4`, exposed both to Lean and to Python (`proof_router.py`) so the Python side can predict which strategy will be used.
- ✅ **Simp lemmas** (`SimpSets.lean`): `@[simp]` eval-unfolding lemmas for manual / semi-automated proofs.
- ✅ **Reference spec library** (`Specs.lean`): hand-written specs for adders, mux, parity, majority, NAND, etc., plus an auto-generated section regenerated from formula stubs.
- ✅ **Algebraic property theorems** (`Properties.lean`, regenerated each iteration): commutativity, associativity, idempotence, identity, annihilator, involution — all decidable via `circuit_decide`.
- ✅ **Macro file** (`Macros.lean`, regenerated each iteration): every installed macro is a parameterized Lean `def macro_N (x0 x1 … : Circuit) : Circuit := …`. The file must `lake build` for a macro to count as installed.

### Python layer

- ✅ **Orchestrator** (`orchestrator.py`): generate → expand → preflight → verify → record → mine → install → prove → re-prompt loop. Single-spec or curriculum modes.
- ✅ **Pydantic AST** (`ast.py`) mirroring the Lean `Circuit` inductive, with cycle/depth/arity guards on macro expansion.
- ✅ **JSON ↔ Lean translator** (`translate.py`): renders Python ASTs to Lean syntax for both `Candidate.lean` and parameterized `Macros.lean` defs.
- ✅ **Frequent-subtree miner** (`miner.py`): canonical-form mining (free vars renamed in occurrence order so structurally-identical subtrees collide), plus `mine_macro_compositions` for macro-of-macro patterns.
- ✅ **Macro hierarchy** (`hierarchy.py`): each macro tagged with `macro_level` (0 = primitives only; ≥ 1 = uses other macros). Installer guarantees a DAG.
- ✅ **Installer** (`installer.py`): structural dedup (canonical hash key), truth-table dedup (rejects functions equivalent or NOT-equivalent to existing macros), then Lean rebuild as the install criterion.
- ✅ **Property prover** (`properties.py`): Python truth-table predicates pre-filter candidate properties, then a single `lake build` certifies the survivors. Anything Python believes is true that Lean rejects gets dropped — Lean is final.
- ✅ **Standalone theorem generator** (`theorem_gen.py` + `TheoremGen.lean`): broader properties (e.g. `commutativity for arbitrary Circuit args`) proved by `simp` + case analysis.
- ✅ **Preflight + repair** (`preflight.py`, `repair.py`): catches `unknown_macro`, `arity_mismatch`, `expansion_cycle`, `expansion_depth`, and Lean-build failures; injects targeted hints for one-shot retries.
- ✅ **Contextual bandit** (`learning/contextual_bandit.py`): Beta(α, β) arms per (spec, macro). Thompson-ranked macros lead the prompt. Arms are tagged with the macro's truth-table key, so name collisions across runs auto-reset the posterior instead of poisoning a different circuit.
- ✅ **RAG memory** (`memory/`): proof traces, failures, macros, theorem properties, DSL actions — all retrievable by tag overlap with type-weighted scoring. Theorem-property cards carry `trust_level: lean_verified`.
- ✅ **Curriculum runner** (`curriculum.py`): 8 staged spec groupings with verify-rate gates and retries.
- ✅ **Persistent caches** (`cache.py`): disk-backed for verify, LLM, and property-prove. Toolchain-version-keyed so Lean upgrades invalidate automatically.
- ✅ **Information-structure heuristics** (in `installer.py`): five tags (`information_preserving` / `information_losing` / `reversible_embedding` / `uses_ancilla` / `cleans_garbage`). These are **explicitly Python heuristics, never asserted as theorems** — they shape bandit reward and RAG retrieval but never claim to be proven.
- ✅ **Spec formula library** (`spec_formulas.py`): formula-driven specs (parity, majority, comparators, threshold, palindrome, rotate-equality, NOR/NAND chains) so `specs/*.json` stubs can be one-line; truth tables and reference Lean Circuits are generated at load time.

### Tooling and observability

- ✅ **Web dashboard** (`web.py` + `web_static/`): per-run summary, proof forest graph, macro ladder (with TT, support, proven-property badges, info-structure tags, Lean body), prompt audit log, attempt timeline, bandit posteriors, RAG card browser, live `Macros.lean` viewer, generated theorem attempts.
- ✅ **CLIs**: `leandream`, `leandream-curriculum`, `leandream-web`, `leandream-bootstrap`, `leandream-doctor`, `leandream-report`, `leandream-analyze`, `leandream-audit`, `leandream-theorem-gen`.
- ✅ **Per-run artifacts** (`runs/<id>/`): `attempts.jsonl`, `metrics.csv`, `summary.json`, `theorem_gen_results.json`, `report.md`.
- ✅ **Test suite**: 79 pytest tests across translator, miner, semantic roles, V4 metrics, and speed-hardening.

---

## Repository layout

```
lean/                              Lake project (the trusted layer)
  lakefile.toml
  lean-toolchain                   # pinned to leanprover/lean4:v4.29.1
  LeanDream/
    DSL.lean                       Circuit, eval, equivOn
    ProofMode.lean                 circuit_decide tactic
    ProofRouter.lean               decideMaxArity = 4
    SimpSets.lean                  @[simp] lemmas for eval
    Specs.lean                     reference circuits
    Macros.lean                    installed macros (regenerated)
    Candidate.lean                 verification target (regenerated each attempt)
    Verify.lean                    candidate_correct theorem
    Properties.lean                proven algebraic theorems (regenerated)
    TheoremGen.lean                stronger general-Circuit theorems
    EmitTheoremCards.lean          theorem-card metadata emission

python/leandream/                  Python orchestration around Lean
  orchestrator.py                  the loop
  ast.py                           Pydantic Circuit AST
  translate.py                     AST ↔ Lean source
  verify.py                        subprocess wrapper around `lake build`
  forest.py                        proof forest persistence
  miner.py                         frequent-subtree mining
  hierarchy.py                     macro DAG / level computation
  installer.py                     macro install with Lean rebuild
  properties.py                    algebraic-property prover
  theorem_gen.py                   general-Circuit theorem generator
  preflight.py / repair.py         pre-Lean validation + targeted retries
  llm.py / mock_llm.py             LLM client (real + canned)
  prompts.py / promptlog.py        prompt construction + audit log
  attempts.py                      per-attempt JSONL writer
  proof_router.py                  picks decide vs native_decide
  truthtable.py                    canonical TT computation
  spec_formulas.py                 formula library for parametric specs
  specs_gen.py                     regenerates the GENERATED section of Specs.lean
  cache.py                         persistent disk caches
  curriculum.py                    staged learning runner
  metrics.py / analysis.py         per-run / cross-run metrics
  reports.py / audit.py            human-readable reports
  bootstrap.py / doctor.py         setup + env validation
  hole_detector.py                 spec-coverage hole detection
  failure_modes.py                 structured failure descriptors
  learning/
    contextual_bandit.py           Beta-arm Thompson sampling
  memory/
    cards.py / card_store.py       RAG card model + store
    indexer.py / retriever.py      build + retrieve cards
    prompt_pack.py                 budget-bounded prompt injection
    theorem_exporter.py            export proven properties to RAG
  web.py / web_static/             FastAPI viewer

specs/                             curated spec library (JSON)
proofs/                            proof forest               [generated, gitignored]
prompts/                           LLM prompt audit log       [generated, gitignored]
macros/                            macro registry JSON        [generated, gitignored]
runs/                              per-run attempt logs       [generated, gitignored]
data/bandit/                       bandit posteriors          [persists across runs]
data/cards/                        RAG card store             [persists across runs]
data/cache/                        verify / LLM / prop caches [persists across runs]
```

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| **Lean 4** | 4.29.1 (pinned) | installed via `elan`; the toolchain is auto-fetched on first `lake build` |
| **Python** | ≥ 3.11 (3.13 tested) | needs Pydantic v2 |
| **OpenAI API key** | — | only for live runs; not needed for `--mock` |
| **macOS / Linux** | — | tested on macOS; Linux should work; Windows untested |

---

## Installation

```sh
# 1. Get Lean toolchain (one-time)
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh
# accept defaults; this installs `elan`, `lean`, `lake` into ~/.elan

# 2. Clone
git clone <this-repo-url> LeanDream
cd LeanDream

# 3. Configure environment
cp .env.example .env
# edit .env and set: OPENAI_API_KEY=sk-...
# optional: LEANDREAM_MODEL=gpt-5  (or gpt-5-mini, gpt-4.1, etc.)

# 4. Python venv + editable install (the editable install registers all 9 CLIs)
python3 -m venv venv
source venv/bin/activate
pip install -e python/

# 5. Sanity-check the install
leandream-bootstrap        # scaffolds proofs/, prompts/, macros/, runs/, data/
leandream-doctor           # confirms Lean + Python deps + .env

# 6. Pre-compile the Lean toolchain (first build pulls Lean and compiles the
#    DSL; expect ~1-2 minutes the first time, then sub-second incrementals)
cd lean && lake build && cd ..
```

> **Note on entry points**: `pip install -e python/` registers nine console scripts (`leandream`, `leandream-curriculum`, `leandream-web`, `leandream-bootstrap`, `leandream-doctor`, `leandream-report`, `leandream-analyze`, `leandream-audit`, `leandream-theorem-gen`). If any of them are missing, re-run `pip install -e python/` — pip caches the entry-point list at install time, not at import time. The most recent install will pick up any new scripts declared in `python/pyproject.toml`.

> **Note on macOS Python**: if you have multiple Pythons, prefer the framework Python (e.g. from python.org) over Homebrew's; some Pydantic + uvloop builds are simpler that way.

> **Note on Lean memory**: `native_decide` for high-arity specs (≥ 8) uses the Lean compiler. The first compile of the day takes ~30 s; subsequent compiles are cached.

---

## Running

```sh
# Offline demo — full pipeline, no API key needed
leandream --mock --specs all --iterations 3

# Live run with the real LLM (gpt-5 by default)
leandream --specs all --iterations 3

# A single spec, one iteration
leandream --specs half_adder_sum --iterations 1

# Wipe accumulated state, then run
leandream --reset --specs all --iterations 4

# Tune mining
leandream --specs all --iterations 5 --min-support 3 --min-size 4

# Staged curriculum (8 stages: smoke → connectives → adder → mux → full → motif → parity_ladder → majority_ladder)
leandream-curriculum
leandream-curriculum --reset                # also wipes bandit + RAG + caches
leandream-curriculum --start 6 --end 7      # just the new ladders
```

State **accumulates across runs** by default — proof forest grows, bandit learns, macro library expands, RAG cards persist. Use `--reset` (per-run state) or `leandream-curriculum --reset` (additionally wipes `data/bandit`, `data/cards`, `data/cache`, `runs/`) for a clean slate.

### What happens during one iteration

For every spec in the iteration's spec list:

1. **Prompt construction**: `prompts.build_user_prompt` renders the spec's truth table (truncated for arity ≥ 5), the bandit-ranked macro list with proven properties, retrieved RAG cards, and an arity-3+ "compose-first" nudge.
2. **LLM call**: `llm.generate_circuit` asks OpenAI for a JSON Circuit AST under structured-output mode. Logged to `prompts/<spec>/<ts>.json`.
3. **Preflight**: Python validates `mac` references and arities before sending to Lean. Catches the cheap mistakes.
4. **Macro expansion**: `Mac` references are inlined to a primitive AST. Cycle, depth, and arity guards.
5. **Spec verification (Lean)**: `verify.verify_candidate` writes `Candidate.lean` declaring the candidate and target spec, then runs `lake build`. **`native_decide` discharges `Circuit.equivOn arity candidate targetSpec = true`. Build success is the proof.**
6. **Repair retry** (if applicable): on `unknown_macro` / `arity_mismatch` / `expansion_*` / `lean_failed`, `repair.py` builds a targeted hint and gives the LLM one more chance.
7. **Forest record**: only verified circuits are recorded to `proofs/<spec>/<ts>.json` with both raw and expanded ASTs.
8. **Bandit update**: rewards land on every (spec, macro) arm involved.

After all specs in the iteration:

9. **Mining**: `miner.mine` extracts frequent canonical subtrees from the forest. `mine_macro_compositions` looks at raw circuits for macro-of-macro patterns.
10. **Macro install (Lean)**: each surviving candidate is appended to `Macros.lean`, then `lake build` runs. **A macro is "installed" if and only if the whole library still builds.**
11. **Property proving (Lean)**: candidate properties are filtered by Python TT predicates, then certified in a single `lake build` of `Properties.lean`. **Properties claimed but not proven are silently dropped — the registry never carries an unproven property.**
12. **Theorem gen (Lean)**: stronger general-Circuit theorems via `simp` + case analysis go to `TheoremGen.lean`.
13. **RAG export**: proven properties become `theorem_property` cards tagged `trust_level: lean_verified`.

If any Lean step fails at any point, the corresponding registry entry / theorem / proof never enters the system. There is no path by which an unverified claim becomes part of the DSL.

---

## Dashboard

```sh
leandream-web                  # http://127.0.0.1:8765
```

| Tab | Content |
|---|---|
| **Home** | Pipeline diagram + live stats |
| **Run** | Per-run summary: stat cards, per-iteration table, per-spec breakdown, failure-mode counts |
| **Curriculum** | Stage definitions and accumulated gate status |
| **Specs** | Each spec's truth table (truncated for arity ≥ 5) + accepted-proof count |
| **Macros** | Macro ladder: arity, hierarchy level, canonical TT, support, bandit posterior, **Lean-proven** property badges, info-structure heuristic tags, Lean body |
| **Proof Forest** | Accepted circuits per spec — raw AST (with mac refs) and expanded AST tree |
| **Holes** | Specs the system can't solve — clusters of failure modes that could not be repaired |
| **Prompts** | Audit of every LLM call — system + user prompt verbatim, response, reasoning, timing |
| **Timeline** | Every attempt across runs — status, repair, LLM/Lean ms |
| **Bandit** | Spec and macro arm posteriors — α, β, mean, n |
| **RAG** | Memory card store with type filter and tag pills |
| **Metrics** | Per-iteration metrics chart |
| **Lean** | Proof-mode distribution; theorem-card coverage by macro; generated-theorem attempts table |
| **DSL Source** | Live `Macros.lean` (the regenerated definitions) |

---

## Generated artifacts

| Path | Contents |
|---|---|
| `macros/registry.json` | Installed macros: arity, AST, TT key, support, **Lean-proven** properties, macro_level, info-structure heuristics, bandit-arm tt_key |
| `proofs/<spec>/<ts>.json` | Accepted proof records (raw + expanded AST + iteration + elapsed) |
| `prompts/<spec>/<ts>.json` | Every LLM call — system/user prompt, macros in scope, response, reasoning |
| `runs/<run_id>/attempts.jsonl` | Every attempt: status, timings, raw/expanded circuit, repair_pass |
| `runs/<run_id>/summary.json` | Run totals, verify rate, blocking reasons, recommended action |
| `runs/<run_id>/metrics.csv` | Per-iteration metrics (verify rate, new macros, new theorems, timings) |
| `runs/<run_id>/theorem_gen_results.json` | Per-macro general-Circuit theorem outcomes |
| `data/bandit/bandit.json` | Bandit posterior state, persists across runs |
| `data/cards/cards.jsonl` | RAG card store, persists across runs |
| `data/cache/*.json` | Verify / LLM / property caches, toolchain-keyed |
| `lean/LeanDream/Macros.lean` | Live macro definitions — diff across iterations to watch the DSL grow |
| `lean/LeanDream/Properties.lean` | Currently-certified algebraic theorems (regenerated each iteration) |

---

## Configuration

The CLI flags cover most knobs; persistent settings go through `.env`:

```
OPENAI_API_KEY=sk-...
LEANDREAM_MODEL=gpt-5         # or gpt-5-mini / gpt-4.1
```

Mining thresholds (`--min-support`, `--min-size`), curriculum scope (`--start`, `--end`), and reset behavior (`--reset`) are per-invocation.

The Lean toolchain is pinned in `lean/lean-toolchain` to `leanprover/lean4:v4.29.1`. Bumping it auto-invalidates all caches. The `circuit_decide` arity threshold (kernel `decide` ↔ compiled `native_decide`) lives at `ProofRouter.lean:decideMaxArity = 4` and is mirrored in `python/leandream/proof_router.py`.

---

## What's not in scope

- **Sequential circuits, multi-output specs, arithmetic.** Combinational Boolean only.
- **Automated proof search beyond decidable propositions.** We rely on `decide` and `native_decide`. No tactic search, no SMT integration.
- **Macro-name persistence across `--reset`.** The bandit's tt_key tagging keeps cross-run posteriors honest, but macro names themselves are sequential and reused.
- **Defending against an adversarial LLM.** The verifier is a sound check; if the LLM produces malformed JSON the preflight catches it, and if it produces an incorrect circuit Lean catches it. We do not, however, defend against e.g. resource-exhaustion attacks via giant ASTs.

---

## License / authorship

Hackathon project; no external license attached. Built on top of Lean 4 (Apache 2.0), Pydantic, FastAPI, and the OpenAI Python SDK.
