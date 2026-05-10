"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "className") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === false || v == null) {}
    else if (v === true) node.setAttribute(k, "");
    else node.setAttribute(k, v);
  }
  const append = (c) => {
    if (c == null || c === false) return;
    if (Array.isArray(c)) { for (const x of c) append(x); return; }
    if (typeof c === "string") node.appendChild(document.createTextNode(c));
    else node.appendChild(c);
  };
  for (const c of children) append(c);
  return node;
}

// ----- AST rendering -----

function nodeLabel(n) {
  switch (n.kind) {
    case "var": return `var(${n.index})`;
    case "const": return n.value ? "1" : "0";
    case "not": return "not";
    case "and": return "and";
    case "or":  return "or";
    case "xor": return "xor";
    case "mac": return n.name;
    default: return JSON.stringify(n);
  }
}

function children(n) {
  if (n.kind === "not") return [n.arg];
  if (n.kind === "and" || n.kind === "or" || n.kind === "xor") return [n.left, n.right];
  return [];
}

function renderAST(n) {
  const root = el("div", { className: "ast" });
  function rec(node, parent) {
    const li = el("li");
    li.appendChild(el("span", { className: `node ${node.kind}` }, nodeLabel(node)));
    const kids = children(node);
    if (kids.length) {
      const ul = el("ul");
      for (const k of kids) rec(k, ul);
      li.appendChild(ul);
    }
    parent.appendChild(li);
  }
  const ul = el("ul");
  rec(n, ul);
  root.appendChild(ul);
  return root;
}

function astToSExpr(n) {
  switch (n.kind) {
    case "var": return `x${n.index}`;
    case "const": return n.value ? "1" : "0";
    case "not": return `(¬ ${astToSExpr(n.arg)})`;
    case "and": return `(${astToSExpr(n.left)} ∧ ${astToSExpr(n.right)})`;
    case "or":  return `(${astToSExpr(n.left)} ∨ ${astToSExpr(n.right)})`;
    case "xor": return `(${astToSExpr(n.left)} ⊕ ${astToSExpr(n.right)})`;
    case "mac": return n.name;
  }
}

// ----- Stats -----

async function loadStats() {
  const s = await api("/api/stats");
  const stats = $("#stats");
  stats.innerHTML = "";
  const items = [
    ["Specs", s.specs],
    ["Proofs", s.proofs],
    ["Macros", s.macros],
    ["Attempts", s.attempts ?? 0],
    ["Cards", s.cards ?? 0],
    ["Iterations", s.iterations_seen.length],
  ];
  for (const [label, n] of items) {
    stats.appendChild(el("div", { className: "stat" },
      el("span", { className: "num" }, String(n)),
      label,
    ));
  }
}

// ----- Specs tab -----

let specsCache = null;
let proofsCache = null;

async function loadSpecs() {
  specsCache = await api("/api/specs");
  proofsCache = await api("/api/proofs");
  const list = $("#specs-list");
  list.innerHTML = "";
  for (const spec of specsCache) {
    const proofCount = proofsCache.filter(p => p.spec === spec.name).length;
    const item = el("div", {
      className: "list-item",
      onclick: () => selectSpec(spec.name),
      "data-spec": spec.name,
    },
      spec.name,
      el("div", { className: "meta" }, `arity ${spec.arity} · ${proofCount} proof(s)`),
    );
    list.appendChild(item);
  }
}

function selectSpec(name) {
  $$("#specs-list .list-item").forEach(i => i.classList.toggle("selected", i.dataset.spec === name));
  const spec = specsCache.find(s => s.name === name);
  const proofs = proofsCache.filter(p => p.spec === name);
  const detail = $("#specs-detail");
  detail.innerHTML = "";
  detail.appendChild(el("h2", {}, spec.name));
  if (spec.description) detail.appendChild(el("div", { className: "desc" }, spec.description));

  detail.appendChild(el("div", { className: "kv" },
    el("div", { className: "k" }, "arity"), el("div", { className: "v" }, String(spec.arity)),
    el("div", { className: "k" }, "inputs"), el("div", { className: "v" }, spec.inputs.join(", ")),
    el("div", { className: "k" }, "lean spec"), el("div", { className: "v" }, spec.lean_spec),
    el("div", { className: "k" }, "proofs accepted"), el("div", { className: "v" }, String(proofs.length)),
  ));

  detail.appendChild(el("div", { className: "section-label" }, "truth table"));
  detail.appendChild(renderTruthTable(spec));

  if (proofs.length) {
    detail.appendChild(el("div", { className: "section-label" }, "accepted proofs"));
    const ul = el("ul");
    for (const p of proofs) {
      ul.appendChild(el("li", {},
        `iter ${p.iteration} · ${p.timestamp} · ${p.elapsed_seconds.toFixed(2)}s`,
      ));
    }
    detail.appendChild(ul);
  }
}

