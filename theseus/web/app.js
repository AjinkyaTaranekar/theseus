"use strict";
// The Try-it page: pick a preset, POST /try/<preset>, draw the AnalysisResult. Every string in a result comes
// from a file or a model, so it only ever goes into the page as text, never as markup.

const $ = (id) => document.getElementById(id);
const buttons = [...document.querySelectorAll(".preset")];
let busy = false;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function clear(node) {
  node.replaceChildren();
}

// "user:priya-intern" -> "priya-intern"; "s3://bucket/key/" -> "bucket/key"
function name(id) {
  return id.replace(/^[a-z0-9_-]+:(\/\/)?/i, "").replace(/\/$/, "");
}

// The classes the comment shades and ranks first (agent/render.py: SENSITIVE_RANK).
const SENSITIVE = { regulated: "high", confidential: "mid" };

function pill(text, kind) {
  return el("span", `pill ${kind}`, text);
}

function status(text, isError) {
  const node = $("status");
  node.textContent = text;
  node.className = isError ? "status error" : "status";
}

function verb(step) {
  if (step.grants && step.grants.length) return `can ${step.grants.join(" and ")}`;
  return step.type.toLowerCase().replaceAll("_", " ");
}

function evidenceText(result, id) {
  const ev = result.evidence[id];
  if (!ev || ev.file === "unknown") return "unknown";
  return ev.line ? `${ev.file}:${ev.line}` : ev.file;
}

// Mermaid label text: quotes and angle brackets would end the label or start markup.
function label(text) {
  const escapes = { '"': "#quot;", "`": "#96;", "<": "#lt;", ">": "#gt;" };
  return [...text.replace(/\s+/g, " ")].map((c) => escapes[c] || c).join("");
}

function definition(path) {
  const ids = new Map();
  for (const step of path.steps) {
    for (const node of [step.from, step.to]) if (!ids.has(node)) ids.set(node, `n${ids.size + 1}`);
  }
  const lines = ["flowchart LR"];
  for (const [node, id] of ids) lines.push(`  ${id}["${label(name(node))}"]`);
  for (const step of path.steps) {
    lines.push(`  ${ids.get(step.from)} -->|"${label(verb(step))}"| ${ids.get(step.to)}`);
  }
  if (SENSITIVE[path.sensitivity]) {
    lines.push("  classDef sensitive fill:#ffebe9,stroke:#cf222e,color:#1f2328");
    lines.push(`  class ${ids.get(path.target)} sensitive`);
  }
  return lines.join("\n");
}

async function draw(box, path) {
  box.textContent = definition(path);
  try {
    await mermaid.run({ nodes: [box], suppressErrors: false });
  } catch (e) {
    console.error("diagram failed", e);
    box.className = "empty";
    box.textContent = "The diagram could not be drawn; the steps below say the same.";
  }
}

function renderPaths(result) {
  const host = $("paths");
  clear(host);
  const beyond = result.use_beyond_intent || [];
  $("paths-empty").hidden = result.opened.length > 0 || beyond.length > 0;
  // No new path, but the code now reads data the PR doesn't mention: show that, with its line.
  for (const use of beyond) {
    const section = el("div", "path");
    const title = el("h3");
    title.append(el("span", "", `${name(use.workload)}'s code now reads ${name(use.resource)}`));
    title.append(pill("not in the PR", "high"));
    section.append(title);
    const why = el("p", "", `The access was there before; the PR's code starts using it at `);
    why.append(el("code", "", `${use.file}:${use.line}`));
    why.append(document.createTextNode(". The PR says nothing about it, so the merge is blocked."));
    section.append(why);
    host.append(section);
  }
  for (const path of result.opened) {
    const section = el("div", "path");
    const title = el("h3");
    title.append(el("span", "", `${name(path.actor)} → ${name(path.target)}`));
    if (path.sensitivity) title.append(pill(path.sensitivity, SENSITIVE[path.sensitivity] || "plain"));
    if (path.unknown) title.append(pill("unknown", "mid"));
    if (path.inferred) title.append(pill("inferred", "plain"));
    section.append(title);
    if (typeof mermaid !== "undefined") {
      const box = el("div", "diagram");
      section.append(box);
      host.append(section);
      draw(box, path);
    } else {
      host.append(section);
    }
    const steps = el("ol", "steps");
    for (const step of path.steps) {
      const item = el("li", "", `${name(step.from)} ${verb(step)} ${name(step.to)}, at `);
      item.append(el("code", "", evidenceText(result, step.evidence)));
      steps.append(item);
    }
    section.append(steps);
  }
}

