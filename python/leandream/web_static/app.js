"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

// ----- Global run selector with localStorage persistence -----

let currentRun = localStorage.getItem("selectedRunId") || null;

function runParam() {
  return currentRun ? `?run=${encodeURIComponent(currentRun)}` : "";
}

function _updateRunLabel() {
  const lbl = $("#current-run-label");
  if (lbl) lbl.textContent = currentRun ? currentRun.slice(0, 24) : "(latest)";
}

async function initRunSelector() {
  const sel = $("#global-run-select");
  if (!sel) return;
  let runs = [];
  try { runs = await api("/api/runs"); } catch(e) {}
  sel.innerHTML = '<option value="">latest</option>';
  for (const r of runs) {
    const opt = el("option", { value: r }, r.slice(0, 24));
    sel.appendChild(opt);
  }
  // Validate stored run still exists
  if (currentRun && !runs.includes(currentRun)) {
    currentRun = null;
    localStorage.removeItem("selectedRunId");
  }
  sel.value = currentRun || "";
  _updateRunLabel();

  sel.onchange = () => {
    currentRun = sel.value || null;
    if (currentRun) localStorage.setItem("selectedRunId", currentRun);
    else localStorage.removeItem("selectedRunId");
    _updateRunLabel();
    // Reload whichever tab is active so data switches immediately
    const activeTab = $("nav.tabs button.active")?.dataset?.tab;
    if (activeTab) switchTab(activeTab);
  };

  const refreshBtn = $("#refresh-btn");
  if (refreshBtn) {
    refreshBtn.onclick = () => {
      const activeTab = $("nav.tabs button.active")?.dataset?.tab;
      if (activeTab) switchTab(activeTab);
    };
  }
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
  const [macros, banditRaw] = await Promise.all([
    api("/api/macros"),
    api("/api/bandit").catch(() => ({})),
  ]);
  const root = $("#macros-table");
  root.innerHTML = "";
  if (Object.keys(macros).length === 0) {
    root.appendChild(el("p", { className: "empty" }, "No macros installed yet. Run the orchestrator."));
    return;
  }
  // Build macro→bandit lookup
  const banditByMacro = {};
  for (const [k, v] of Object.entries(banditRaw)) {
    if (k.startsWith("macro:")) banditByMacro[k.slice(6)] = v;
  }
  const tbl = el("table", { className: "macros" });
  tbl.appendChild(el("thead", {},
    el("tr", {},
      el("th", {}, "name"),
      el("th", {}, "arity"),
      el("th", {}, "lvl"),
      el("th", {}, "TT"),
      el("th", {}, "support"),
      el("th", {}, "bandit"),
      el("th", {}, "properties"),
      el("th", {}, "info"),
      el("th", {}, "members"),
      el("th", {}, "body"),
    ),
  ));
  const tbody = el("tbody");
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

    // Bandit posterior cell
    const bStats = banditByMacro[name];
    let banditCell;
    if (bStats) {
      const pct = Math.round((bStats.mean ?? 0) * 100);
      const nTrials = Math.round(bStats.n ?? 0);
      const phase = nTrials < 5 ? "explore" : bStats.mean >= 0.5 ? "exploit" : "low";
      const phaseCls = phase === "exploit" ? "badge ok" : phase === "explore" ? "badge iter" : "badge warn";
      banditCell = el("td", {},
        el("span", { className: phaseCls }, phase),
        el("span", { className: "meta", style: "margin-left:4px" },
          ` μ=${(bStats.mean??0).toFixed(2)} n=${nTrials}`),
      );
    } else {
      banditCell = el("td", {}, el("span", { className: "meta" }, "—"));
    }

    tbody.appendChild(el("tr", {},
      el("td", {}, el("code", {}, name)),
      el("td", {}, String(info.arity ?? "?")),
      el("td", {}, macroLevelBadge(info.macro_level)),
      el("td", {}, info.tt_key ? el("code", {}, info.tt_key) : el("span", { className: "meta" }, "—")),
      el("td", {}, el("span", { className: "support-bar" }, String(info.support ?? 0))),
      banditCell,
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
  // Load only this run's attempts when a run is selected; all otherwise
  attemptsCache = await api(`/api/attempts${runParam()}`);
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

  // Pre-select the global run in the timeline filter
  if (currentRun && runs.includes(currentRun)) runSel.value = currentRun;

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

function _banditPhase(stats) {
  const n = Math.round(stats.n ?? 0);
  const mean = stats.mean ?? 0;
  if (n < 5)       return { label: "exploring", cls: "badge iter", why: `only ${n} trial(s) — Thompson is sampling widely` };
  if (mean >= 0.6) return { label: "exploiting", cls: "badge ok",   why: `μ=${mean.toFixed(2)} — high reward arm, selected often` };
  if (mean <= 0.2) return { label: "deprioritised", cls: "badge fail", why: `μ=${mean.toFixed(2)} — low reward, β=${stats.beta?.toFixed(1)} pulls posterior down` };
  return { label: "uncertain", cls: "badge warn", why: `μ=${mean.toFixed(2)}, n=${n} — still gathering evidence` };
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
      el("th", { style: "width:100px" }, ""),
      el("th", {}, "phase / why"),
    ),
  ));
  const tbody = el("tbody");
  for (const [key, stats] of entries) {
    const label = key.slice(labelType.length + 1);
    const pct = Math.round(stats.mean * 100);
    const phase = _banditPhase(stats);
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
      el("td", {},
        el("span", { className: phase.cls }, phase.label),
        el("span", { className: "meta", style: "margin-left:4px;font-size:10px" }, phase.why),
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

// ----- Home tab -----

async function loadHome() {
  const [stats, analysis] = await Promise.all([
    api("/api/stats"),
    api("/api/analysis").catch(() => null),
  ]);

  // Stats grid
  const grid = $("#home-stats-grid");
  grid.innerHTML = "";
  const items = [
    ["Specs", stats.specs, "#f59e0b"],
    ["Proofs", stats.proofs, "#22c55e"],
    ["Macros", stats.macros, "#a855f7"],
    ["Attempts", stats.attempts ?? 0, "#64748b"],
    ["Cards", stats.cards ?? 0, "#0ea5e9"],
    ["Iterations", stats.iterations_seen.length, "#f97316"],
    ["Run ID", currentRun ? currentRun.slice(0,14) : "latest", "#0ea5e9"],
  ];
  for (const [label, n, color] of items) {
    grid.appendChild(el("div", { className: "home-stat-card", style: `border-left: 4px solid ${color}` },
      el("div", { className: "home-stat-num" }, String(n)),
      el("div", { className: "home-stat-label" }, label),
    ));
  }

  // Analysis
  const an = $("#home-analysis");
  an.innerHTML = "";
  if (analysis) {
    const rows = [
      ["Macro usage rate", `${(analysis.macro_usage_rate * 100).toFixed(1)}%`],
      ["Total macro refs", String(analysis.total_macro_references)],
      ["Cross-spec reuse", String(analysis.macro_reuse_count)],
      ["Avg expansion ratio", analysis.avg_compression_ratio ? `${analysis.avg_compression_ratio.toFixed(2)}×` : "—"],
      ["Macro count", String(analysis.macro_count)],
      ["Theorems proven", String(analysis.theorem_count)],
    ];
    const kv = el("div", { className: "kv" });
    for (const [k, v] of rows) {
      kv.appendChild(el("div", { className: "k" }, k));
      kv.appendChild(el("div", { className: "v" }, v));
    }
    an.appendChild(kv);

    if (analysis.macro_call_counts && Object.keys(analysis.macro_call_counts).length) {
      an.appendChild(el("div", { className: "section-label" }, "Macro call counts"));
      const ul = el("ul");
      for (const [name, cnt] of Object.entries(analysis.macro_call_counts).sort((a,b)=>b[1]-a[1])) {
        ul.appendChild(el("li", {}, `${name}: ${cnt} call(s) across ${analysis.specs_per_macro[name] ?? 0} spec(s)`));
      }
      an.appendChild(ul);
    }
  } else {
    an.appendChild(el("p", { className: "empty" }, "No analysis data yet. Run the orchestrator first."));
  }

  const summary = await api(`/api/summary${runParam()}`).catch(() => null);
  if (summary?.recommended_next_action) {
    const recEl = el("div", { className: "home-rec", style: "margin-top:1rem;padding:8px;background:var(--panel-2);border-left:3px solid var(--accent);border-radius:4px;" },
      el("strong", {}, "Recommendation: "),
      el("span", { className: "meta" }, summary.recommended_next_action),
    );
    an.appendChild(recEl);
  }
}

// ----- Curriculum tab -----

const STAGE_COLORS = ["#64748b", "#f59e0b", "#3b82f6", "#a855f7", "#ef4444"];

async function loadCurriculum() {
  const root = $("#curriculum-stages");
  root.innerHTML = '<p class="empty">Loading curriculum…</p>';
  let stages;
  try { stages = await api("/api/curriculum"); }
  catch(err) {
    root.innerHTML = "";
    root.appendChild(el("p", { className: "empty" }, `Curriculum unavailable: ${err.message}`));
    return;
  }
  root.innerHTML = "";
  if (!stages.length) {
    root.appendChild(el("p", { className: "empty" }, "No curriculum data. Run the orchestrator first."));
    return;
  }
  root.appendChild(el("p", { className: "meta", style: "margin-bottom:12px;font-size:11px;color:#888" },
    "Gate status is evaluated against the current registry and all accumulated runs."));
  for (const stage of stages) {
    const gate = stage.gate || {};
    const passed = gate.passed;
    const passIcon = passed === true ? "✓" : passed === false ? "✗" : "?";
    const passCls = passed === true ? "gate-pass" : passed === false ? "gate-fail" : "gate-unknown";
    const color = STAGE_COLORS[stage.index] || "#64748b";

    const specList = stage.specs.length === 1 && stage.specs[0] === "all" ? "all specs" : stage.specs.join(", ");
    const card = el("div", { className: "curriculum-card", style: `border-left: 4px solid ${color}` },
      el("div", { className: "curriculum-header" },
        el("span", { className: `gate-badge ${passCls}` }, passIcon),
        el("strong", {}, `Stage ${stage.index}: ${stage.name.toUpperCase()}`),
      ),
      el("div", { className: "kv" },
        el("div", { className: "k" }, "Specs"),
        el("div", { className: "v" }, specList),
        el("div", { className: "k" }, "Planned iters"),
        el("div", { className: "v" }, String(stage.iterations)),
        el("div", { className: "k" }, "Gate: verify ≥"),
        el("div", { className: "v" }, `${(stage.min_verify_ratio * 100).toFixed(0)}%`),
        el("div", { className: "k" }, "Gate: macros ≥"),
        el("div", { className: "v" }, String(stage.min_macros)),
        el("div", { className: "k" }, "Verified"),
        el("div", { className: "v" }, gate.verify_ratio != null ? `${(gate.verify_ratio * 100).toFixed(0)}%` : "—"),
        el("div", { className: "k" }, "Macros"),
        el("div", { className: "v" }, gate.macro_count != null ? String(gate.macro_count) : "—"),
        el("div", { className: "k" }, "Reason"),
        el("div", { className: "v meta" }, gate.reason || "—"),
      ),
    );
    root.appendChild(card);
  }
}

// ----- Proof Forest Graph tab -----

let forestData = null;
let forestSelected = null;
let _forestPositions = {};
// Node-type visibility toggles (initialised on first loadForest)
let forestFilter = { spec: true, proof: true, failure: true, hole: true, macro: true };

function _buildForestFilterBar() {
  const bar = el("div", { className: "forest-filter-bar" });
  const types = [
    { key: "spec",    label: "Specs",    color: "#f59e0b" },
    { key: "proof",   label: "Proofs",   color: "#22c55e" },
    { key: "failure", label: "Failures", color: "#f85149" },
    { key: "hole",    label: "Holes",    color: "#facc15" },
    { key: "macro",   label: "Macros",   color: "#a855f7" },
  ];
  for (const { key, label, color } of types) {
    const cb = el("input", { type: "checkbox", id: `ff-${key}`, checked: true });
    cb.checked = forestFilter[key];
    cb.onchange = () => { forestFilter[key] = cb.checked; drawForestCanvas(); };
    const lbl = el("label", { for: `ff-${key}`, style: `color:${color}` },
      el("span", { className: "dot", style: `background:${color}` }),
      ` ${label}`
    );
    lbl.prepend(cb);
    bar.appendChild(lbl);
  }
  return bar;
}

async function loadForest() {
  const d = $("#forest-detail");
  if (d) d.innerHTML = '<p class="empty">Loading…</p>';
  // Inject filter bar once — as a sibling BEFORE .forest-split, not inside the grid
  const forestSplit = $(".forest-split");
  if (forestSplit && !forestSplit.previousElementSibling?.classList.contains("forest-filter-bar")) {
    forestSplit.parentNode.insertBefore(_buildForestFilterBar(), forestSplit);
  }
  let resp;
  try {
    resp = await api(`/api/forest-graph${runParam()}`);
  } catch(err) {
    if (d) d.innerHTML = `<p class="empty">Failed to load forest: ${err.message}</p>`;
    const canvas = $("#forest-canvas");
    if (canvas) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#888";
      ctx.font = "13px monospace";
      ctx.fillText(`Forest unavailable: ${err.message}`, 20, 40);
    }
    return;
  }
  forestData = resp;
  // Resize canvas after layout reflow so clientWidth is accurate
  requestAnimationFrame(() => {
    const wrap = $("#forest-canvas-wrap");
    const canvas = $("#forest-canvas");
    if (wrap && canvas) {
      const W = Math.max(600, (wrap.clientWidth || 700) - 8);
      const H = Math.max(440, Math.round(W * 0.62));
      canvas.width = W;
      canvas.height = H;
    }
    drawForestCanvas();
    if (d) d.innerHTML = '<p class="empty">Click a node to inspect it.</p>';
  });
}

function drawForestCanvas() {
  const canvas = $("#forest-canvas");
  if (!canvas || !forestData) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const nodes = forestData.nodes;
  const edges = forestData.edges;
  if (!nodes.length) {
    ctx.fillStyle = "#888";
    ctx.font = "14px monospace";
    ctx.fillText("No data — run the orchestrator first.", 20, 40);
    return;
  }

  const visibleNodes = nodes.filter(n => forestFilter[n.type] !== false);
  const byType = { spec: [], proof: [], macro: [], hole: [], failure: [] };
  visibleNodes.forEach(n => { (byType[n.type] = byType[n.type] || []).push(n); });

  const positions = {};
  const cx = W / 2, cy = H / 2;
  const minDim = Math.min(W, H);
  const specR    = minDim * 0.24;
  const macroR   = minDim * 0.46;
  const clusterR = Math.min(48, specR * 0.42);

  // 1. Spec nodes in inner ring
  byType.spec.forEach((n, i) => {
    const angle = (2 * Math.PI * i / Math.max(byType.spec.length, 1)) - Math.PI / 2;
    positions[n.id] = { x: cx + specR * Math.cos(angle), y: cy + specR * Math.sin(angle) };
  });

  // 2. Proof + failure nodes clustered around their spec (up to 5 most-recent per spec)
  // Merge proofs and failures for clustering
  const proofsBySpec = {};
  for (const n of [...byType.proof, ...byType.failure]) {
    const sid = `spec:${n.spec}`;
    (proofsBySpec[sid] = proofsBySpec[sid] || []).push(n);
  }
  let hiddenProofs = 0;
  for (const [sid, proofs] of Object.entries(proofsBySpec)) {
    const sp = positions[sid];
    if (!sp) continue;
    const sorted = [...proofs].sort((a, b) => (b.iteration || 0) - (a.iteration || 0));
    hiddenProofs += Math.max(0, sorted.length - 5);
    const shown = sorted.slice(0, 5);
    shown.forEach((n, i) => {
      const angle = (2 * Math.PI * i / Math.max(shown.length, 1)) - Math.PI / 2;
      positions[n.id] = { x: sp.x + clusterR * Math.cos(angle), y: sp.y + clusterR * Math.sin(angle) };
    });
  }

  // 3. Macro nodes in outer ring
  byType.macro.forEach((n, i) => {
    const angle = (2 * Math.PI * i / Math.max(byType.macro.length, 1)) - Math.PI / 2;
    positions[n.id] = { x: cx + macroR * Math.cos(angle), y: cy + macroR * Math.sin(angle) };
  });

  // 4. Hole nodes near their spec (max 12 shown, blockers first)
  const sortedHoles = [...byType.hole].sort((a, b) =>
    (a.severity === "blocker" ? 0 : a.severity === "warning" ? 1 : 2) -
    (b.severity === "blocker" ? 0 : b.severity === "warning" ? 1 : 2)
  );
  const hiddenHoles = Math.max(0, sortedHoles.length - 12);
  const holesToShow = sortedHoles.slice(0, 12);
  let unassignedHoleIdx = 0;
  for (const n of holesToShow) {
    const sid = n.spec ? `spec:${n.spec}` : null;
    if (sid && positions[sid]) {
      const sp = positions[sid];
      const baseAngle = Math.atan2(sp.y - cy, sp.x - cx);
      const holeR = specR + clusterR + 18;
      positions[n.id] = {
        x: cx + holeR * Math.cos(baseAngle + 0.25),
        y: cy + holeR * Math.sin(baseAngle + 0.25),
      };
    } else {
      positions[n.id] = { x: 40 + unassignedHoleIdx * 45, y: H - 24 };
      unassignedHoleIdx++;
    }
  }

  _forestPositions = positions;

  // Draw edges (only between positioned nodes)
  ctx.lineWidth = 0.8;
  for (const e of edges) {
    const f = positions[e.from], t = positions[e.to];
    if (!f || !t) continue;
    ctx.beginPath();
    ctx.strokeStyle = e.dashed ? "#666" : "#444";
    if (e.dashed) { ctx.setLineDash([4, 4]); } else { ctx.setLineDash([]); }
    ctx.moveTo(f.x, f.y); ctx.lineTo(t.x, t.y);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  // Draw nodes
  for (const n of visibleNodes) {
    const pos = positions[n.id];
    if (!pos) continue;
    const r = n.type === "spec" ? 18 : n.type === "macro" ? 13 : n.type === "hole" ? 9 : 6;
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = n.id === forestSelected ? "#fff" : (n.color || "#888");
    ctx.fill();
    if (n.id === forestSelected) {
      ctx.strokeStyle = n.color || "#888";
      ctx.lineWidth = 2.5;
      ctx.stroke();
      ctx.lineWidth = 1;
    }
    // Labels for spec and macro nodes only
    if (n.type === "spec" || n.type === "macro") {
      ctx.fillStyle = "#ccc";
      ctx.font = `${n.type === "spec" ? 10 : 9}px monospace`;
      ctx.textAlign = "center";
      const label = (n.label || "").replace(/^macro_(\d+)$/, "m$1").slice(0, 10);
      ctx.fillText(label, pos.x, pos.y + r + 11);
    }
  }

  // Footer legend
  ctx.fillStyle = "#666";
  ctx.font = "9px monospace";
  ctx.textAlign = "left";
  const footer = [];
  if (hiddenProofs > 0) footer.push(`+${hiddenProofs} older proofs hidden (showing 5/spec)`);
  if (hiddenHoles > 0) footer.push(`+${hiddenHoles} holes hidden (showing 12)`);
  if (footer.length) ctx.fillText(footer.join("   "), 8, H - 6);

  // Click handler (with coordinate scaling for HiDPI/CSS scaling)
  canvas.onclick = (evt) => {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const mx = (evt.clientX - rect.left) * scaleX;
    const my = (evt.clientY - rect.top) * scaleY;
    let hit = null;
    for (const n of nodes) {
      const pos = _forestPositions[n.id];
      if (!pos) continue;
      const r = n.type === "spec" ? 18 : n.type === "macro" ? 13 : 10;
      if ((mx - pos.x) ** 2 + (my - pos.y) ** 2 <= r * r) { hit = n; break; }
    }
    forestSelected = hit ? hit.id : null;
    drawForestCanvas();
    renderForestDetail(hit);
  };
}

function renderForestDetail(node) {
  const d = $("#forest-detail");
  d.innerHTML = "";
  if (!node) { d.innerHTML = '<p class="empty">Click a node to inspect it.</p>'; return; }
  d.appendChild(el("h3", {}, `${node.type.toUpperCase()}: ${node.label}`));
  const kv = el("div", { className: "kv" });
  const add = (k, v) => { kv.appendChild(el("div",{className:"k"},k)); kv.appendChild(el("div",{className:"v"},String(v||"—"))); };
  add("ID", node.id);
  add("Type", node.type);
  if (node.spec)        add("Spec", node.spec);
  if (node.arity != null) add("Arity", node.arity);
  if (node.level != null) add("Level", node.level);
  if (node.body)        add("Body", node.body);
  if (node.iteration != null) add("Iteration", node.iteration);
  if (node.elapsed)     add("Elapsed", `${node.elapsed.toFixed(2)}s`);
  if (node.severity)    add("Severity", node.severity);
  if (node.status)      add("Status", node.status);
  if (node.error_type)  add("Error type", node.error_type);
  if (node.proof_mode)  add("Proof mode", node.proof_mode);
  d.appendChild(kv);
}

// ----- Holes tab -----

const HOLE_TYPE_LABELS = {
  hole_never_verified:       "never verified",
  hole_arity_too_high:       "arity too high",
  hole_macro_deps_missing:   "macro deps missing",
  hole_llm_consistently_wrong: "LLM consistently wrong",
  hole_semantic_gap:         "semantic gap",
  hole_prompt:               "prompt hole",
  hole_repair:               "repair hole",
  hole_affine_target:        "affine target",
  hole_nonlinear_product:    "nonlinear product",
  hole_or_like:              "OR-like",
  hole_conditional:          "conditional/mux",
  hole_majority_carry:       "majority/carry",
};

async function loadHoles() {
  const root = $("#holes-list");
  root.innerHTML = '<p class="empty">Loading holes…</p>';
  let resp;
  try {
    resp = await api(`/api/holes${runParam()}`);
  } catch(err) {
    root.innerHTML = "";
    root.appendChild(el("p", { className: "empty" }, `Could not load holes: ${err.message}`));
    return;
  }
  root.innerHTML = "";
  // API returns {holes: [...], message: "..."} or legacy bare array
  const holes = Array.isArray(resp) ? resp : (resp?.holes ?? []);
  const apiMsg = typeof resp === "object" && !Array.isArray(resp) ? resp.message : null;
  if (!holes.length) {
    root.appendChild(el("p", { className: "empty" },
      apiMsg || "No holes detected for this run. Run more iterations to accumulate evidence."));
    return;
  }
  // Group by spec for compact display
  const bySpec = {};
  for (const card of holes) {
    const spec = (card.payload?.specs || [])[0] || "?";
    (bySpec[spec] = bySpec[spec] || []).push(card);
  }
  for (const [spec, cards] of Object.entries(bySpec)) {
    for (const card of cards) {
      const p = card.payload || {};
      const sevCls = p.severity === "blocker" ? "badge fail" : p.severity === "warning" ? "badge warn" : "badge iter";
      const typeLabel = HOLE_TYPE_LABELS[p.hole_type] || p.hole_type || "?";
      const resolveCls = p.status === "resolved" ? "badge ok" : "badge muted-badge";
      const item = el("div", { className: "hole-card" },
        el("div", { className: "hole-header" },
          el("span", { className: sevCls }, p.severity || "?"),
          el("span", { className: "badge muted-badge" }, typeLabel),
          el("strong", {}, (p.specs || []).join(", ") || "?"),
          p.status === "resolved"
            ? el("span", { className: resolveCls, style: "margin-left:auto" }, `resolved by ${p.resolved_by || "?"}`)
            : null,
        ),
        el("div", { className: "kv" },
          el("div",{className:"k"},"Status"),
          el("div",{className:"v"}, p.status || "unresolved"),
          el("div",{className:"k"},"Hole ID"),
          el("div",{className:"v"},el("code",{},p.hole_id||card.card_id)),
          el("div",{className:"k"},"Evidence"),
          el("div",{className:"v"},el("pre",{style:"max-height:120px;overflow:auto;margin:0"},
            JSON.stringify(p.evidence||{},null,2))),
          ...(p.available_macros_at_detection?.length
            ? [el("div",{className:"k"},"Macros at detection"),
               el("div",{className:"v"}, p.available_macros_at_detection.join(", "))]
            : []),
        ),
        p.suggested_existing_repairs?.length
          ? el("div", { className: "meta", style:"margin-top:6px" },
              "Suggested repairs: " + p.suggested_existing_repairs.join(", "))
          : null,
      );
      root.appendChild(item);
    }
  }
}

// ----- Metrics tab -----

async function loadMetrics() {
  const [rows, summary] = await Promise.all([
    api(`/api/metrics${runParam()}`).catch(() => []),
    api(`/api/summary${runParam()}`).catch(() => null),
  ]);

  const sumEl = $("#metrics-summary");
  sumEl.innerHTML = "";
  if (summary) {
    const items = [
      ["Total verified", summary.total_verified, "#22c55e"],
      ["Total attempts", summary.total_attempted, "#64748b"],
      ["Verify rate", `${((summary.overall_verify_rate||0)*100).toFixed(1)}%`, "#0ea5e9"],
      ["Macros", summary.macro_count, "#a855f7"],
      ["Theorems", summary.theorem_count, "#f97316"],
      ["Holes", summary.holes_detected, "#facc15"],
    ];
    for (const [label, n, color] of items) {
      sumEl.appendChild(el("div", { className: "home-stat-card", style: `border-left:4px solid ${color}` },
        el("div", { className: "home-stat-num" }, String(n ?? "—")),
        el("div", { className: "home-stat-label" }, label),
      ));
    }
  }

  const chartEl = $("#metrics-chart");
  chartEl.innerHTML = "";
  if (!rows.length) {
    chartEl.appendChild(el("p", { className: "empty" }, "No metrics.csv yet — run the orchestrator first."));
    return;
  }
  // Simple ASCII-style bar chart for verify_rate
  const maxBar = 30;
  const pre = el("pre", { className: "metrics-chart-pre" });
  pre.textContent = rows.map(r => {
    const rate = parseFloat(r.verify_rate || 0);
    const bar = "█".repeat(Math.round(rate * maxBar));
    const pad = " ".repeat(maxBar - bar.length);
    return `iter ${String(r.iteration).padStart(2)} │${bar}${pad}│ ${(rate*100).toFixed(0).padStart(3)}% `
         + `[macros:${r.new_macros??0} rag:${r.rag_card_count??0}]`;
  }).join("\n");
  chartEl.appendChild(pre);

  // Macro usage rate chart
  const macroRates = rows.filter(r => r.macro_usage_rate != null);
  if (macroRates.length) {
    chartEl.appendChild(el("div", { className: "section-label" }, "Macro usage rate per iteration"));
    const pre2 = el("pre", { className: "metrics-chart-pre" });
    pre2.textContent = macroRates.map(r => {
      const rate = parseFloat(r.macro_usage_rate || 0);
      const bar = "▓".repeat(Math.round(rate * maxBar));
      const pad = " ".repeat(maxBar - bar.length);
      return `iter ${String(r.iteration).padStart(2)} │${bar}${pad}│ ${(rate*100).toFixed(0).padStart(3)}%`;
    }).join("\n");
    chartEl.appendChild(pre2);
  }
}

// ----- Lean Proof Engineering tab -----

async function loadLean() {
  const root_modes = $("#lean-proof-modes");
  const root_macros = $("#lean-macro-theorems");
  const root_gen = $("#lean-theorem-gen");
  if (!root_modes) return;

  let data;
  try { data = await api(`/api/lean-engineering${runParam()}`); }
  catch(err) {
    root_modes.innerHTML = `<p class="empty">Lean engineering data unavailable: ${err.message}</p>`;
    return;
  }

  // --- Proof mode distribution ---
  root_modes.innerHTML = "";
  root_modes.appendChild(el("div", { className: "section-label" }, "Proof mode distribution"));
  const dist = data.proof_mode_distribution || {};
  if (Object.keys(dist).length) {
    const tbl = el("table", { className: "bandit" });
    tbl.appendChild(el("thead", {}, el("tr", {},
      el("th", {}, "proof_mode"), el("th", {}, "count"), el("th", { style: "width:120px" }, "")
    )));
    const tbody = el("tbody");
    const total = Object.values(dist).reduce((a,b)=>a+b,0);
    for (const [mode, cnt] of Object.entries(dist).sort((a,b)=>b[1]-a[1])) {
      const pct = total ? Math.round(cnt/total*100) : 0;
      tbody.appendChild(el("tr", {},
        el("td", {}, el("code", {}, mode)),
        el("td", { className: "num" }, String(cnt)),
        el("td", {}, el("div", { className: "mean-bar-bg" },
          el("div", { className: "mean-bar", style: `width:${pct}%` }))),
      ));
    }
    tbl.appendChild(tbody);
    root_modes.appendChild(tbl);
  } else {
    root_modes.appendChild(el("p", { className: "empty" }, "No proof mode data yet — run the orchestrator."));
  }
  root_modes.appendChild(el("div", { className: "kv", style: "margin-top:8px" },
    el("div",{className:"k"},"Total verified"), el("div",{className:"v"}, String(data.total_verified ?? "—")),
    el("div",{className:"k"},"Theorem cards"), el("div",{className:"v"}, String(data.theorem_cards_total ?? "—")),
    el("div",{className:"k"},"Lean-checked properties"), el("div",{className:"v"}, String(data.lean_checked_properties ?? "—")),
  ));

  // --- Macros with/without Lean theorems ---
  root_macros.innerHTML = "";
  root_macros.appendChild(el("div", { className: "section-label" }, "Macro theorem coverage"));
  const withTheorems = data.macros_with_lean_theorems || [];
  const promptOnly = data.macros_prompt_only || [];
  if (withTheorems.length + promptOnly.length === 0) {
    root_macros.appendChild(el("p", { className: "empty" }, "No macros installed yet."));
  } else {
    const tbl = el("table", { className: "macros" });
    tbl.appendChild(el("thead", {}, el("tr", {},
      el("th", {}, "macro"), el("th", {}, "coverage")
    )));
    const tbody = el("tbody");
    for (const m of withTheorems) {
      tbody.appendChild(el("tr", {},
        el("td", {}, el("code", {}, m)),
        el("td", {}, el("span", { className: "badge ok" }, "lean_theorem_checked")),
      ));
    }
    for (const m of promptOnly) {
      tbody.appendChild(el("tr", {},
        el("td", {}, el("code", {}, m)),
        el("td", {}, el("span", { className: "badge warn" }, "prompt_only")),
      ));
    }
    tbl.appendChild(tbody);
    root_macros.appendChild(tbl);
  }

  // --- Theorem generation results ---
  root_gen.innerHTML = "";
  root_gen.appendChild(el("div", { className: "section-label" }, "Generated theorem attempts"));
  const genResults = data.theorem_gen_results || [];
  if (!genResults.length) {
    root_gen.appendChild(el("p", { className: "empty" },
      "No theorem generation results yet. Run: leandream-theorem-gen"));
  } else {
    const proved = genResults.filter(r => r.status === "proved");
    const failed = genResults.filter(r => r.status !== "proved");
    root_gen.appendChild(el("p", { className: "meta" },
      `${proved.length} proved · ${failed.length} failed`));
    const tbl = el("table", { className: "timeline" });
    tbl.appendChild(el("thead", {}, el("tr", {},
      el("th", {}, "macro"), el("th", {}, "property"), el("th", {}, "status")
    )));
    const tbody = el("tbody");
    for (const r of genResults) {
      tbody.appendChild(el("tr", {},
        el("td", {}, el("code", {}, r.macro || "?")),
        el("td", {}, r.property || "?"),
        el("td", {}, el("span", { className: `badge ${r.status === "proved" ? "ok" : "fail"}` }, r.status || "?")),
      ));
    }
    tbl.appendChild(tbody);
    root_gen.appendChild(tbl);
  }
}

// ----- Tab switching -----

function switchTab(name) {
  $$("nav.tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "home")       loadHome();
  if (name === "curriculum") loadCurriculum();
  if (name === "specs")      loadSpecs();
  if (name === "macros")     loadMacros();
  if (name === "forest")     loadForest();
  if (name === "holes")      loadHoles();
  if (name === "prompts")    loadPrompts();
  if (name === "timeline")   loadTimeline();
  if (name === "bandit")     loadBandit();
  if (name === "rag")        loadRAG();
  if (name === "metrics")    loadMetrics();
  if (name === "lean")       loadLean();
  if (name === "dsl")        loadDSL();
}

document.addEventListener("DOMContentLoaded", async () => {
  $$("nav.tabs button").forEach(b => b.onclick = () => switchTab(b.dataset.tab));
  await initRunSelector();
  loadStats();
  loadHome();
});