function renderTruthTable(spec) {
  const t = el("table", { className: "tt" });
  const thead = el("thead", {},
    el("tr", {},
      ...spec.inputs.map(i => el("th", {}, i)),
      el("th", {}, "out"),
    ),
  );
  const tbody = el("tbody");
  for (const row of spec.truth_table) {
    tbody.appendChild(el("tr", {},
      ...row.inputs.map(v => el("td", {}, v ? "1" : "0")),
      el("td", { className: "out" }, row.output ? "1" : "0"),
    ));
  }
  t.appendChild(thead);
  t.appendChild(tbody);
  return t;
}

// ----- Macros tab (with macro_level + info_structure) -----

function macroLevelBadge(level) {
  const lvl = level ?? 0;
  const cls = lvl === 0 ? "lvl-0" : lvl === 1 ? "lvl-1" : "lvl-2p";
  return el("span", { className: `lvl-badge ${cls}` }, String(lvl));
}

function infoTags(info) {
  if (!info) return null;
  const keys = ["information_preserving", "information_losing", "reversible_embedding",
                "uses_ancilla", "cleans_garbage"];
  const short = { information_preserving: "IP", information_losing: "IL",
                  reversible_embedding: "RE", uses_ancilla: "anc", cleans_garbage: "CG" };
  const wrap = el("span", {});
  let any = false;
  for (const k of keys) {
    if (info[k] === true) {
      wrap.appendChild(el("span", { className: `info-tag it-${k.replace(/_/g, "-")}` }, short[k]));
      any = true;
    }
  }
  return any ? wrap : null;
}

async function loadMacros() {
  const macros = await api("/api/macros");
  const root = $("#macros-table");
  root.innerHTML = "";
  if (Object.keys(macros).length === 0) {
    root.appendChild(el("p", { className: "empty" }, "No macros installed yet. Run the orchestrator."));
    return;
  }
  const tbl = el("table", { className: "macros" });
  tbl.appendChild(el("thead", {},
    el("tr", {},
      el("th", {}, "name"),
      el("th", {}, "arity"),
      el("th", {}, "lvl"),
      el("th", {}, "TT"),
      el("th", {}, "support"),
      el("th", {}, "properties"),
      el("th", {}, "info"),
      el("th", {}, "members"),
      el("th", {}, "body"),
    ),
  ));
  const tbody = el("tbody");
  // Sort by macro_level asc, then support desc (macro ladder order)
  const sorted = Object.entries(macros).sort((a, b) => {
    const la = a[1].macro_level ?? 0, lb = b[1].macro_level ?? 0;
    if (la !== lb) return la - lb;
    return (b[1].support ?? 0) - (a[1].support ?? 0);
  });
  for (const [name, info] of sorted) {
    const tagsCell = el("td", {});
    for (const m of (info.members || [])) tagsCell.appendChild(el("span", { className: "spec-tag" }, m));

    const propsCell = el("td", {});
    for (const p of (info.properties || [])) {
      propsCell.appendChild(el("span", { className: "prop-badge" }, p));
    }
    if (!info.properties || info.properties.length === 0) {
      propsCell.appendChild(el("span", { className: "meta" }, "—"));
    }

    const infoCell = el("td", {});
    const itags = infoTags(info.info_structure);
    if (itags) infoCell.appendChild(itags);

    const bodyText = info.body_repr || (info.ast ? astToSExpr(info.ast) : "");

    tbody.appendChild(el("tr", {},
      el("td", {}, el("code", {}, name)),
      el("td", {}, String(info.arity ?? "?")),
      el("td", {}, macroLevelBadge(info.macro_level)),
      el("td", {}, info.tt_key ? el("code", {}, info.tt_key) : el("span", { className: "meta" }, "—")),
      el("td", {}, el("span", { className: "support-bar" }, String(info.support ?? 0))),
      propsCell,
      infoCell,
      tagsCell,
      el("td", {}, el("code", {}, bodyText)),
    ));
  }
  tbl.appendChild(tbody);
  root.appendChild(tbl);
}