function table(headers, rows) {
  const wrap = el("div", "scroll");
  const t = el("table");
  const head = el("tr");
  for (const h of headers) head.append(el("th", "", h));
  t.append(head);
  for (const row of rows) {
    const tr = el("tr");
    for (const cell of row) {
      const td = el("td");
      if (cell instanceof Node) td.append(cell);
      else td.textContent = cell;
      tr.append(td);
    }
    t.append(tr);
  }
  wrap.append(t);
  return wrap;
}

const VERDICT = { pass: "ok", fail: "high", invalid: "high", unknown: "mid" };
const VERDICT_WORDS = { pass: "passes", fail: "doesn't pass", invalid: "can't be applied", unknown: "couldn't be checked" };

function renderFixes(result) {
  const host = $("fixes");
  clear(host);
  $("fixes-empty").hidden = result.candidates.length > 0;
  if (!result.candidates.length) return;
  const rows = result.candidates.map((c) => {
    const what = el("span", "", c.title);
    if (c.recommended) what.append(document.createTextNode(" "), pill("recommended", "ok"));
    return [what, pill(VERDICT_WORDS[c.verdict] || c.verdict, VERDICT[c.verdict] || "plain"), c.reason];
  });
  host.append(table(["What the fix does", "Tested on a graph copy", "Why"], rows));
}

function renderTrace(result) {
  const host = $("trace");
  clear(host);
  $("trace-empty").hidden = result.tool_trace.length > 0;
  if (!result.tool_trace.length) return;
  host.append(table(["Tool", "Result", "ms"], result.tool_trace.map((c) => [c.tool, c.summary, String(c.ms)])));
}

function renderCoverage(result) {
  const host = $("coverage");
  clear(host);
  const c = result.coverage;
  const skipped = Object.entries(c.skipped_types).sort(([a], [b]) => a.localeCompare(b));
  const facts = [
    ["Resources", `${c.modeled} modeled of ${c.resources}`],
    ["Graph", `${c.nodes} nodes, ${c.edges} edges`],
    ["Skipped types", skipped.length ? skipped.map(([k, n]) => `${k} (${n})`).join(", ") : "none"],
    ["Code calls skipped", String(c.code_calls_skipped)],
    ["Unknowns", result.unknowns.length ? result.unknowns.join(", ") : "none"],
  ];
  const list = el("dl", "facts");
  for (const [term, detail] of facts) {
    list.append(el("dt", "", term), el("dd", "", detail));
  }
  host.append(list);
}

function renderResult(result) {
  $("headline").textContent = result.headline;
  const t = result.timings;
  const models = Object.values(result.models || {});
  $("meta").textContent =
    `Analyzed in ${t.total_ms} ms (engine ${t.engine_ms} ms). ` +
    (models.length ? `Models, replayed: ${[...new Set(models)].join(", ")}.` : "Models replayed from recordings.");
  renderPaths(result);
  renderFixes(result);
  renderTrace(result);
  renderCoverage(result);
  $("result").hidden = false;
}

async function failure(res) {
  if (res.status === 429) {
    const wait = res.headers.get("Retry-After");
    return `That is ten tries a minute. Try again${wait ? ` in ${wait} seconds` : " shortly"}.`;
  }
  if (res.status === 503) return "The engine is not ready. Try again in a moment.";
  return "The engine could not analyze that one. Try another preset.";
}

async function run(button) {
  if (busy) return;
  busy = true;
  for (const b of buttons) {
    b.disabled = true;
    b.setAttribute("aria-pressed", String(b === button));
  }
  status("Planning both commits and tracing paths in FalkorDB…");
  try {
    const res = await fetch(`/try/${encodeURIComponent(button.dataset.preset)}`, { method: "POST" });
    if (!res.ok) {
      status(await failure(res), true);
      return;
    }
    renderResult(await res.json());
    status("");
  } catch (e) {
    console.error("try failed", e);
    status("Could not reach the server. Check your connection and try again.", true);
  } finally {
    busy = false;
    for (const b of buttons) b.disabled = false;
  }
}

if (typeof mermaid !== "undefined") {
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" });
}
for (const button of buttons) button.addEventListener("click", () => run(button));

// The front page's terminal types its lines once it scrolls into view. Without script, or with reduced
// motion, every line is simply there.
const term = document.querySelector(".term");
if (term && "IntersectionObserver" in window && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  term.classList.add("armed");
  const seen = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) {
      term.classList.add("play");
      seen.disconnect();
    }
  }, { threshold: 0.35 });
  seen.observe(term);
}