// ----- Proofs tab -----

async function loadProofs() {
  if (!proofsCache) proofsCache = await api("/api/proofs");
  const filter = $("#proof-filter");
  const specs = [...new Set(proofsCache.map(p => p.spec))].sort();
  filter.innerHTML = '<option value="">all</option>';
  for (const s of specs) filter.appendChild(el("option", { value: s }, s));
  filter.onchange = renderProofList;
  renderProofList();
}

function renderProofList() {
  const filter = $("#proof-filter").value;
  const list = $("#proofs-list");
  list.innerHTML = "";
  const filtered = filter ? proofsCache.filter(p => p.spec === filter) : proofsCache;
  for (const p of filtered) {
    list.appendChild(el("div", {
      className: "list-item",
      "data-key": `${p.spec}/${p.filename}`,
      onclick: () => selectProof(p.spec, p.filename),
    },
      p.spec,
      el("div", { className: "meta" }, `iter ${p.iteration} · ${p.timestamp.slice(0, 15)} · ${p.elapsed_seconds.toFixed(2)}s`),
    ));
  }
}

async function selectProof(spec, filename) {
  $$("#proofs-list .list-item").forEach(i => i.classList.toggle("selected", i.dataset.key === `${spec}/${filename}`));
  const proof = await api(`/api/proofs/${spec}/${filename}`);
  const detail = $("#proofs-detail");
  detail.innerHTML = "";
  detail.appendChild(el("h2", {}, `${proof.spec}`));
  detail.appendChild(el("div", { className: "kv" },
    el("div", { className: "k" }, "iteration"), el("div", { className: "v" }, String(proof.iteration)),
    el("div", { className: "k" }, "timestamp"), el("div", { className: "v" }, proof.timestamp),
    el("div", { className: "k" }, "elapsed"), el("div", { className: "v" }, `${proof.elapsed_seconds.toFixed(2)}s`),
  ));

  detail.appendChild(el("div", { className: "section-label" }, "raw AST (as emitted by LLM)"));
  detail.appendChild(el("p", { className: "desc" }, "Macro references shown as orange nodes."));
  detail.appendChild(renderAST(proof.raw));
  detail.appendChild(el("pre", {}, astToSExpr(proof.raw)));

  detail.appendChild(el("div", { className: "section-label" }, "expanded AST (after macro inlining; what the miner sees)"));
  detail.appendChild(renderAST(proof.expanded));
  detail.appendChild(el("pre", {}, astToSExpr(proof.expanded)));
}

// ----- Prompts tab -----

let promptsCache = null;

async function loadPrompts() {
  promptsCache = await api("/api/prompts");
  const specSel = $("#prompt-filter");
  const iterSel = $("#prompt-iter-filter");
  const specs = [...new Set(promptsCache.map(p => p.spec))].sort();
  const iters = [...new Set(promptsCache.map(p => p.iteration))].sort((a, b) => a - b);

  specSel.innerHTML = '<option value="">all</option>';
  for (const s of specs) specSel.appendChild(el("option", { value: s }, s));
  iterSel.innerHTML = '<option value="">all</option>';
  for (const i of iters) iterSel.appendChild(el("option", { value: String(i) }, `iter ${i}`));

  specSel.onchange = renderPromptList;
  iterSel.onchange = renderPromptList;
  renderPromptList();
}

function renderPromptList() {
  const fSpec = $("#prompt-filter").value;
  const fIter = $("#prompt-iter-filter").value;
  const list = $("#prompts-list");
  list.innerHTML = "";
  const filtered = promptsCache.filter(p =>
    (!fSpec || p.spec === fSpec) &&
    (fIter === "" || String(p.iteration) === fIter)
  );
  if (!filtered.length) {
    list.appendChild(el("div", { className: "empty" }, "No prompts match."));
    return;
  }
  for (const p of filtered) {
    const item = el("div", {
      className: "list-item",
      "data-key": `${p.spec}/${p.filename}`,
      onclick: () => selectPrompt(p.spec, p.filename),
    },
      p.spec,
      el("div", { className: "row" },
        el("span", { className: "badge iter" }, `iter ${p.iteration}`),
        el("span", { className: `badge ${p.ok ? "ok" : "fail"}` }, p.ok ? "ok" : "err"),
        el("span", { className: "meta" }, ` ${p.macros_count} macro(s) · ${p.elapsed_seconds.toFixed(1)}s`),
      ),
      el("div", { className: "meta" }, `${p.timestamp.slice(0, 15)} · ${p.model}`),
    );
    list.appendChild(item);
  }
}

async function selectPrompt(spec, filename) {
  $$("#prompts-list .list-item").forEach(i => i.classList.toggle("selected", i.dataset.key === `${spec}/${filename}`));
  const data = await api(`/api/prompts/${spec}/${filename}`);
  const detail = $("#prompts-detail");
  detail.innerHTML = "";
  detail.appendChild(el("h2", {}, `${data.spec} · iter ${data.iteration}`));
  detail.appendChild(el("div", { className: "kv" },
    el("div", { className: "k" }, "model"),     el("div", { className: "v" }, data.model || ""),
    el("div", { className: "k" }, "timestamp"), el("div", { className: "v" }, data.timestamp || ""),
    el("div", { className: "k" }, "elapsed"),   el("div", { className: "v" }, `${(data.elapsed_seconds ?? 0).toFixed(2)}s`),
    el("div", { className: "k" }, "result"),    el("div", { className: "v" },
      el("span", { className: `badge ${data.ok ? "ok" : "fail"}` }, data.ok ? "ok" : "error"),
    ),
    el("div", { className: "k" }, "macros in prompt"), el("div", { className: "v" },
      data.macros_in_prompt && data.macros_in_prompt.length
        ? data.macros_in_prompt.map(m => el("span", { className: "spec-tag" }, m))
        : el("span", { className: "meta" }, "(none)"),
    ),
  ));

  if (data.error) {
    detail.appendChild(el("div", { className: "section-label" }, "error"));
    detail.appendChild(el("pre", {}, data.error));
  }

  detail.appendChild(el("div", { className: "section-label" }, "system prompt"));
  detail.appendChild(el("pre", { className: "prompt" }, data.system_prompt || ""));

  detail.appendChild(el("div", { className: "section-label" }, "user prompt"));
  detail.appendChild(el("pre", { className: "prompt" }, data.user_prompt || ""));

  if (data.reasoning) {
    detail.appendChild(el("div", { className: "section-label" }, "reasoning (from response)"));
    detail.appendChild(el("pre", {}, data.reasoning));
  }

  if (data.response_circuit) {
    detail.appendChild(el("div", { className: "section-label" }, "response circuit"));
    detail.appendChild(renderAST(data.response_circuit));
    detail.appendChild(el("pre", {}, astToSExpr(data.response_circuit)));
  }
}

// ----- DSL source tab -----

async function loadDSL() {
  const data = await api("/api/macros/lean");
  $("#dsl-source").textContent = data.source;
}

// ----- Timeline tab -----

let attemptsCache = null;

const STATUS_CLASS = {
  verified: "ok",
  lean_failed: "fail",
  lean_timeout: "warn",
  llm_error: "fail",
  schema_error: "muted-badge",
  unknown_macro: "warn",
  arity_mismatch: "warn",
  expansion_cycle: "warn",
  expansion_depth: "warn",
  internal_error: "muted-badge",
};

function statusBadge(status) {
  const cls = STATUS_CLASS[status] || "muted-badge";
  return el("span", { className: `badge ${cls}` }, (status || "?").replace(/_/g, " "));
}

async function loadTimeline() {
  attemptsCache = await api("/api/attempts");
  const runSel = $("#timeline-run-filter");
  const specSel = $("#timeline-spec-filter");
  const statusSel = $("#timeline-status-filter");

  const runs = [...new Set(attemptsCache.map(a => a.run_id).filter(Boolean))].sort().reverse();
  const specs = [...new Set(attemptsCache.map(a => a.spec).filter(Boolean))].sort();
  const statuses = [...new Set(attemptsCache.map(a => a.status).filter(Boolean))].sort();

  runSel.innerHTML = '<option value="">all runs</option>';
  runs.forEach(r => runSel.appendChild(el("option", { value: r }, r.slice(0, 24))));
  specSel.innerHTML = '<option value="">all specs</option>';
  specs.forEach(s => specSel.appendChild(el("option", { value: s }, s)));
  statusSel.innerHTML = '<option value="">all statuses</option>';
  statuses.forEach(s => statusSel.appendChild(el("option", { value: s }, s)));

  runSel.onchange = specSel.onchange = statusSel.onchange = renderTimeline;
  renderTimeline();
}

function renderTimeline() {
  const fRun    = $("#timeline-run-filter").value;
  const fSpec   = $("#timeline-spec-filter").value;
  const fStatus = $("#timeline-status-filter").value;

  const filtered = (attemptsCache || []).filter(a =>
    (!fRun    || a.run_id === fRun) &&
    (!fSpec   || a.spec   === fSpec) &&
    (!fStatus || a.status === fStatus)
  );

  const root = $("#timeline-table");
  root.innerHTML = "";
  if (!filtered.length) {
    root.appendChild(el("p", { className: "empty" }, "No attempts match."));
    return;
  }

  const tbl = el("table", { className: "timeline" });
  tbl.appendChild(el("thead", {},
    el("tr", {},
      el("th", {}, "iter"),
      el("th", {}, "spec"),
      el("th", {}, "status"),
      el("th", {}, "repair"),
      el("th", {}, "LLM ms"),
      el("th", {}, "Lean ms"),
      el("th", {}, "time"),
    ),
  ));
  const tbody = el("tbody");
  for (const a of filtered) {  // already newest-first from API
    const llmMs  = a.llm_time_ms  != null ? Math.round(a.llm_time_ms).toLocaleString()  : "—";
    const leanMs = a.lean_time_ms != null ? Math.round(a.lean_time_ms).toLocaleString() : "—";
    const repairEl = a.repair_pass != null
      ? el("span", { className: "badge iter" }, `pass ${a.repair_pass}`)
      : el("span", { className: "meta" }, "—");
    tbody.appendChild(el("tr", { className: a.status === "verified" ? "row-ok" : "" },
      el("td", { className: "num" }, String(a.iteration ?? "?")),
      el("td", {}, el("code", {}, a.spec || "?")),
      el("td", {}, statusBadge(a.status)),
      el("td", {}, repairEl),
      el("td", { className: "num" }, llmMs),
      el("td", { className: "num" }, leanMs),
      el("td", { className: "meta" }, (a.timestamp || "").slice(11, 19)),
    ));
  }
  tbl.appendChild(tbody);
  root.appendChild(tbl);
}

// ----- Bandit tab -----

async function loadBandit() {
  const data = await api("/api/bandit");
  const entries = Object.entries(data);
  const specEntries  = entries.filter(([k]) => k.startsWith("spec:"))
                              .sort((a, b) => b[1].mean - a[1].mean);
  const macroEntries = entries.filter(([k]) => k.startsWith("macro:"))
                              .sort((a, b) => b[1].mean - a[1].mean);
  renderBanditTable(specEntries,  "#bandit-spec-table",  "spec");
  renderBanditTable(macroEntries, "#bandit-macro-table", "macro");
}

function renderBanditTable(entries, sel, labelType) {
  const root = $(sel);
  root.innerHTML = "";
  if (!entries.length) {
    root.appendChild(el("p", { className: "empty" }, `No ${labelType} arms yet.`));
    return;
  }
  const tbl = el("table", { className: "bandit" });
  tbl.appendChild(el("thead", {},
    el("tr", {},
      el("th", {}, "arm"),
      el("th", {}, "mean"),
      el("th", {}, "n"),
      el("th", {}, "α"),
      el("th", {}, "β"),
      el("th", { style: "width:120px" }, ""),
    ),
  ));
  const tbody = el("tbody");
  for (const [key, stats] of entries) {
    const label = key.slice(labelType.length + 1);
    const pct = Math.round(stats.mean * 100);
    tbody.appendChild(el("tr", {},
      el("td", {}, el("code", {}, label)),
      el("td", { className: "num" }, stats.mean.toFixed(3)),
      el("td", { className: "num" }, String(Math.round(stats.n))),
      el("td", { className: "num" }, stats.alpha.toFixed(2)),
      el("td", { className: "num" }, stats.beta.toFixed(2)),
      el("td", {},
        el("div", { className: "mean-bar-bg" },
          el("div", { className: "mean-bar", style: `width:${pct}%` }),
        ),
      ),
    ));
  }
  tbl.appendChild(tbody);
  root.appendChild(tbl);
}

// ----- RAG Inspector tab -----

let cardsCache = null;

const CARD_TYPE_LABEL = {
  proof_trace:       "trace",
  failure:           "failure",
  macro:             "macro",
  theorem_property:  "theorem",
  dsl_action:        "dsl",
};

async function loadRAG() {
  cardsCache = await api("/api/cards");
  const typeSel = $("#rag-type-filter");
  const types = [...new Set(cardsCache.map(c => c.card_type))].sort();
  typeSel.innerHTML = '<option value="">all types</option>';
  types.forEach(t => typeSel.appendChild(el("option", { value: t }, t)));
  typeSel.onchange = renderRAG;
  renderRAG();
}

function renderRAG() {
  const fType = $("#rag-type-filter").value;
  const filtered = (cardsCache || []).filter(c => !fType || c.card_type === fType);
  const root = $("#rag-cards");
  root.innerHTML = "";
  if (!filtered.length) {
    root.appendChild(el("p", { className: "empty" }, "No cards found."));
    return;
  }
  for (const card of filtered) {
    const short = CARD_TYPE_LABEL[card.card_type] || card.card_type;
    const item = el("div", { className: "card-item" });

    item.appendChild(el("div", { className: "card-header" },
      el("span", { className: `card-type-badge ct-${card.card_type.replace(/_/g, "-")}` }, short),
      el("span", { className: "card-id" }, card.card_id),
      el("span", { className: "meta" }, card.created_at ? card.created_at.slice(0, 19) : ""),
    ));

    if (card.tags && card.tags.length) {
      const tagBar = el("div", { className: "tag-bar" });
      card.tags.forEach(t => tagBar.appendChild(el("span", { className: "spec-tag" }, t)));
      item.appendChild(tagBar);
    }

    const p = card.payload || {};
    const lines = [];
    if (p.spec)            lines.push(`spec: ${p.spec}`);
    if (p.macro_name)      lines.push(`macro: ${p.macro_name}`);
    if (p.property_name)   lines.push(`property: ${p.property_name}`);
    if (p.lean_statement)  lines.push(`stmt: ${p.lean_statement}`);
    if (p.body_repr)       lines.push(`body: ${p.body_repr}`);
    if (p.error_type)      lines.push(`error: ${p.error_type} — ${p.message || ""}`);
    if (p.name && !p.macro_name) lines.push(`name: ${p.name}`);
    if (p.description)     lines.push(p.description);
    if (lines.length) {
      item.appendChild(el("pre", { className: "card-payload" }, lines.join("\n")));
    }

    root.appendChild(item);
  }
}

// ----- Tab switching -----

function switchTab(name) {
  $$("nav.tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "specs")    loadSpecs();
  if (name === "macros")   loadMacros();
  if (name === "proofs")   loadProofs();
  if (name === "prompts")  loadPrompts();
  if (name === "timeline") loadTimeline();
  if (name === "bandit")   loadBandit();
  if (name === "rag")      loadRAG();
  if (name === "dsl")      loadDSL();
}

document.addEventListener("DOMContentLoaded", () => {
  $$("nav.tabs button").forEach(b => b.onclick = () => switchTab(b.dataset.tab));
  loadStats();
  loadSpecs();
});
