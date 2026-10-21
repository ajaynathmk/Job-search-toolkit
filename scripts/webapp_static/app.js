/* Job tracker interface. Design brief and research: docs/OPERATING.md.
   Plain JavaScript, no build step. Reads the existing API; every write goes through scripts/db.py on the server. */
"use strict";

// ---------------------------------------------------------------- helpers
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const store = {get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
               set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage may be blocked */ } }};

const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', x: '<path d="M18 6 6 18M6 6l12 12"/>', check: '<path d="m5 12 5 5L20 7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', alert: '<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/>',
  send: '<path d="M22 2 11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>', calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  today: '<path d="M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1V11z"/>', jobs: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18"/>',
  thesis: '<path d="m2 9 10-5 10 5-10 5L2 9z"/><path d="M6 11v5c3 2 9 2 12 0v-5"/>', inbox: '<path d="M3 13l3-8h12l3 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6z"/><path d="M3 13h5l1 3h6l1-3h5"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  board: '<rect x="3" y="3" width="6" height="18" rx="1.5"/><rect x="11" y="3" width="6" height="11" rx="1.5"/>', table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>', ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  folder: '<path d="M3 6a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6z"/>', chev: '<path d="m9 6 6 6-6 6"/>', down: '<path d="m6 9 6 6 6-6"/>', up: '<path d="m6 15 6-6 6 6"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>', circle: '<circle cx="12" cy="12" r="8"/>', ban: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.7 7L3 21l2-5.5A8 8 0 1 1 21 12z"/>', archive: '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4"/>',
  xcircle: '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>', rows: '<path d="M3 6h18M3 12h18M3 18h18"/>', link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>', copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
};
const icon = (n, c = "") => `<svg class="i ${c}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ""}</svg>`;

const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const dayDiff = iso => iso ? Math.round((Date.parse(String(iso).slice(0, 10) + "T00:00:00") - Date.parse(todayISO() + "T00:00:00")) / 864e5) : null;
const fmtDate = iso => { if (!iso) return ""; const d = new Date(String(iso).slice(0, 10) + "T00:00:00"); return isNaN(d) ? esc(iso) : d.toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric"}); };
function due(iso) {
  const n = dayDiff(iso);
  if (n === null || isNaN(n)) return {html: '<span class="due none">No deadline</span>', n: null};
  let text, cls;
  if (n < 0) { text = n === -1 ? "Yesterday" : `${-n} days ago`; cls = "over"; } else if (n === 0) { text = "Today"; cls = "urgent"; } else if (n === 1) { text = "Tomorrow"; cls = "urgent"; }
  else if (n <= 7) { text = `in ${n} days`; cls = "soon"; } else { text = `in ${n} days`; cls = ""; }
  return {html: `<span class="due ${cls}" title="${esc(fmtDate(iso))}">${text}</span>`, n};
}
function ago(iso) {
  const n = dayDiff(iso); if (n === null) return "";
  if (n === 0) return "Today"; if (n === -1) return "Yesterday"; if (n > -14 && n < 0) return `${-n}d ago`; return fmtDate(iso);
}

// ---------------------------------------------------------------- the stage model (docs/OPERATING.md)
let DEFS = null;
async function loadDefs() { try { DEFS = await api("/api/definitions"); } catch (e) { DEFS = null; } if (DEFS) { CATEGORY = DEFS.category_labels; SUBFIELD = DEFS.subfield_labels; ROUTES = Object.assign({none_found: "No legal route found", unknown: "Route not assessed"}, DEFS.route_labels || {}); KIND = Object.assign({other: "Other"}, DEFS.kind_labels || {}); PILLARS = Object.assign({other: "Other"}, DEFS.pillar_labels || {}); } }
const verdictMeta = v => (DEFS && DEFS.verdict_meta[v]) || null;
const verdictBadge = v => { const m = verdictMeta(v); return m ? `<span class="badge ${m.tone}" title="${esc((DEFS.verdict_help || {})[v] || "")}">${esc(m.label)}</span>` : '<span class="badge plain">Not analysed</span>'; };
const levelLabel = l => (DEFS && DEFS.analysis_levels[l]) || l || "";
const STAGES = {
  candidate: {label: "Not analysed",  tone: "plain",   icon: "clock",   dot: "var(--text-3)"},
  review:    {label: "Open",           tone: "accent",  icon: "circle",  dot: "var(--accent)"},
  queued:    {label: "In progress",   tone: "warning", icon: "clock",   dot: "var(--warning)"},
  ready:     {label: "Ready to send", tone: "success", icon: "check",   dot: "var(--success)"},
  blocked:   {label: "Blocked",       tone: "danger",  icon: "ban",     dot: "var(--danger)"},
  applied:   {label: "Applied",       tone: "info",    icon: "send",    dot: "var(--info)"},
  interview: {label: "Interview",     tone: "violet",  icon: "chat",    dot: "var(--violet)"},
  declined:  {label: "Declined",      tone: "",        icon: "xcircle", dot: "var(--text-3)"},
  closed:    {label: "Closed",        tone: "",        icon: "archive", dot: "var(--text-3)"},
};
function stageOf(j) {
  if (DEFS) {
    for (const r of DEFS.stage_rules) { let ok = true; for (const [k, want] of Object.entries(r.when)) { const v = j[k]; ok = ok && (want === "set" ? !!v : want.includes(v)); } if (ok) return r.stage; }
    return "review";
  }
  if (j.status === "applied") return "applied"; if (j.status === "interview") return "interview";
  if (j.status === "rejected") return j.applied_at ? "declined" : "closed"; if (j.status === "skip") return "closed";
  if (j.approval === "blocked") return "blocked"; if (j.approval === "prepared") return "ready"; if (j.approval === "requested" || j.approval === "recheck") return "queued";
  return "review";
}
const stageBadge = s => { const m = STAGES[s] || STAGES.review; return `<span class="badge ${m.tone}">${icon(m.icon, "sm")}${m.label}</span>`; };
const ACTIVE = ["review", "queued", "ready"];
let ROUTES = {none_found: "No legal route found", unknown: "Route not assessed"};

// ---------------------------------------------------------------- state
const S = {
  jobs: [], thesis: [], watch: {items: [], runs: []}, loaded: false, live: true,
  route: "today", seg: "best", q: "", view: store.get("view", "table"), density: store.get("density", "comfortable"),
  filters: {verdict: new Set(), category: new Set(), tier: new Set(), country: new Set(), field: new Set(), source: new Set()}, sort: null, shown: 100,
  sel: null, thesisSeg: "all", inbox: {kind: "all", origin: "all", onPillar: true, days: 7, hideDismissed: true}, dismissed: new Set(store.get("dismissed", [])), undo: null,
  theme: store.get("theme", null),
};
const byId = id => S.jobs.find(j => j.id === id);
const thById = id => S.thesis.find(t => t.id === id);

// ---------------------------------------------------------------- data
async function api(url, method = "GET", body = null) {
  const o = {method, headers: {}}; if (body !== null) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
  const r = await fetch(url, o); let d = null; try { d = await r.json(); } catch (e) { d = {error: "unexpected reply"}; } if (!r.ok && !d.error) d.error = "failed (" + r.status + ")"; d._ok = r.ok; return d;
}
async function load(initial = false) {
  if (!initial && (document.hidden || document.activeElement && ["TEXTAREA", "INPUT"].includes(document.activeElement.tagName))) return;
  try {
    if (!DEFS) await loadDefs();
    const [jobs, thesis, mail] = await Promise.all([api("/api/jobs"), api("/api/thesis"), api("/api/mail")]);
    if (mail && Array.isArray(mail.act_now)) S.mail = mail;
    if (!Array.isArray(jobs)) throw new Error("jobs");
    S.jobs = jobs; S.thesis = Array.isArray(thesis) ? thesis : [];
    S.loaded = true; S.live = true; if (S.route === "pipeline") { try { S.pipeline = await api("/api/pipeline"); } catch (e) { /* keep the last copy */ } }
  } catch (e) { S.live = false; }
  render();
}

// ---------------------------------------------------------------- routing (state lives in the URL hash)
function readHash() {
  const raw = location.hash.replace(/^#\/?/, ""); const [path, qs] = raw.split("?"); const p = new URLSearchParams(qs || "");
  let route = path || "";
  if (!route) route = ({"/thesis": "thesis", "/watch": "review", "/inbox": "review", "/review": "review", "/mail": "mail", "/pipeline": "pipeline"})[location.pathname] || "today";
  if (route === "inbox") route = "review";
  if (!["today", "jobs", "thesis", "review", "mail", "pipeline"].includes(route)) route = "today";
  S.route = route;
  if (route === "jobs") {
    S.seg = p.get("seg") || "best"; S.q = p.get("q") || ""; S.view = p.get("view") || S.view;
    for (const k of Object.keys(S.filters)) S.filters[k] = new Set((p.get(k) || "").split(",").filter(Boolean));
    S.sort = p.get("sort") ? {key: p.get("sort").split(":")[0], dir: p.get("sort").split(":")[1] || "desc"} : null;
  }
}
function writeHash() {
  let h = "#/" + S.route;
  if (S.route === "jobs") {
    const p = new URLSearchParams();
    if (S.seg !== "best") p.set("seg", S.seg); if (S.q) p.set("q", S.q); if (S.view !== "table") p.set("view", S.view);
    for (const [k, v] of Object.entries(S.filters)) if (v.size) p.set(k, [...v].join(","));
    if (S.sort) p.set("sort", S.sort.key + ":" + S.sort.dir);
    const s = p.toString(); if (s) h += "?" + s;
  }
  if (location.hash !== h) history.replaceState(null, "", location.pathname.replace(/^\/(thesis|watch|pipeline|review|inbox)$/, "/") + h);
}
function go(route, params = {}) {
  S.route = route;
  if (route === "jobs") { S.seg = params.seg || "best"; S.q = params.q || ""; S.filters = {verdict: new Set(), category: new Set(), tier: new Set(), country: new Set(), field: new Set(), source: new Set()}; S.sort = null; S.shown = 100; }
  closeDrawer(true); writeHash(); render(); window.scrollTo(0, 0); $(".side")?.classList.remove("open");
}

// ---------------------------------------------------------------- jobs: filtering and sorting
const BEST = j => DEFS ? DEFS.best_fit_verdicts.includes(j.verdict) : ["APPLY", "BACKUP", "PLAN", "LATER"].includes(j.verdict);
const OPENSTAGE = s => ["review", "queued", "ready"].includes(s);
const SEGS = [
  {k: "best", label: "Best fits", f: (s, j) => OPENSTAGE(s) && BEST(j)}, {k: "queued", label: "In progress", f: s => s === "queued"},
  {k: "ready", label: "Ready to send", f: s => s === "ready"}, {k: "applied", label: "Applied", f: s => s === "applied"},
  {k: "interview", label: "Interview", f: s => s === "interview"}, {k: "blocked", label: "Blocked", f: (s, j) => s === "blocked" || j.verdict === "BLOCKED"},
  {k: "notfit", label: "Not a fit", f: (s, j) => (OPENSTAGE(s) || s === "blocked") && ["PASS", "EXPIRED"].includes(j.verdict)},
  {k: "candidate", label: "Not analysed", f: s => s === "candidate"}, {k: "closed", label: "Closed", f: s => s === "declined" || s === "closed"}, {k: "all", label: "All", f: () => true},
];
let CATEGORY = {};
let SUBFIELD = {};
const FILTERS = {verdict: {label: "Verdict", get: j => (verdictMeta(j.verdict) || {label: "Not analysed"}).label}, category: {label: "Category", get: j => CATEGORY[j.category] || "Not categorised"}, tier: {label: "Tier", get: j => j.tier ? "Tier " + j.tier : "Long shot"}, country: {label: "Country", get: j => j.country || "?"},
                  field: {label: "Field", get: j => j.field || "unclassified"}, source: {label: "Source", get: j => (j.source || "?").replace(/_/g, " ")}};
function matchQuery(j, q) {
  if (!q) return true; const hay = [j.title, j.employer, j.location, j.field, j.track, j.source, j.country, j.notes, j.my_notes, j.jd_summary].join(" ").toLowerCase();
  return q.toLowerCase().split(/\s+/).every(w => hay.includes(w));
}
function passes(j, skipSeg) {
  if (!matchQuery(j, S.q)) return false;
  for (const [k, set] of Object.entries(S.filters)) if (set.size && !set.has(FILTERS[k].get(j))) return false;
  return skipSeg || SEGS.find(s => s.k === S.seg).f(stageOf(j), j);
}
function defaultSort(seg) { return ({best: {key: "verdict", dir: "asc"}, notfit: {key: "score", dir: "desc"}, applied: {key: "applied", dir: "desc"}, interview: {key: "updated", dir: "desc"}, closed: {key: "updated", dir: "desc"}, ready: {key: "deadline", dir: "asc"}, queued: {key: "deadline", dir: "asc"}})[seg] || {key: "score", dir: "desc"}; }
function sortVal(j, k) {
  switch (k) {
    case "verdict": { const m = verdictMeta(j.verdict); return (m ? m.rank : 9) * 100 - (j.score || 0); } case "score": return j.score == null ? -1 : j.score; case "deadline": return j.deadline || "9999"; case "found": return j.date_found || ""; case "applied": return j.applied_at || "";
    case "updated": return j.updated_at || ""; case "role": return (j.title || "").toLowerCase(); case "stage": return stageOf(j); default: return "";
  }
}
function jobsView() {
  const s = S.sort || defaultSort(S.seg); const dir = s.dir === "asc" ? 1 : -1;
  return S.jobs.filter(j => passes(j)).sort((a, b) => { const x = sortVal(a, s.key), y = sortVal(b, s.key); if (x < y) return -dir; if (x > y) return dir; return (b.score || 0) - (a.score || 0) || (b.date_found || "").localeCompare(a.date_found || ""); });
}
const countBy = (arr, fn) => arr.reduce((m, x) => { const k = fn(x); m[k] = (m[k] || 0) + 1; return m; }, {});

// ---------------------------------------------------------------- actions (all through one write path, each with undo)
const TODAY_FIELDS = ["status", "approval", "applied_at", "closed_at", "approved_at", "recheck_at"];
const ACTIONS = {
  approve: () => ({approval: "requested", approved_at: todayISO()}), recheck: () => ({approval: "recheck", recheck_at: todayISO()}),
  skip: () => ({status: "skip"}), close: () => ({status: "rejected", approval: "none", closed_at: todayISO()}),
  applied: d => ({status: "applied", applied_at: d || todayISO()}), interview: () => ({status: "interview"}),
  declined: () => ({status: "rejected", closed_at: todayISO()}), reopen: () => ({status: "open", approval: "none", applied_at: null, closed_at: null}),
};
const LABELS = {approve: "Approved", recheck: "Marked for recheck", skip: "Marked not for me", close: "Closed", applied: "Marked applied", interview: "Marked interview", declined: "Marked declined", reopen: "Reopened"};
async function act(id, name, arg) {
  const j = byId(id); if (!j) return; const changes = ACTIONS[name](arg); const prev = {}; for (const k of Object.keys(changes)) prev[k] = j[k] == null ? null : j[k];
  const r = await api(`/api/jobs/${encodeURIComponent(id)}/set`, "POST", changes);
  if (r.error) return toast("Could not save: " + r.error);
  Object.assign(j, r); S.undo = {id, prev}; toast(`${LABELS[name]}: ${j.title}`, true); render();
}
async function undo() {
  if (!S.undo) return; const {id, prev} = S.undo; S.undo = null; const r = await api(`/api/jobs/${encodeURIComponent(id)}/set`, "POST", prev);
  if (!r.error) { Object.assign(byId(id), r); toast("Undone"); render(); }
}
let toastTimer = null;
function toast(text, withUndo = false) {
  const t = $("#toast"); t.innerHTML = `<span>${esc(text)}</span>${withUndo ? '<button data-act="undo">Undo</button>' : ""}`; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), withUndo ? 6000 : 2600);
}

// ---------------------------------------------------------------- shared fragments
function scoreCell(n) {
  if (n == null) return '<span class="muted">-</span>'; const cls = n >= 7 ? "hi" : n >= 4 ? "mid" : "";
  return `<span class="score ${cls}" title="Score ${n} of 10"><span class="score-num">${n}</span><span class="score-bar"><i style="width:${n * 10}%"></i></span></span>`;
}
const roleCell = j => `<div class="role"><b title="${esc(j.title)}">${esc(j.title)}</b><span>${esc(j.employer)}${j.location ? " · " + esc(j.location) : ""}</span></div>`;
const emptyState = (t, s) => `<div class="empty"><b>${esc(t)}</b>${esc(s || "")}</div>`;

// ---------------------------------------------------------------- pages
function pgToday() {
  const st = countBy(S.jobs, stageOf); const n = k => st[k] || 0;
  const open = S.jobs.filter(j => ["review", "queued", "ready"].includes(stageOf(j)) && j.deadline);
  const dl = open.map(j => ({j, d: dayDiff(j.deadline)})).filter(x => x.d !== null && x.d >= -7 && x.d <= 21).sort((a, b) => a.d - b.d);
  const week = dl.filter(x => x.d >= 0 && x.d <= 7).length;
  const best = S.jobs.filter(j => stageOf(j) === "review" && BEST(j)).sort((a, b) => (verdictMeta(a.verdict).rank - verdictMeta(b.verdict).rank) || (b.score || 0) - (a.score || 0)).slice(0, 6);
  const inbox = reviewQueue();
  const pipe = ["review", "queued", "ready", "applied", "interview"]; const total = pipe.reduce((s, k) => s + n(k), 0) || 1;
  const tStat = countBy(S.thesis, t => t.status);
  return `
  <div class="stat-row">
    <button class="stat" data-go="jobs" data-seg="best"><div class="big">${S.jobs.filter(j => OPENSTAGE(stageOf(j)) && BEST(j)).length}</div><div class="lbl">Best fits</div><div class="hint">${S.jobs.filter(j => OPENSTAGE(stageOf(j)) && j.verdict === "APPLY").length} to apply to first</div></button>
    <button class="stat" data-go="jobs" data-seg="ready"><div class="big">${n("ready")}</div><div class="lbl">Ready to send</div><div class="hint">${S.jobs.filter(j => stageOf(j) === "ready" && ["PASS", "BLOCKED", "EXPIRED"].includes(j.verdict)).length} of them are not a fit</div></button>
    <button class="stat" data-go="jobs" data-seg="applied"><div class="big">${n("applied") + n("interview")}</div><div class="lbl">Applied</div><div class="hint">${n("interview")} in interview</div></button>
    <button class="stat" data-go="jobs" data-seg="all" data-sort="deadline:asc"><div class="big">${week}</div><div class="lbl">Deadlines this week</div><div class="hint">${dl.length} in the next 3 weeks</div></button>
  </div>
  <div class="grid-2"><div>
    <section class="panel"><header>${icon("calendar")}<h2>Upcoming deadlines</h2><a class="link" href="#/jobs?seg=all&sort=deadline:asc">All roles by deadline</a></header>
      ${dl.length ? dl.slice(0, 8).map(x => `<div class="list-row" data-open="job" data-id="${esc(x.j.id)}">${scoreCell(x.j.score)}<div class="role"><b>${esc(x.j.title)}</b><span>${esc(x.j.employer)}</span></div>${stageBadge(stageOf(x.j))}${due(x.j.deadline).html}</div>`).join("") : emptyState("No deadlines in the next three weeks", "Roles with an application deadline appear here, soonest first.")}
    </section>
    <section class="panel"><header>${icon("circle")}<h2>Best matches to review</h2><a class="link" href="#/jobs">All best fits</a></header>
      ${best.length ? best.map(j => `<div class="list-row" data-open="job" data-id="${esc(j.id)}">${scoreCell(j.score)}<div class="role"><b>${esc(j.title)}</b><span>${esc(j.employer)}${j.location ? " · " + esc(j.location) : ""}</span></div>${due(j.deadline).n !== null ? due(j.deadline).html : ""}<button class="btn sm" data-act="approve" data-id="${esc(j.id)}">Approve</button><button class="btn sm ghost" data-act="skip" data-id="${esc(j.id)}" title="Not for me">${icon("x", "sm")}</button></div>`).join("") : emptyState("Nothing to review", "New roles from the daily run land here.")}
    </section></div>
  <div>
    <section class="panel"><header>${icon("jobs")}<h2>Pipeline</h2></header><div class="funnel">
      <div class="funnel-bar" role="img" aria-label="Pipeline: ${pipe.map(k => n(k) + " " + STAGES[k].label).join(", ")}">${pipe.map(k => n(k) ? `<i style="flex:${n(k) / total * 100};background:${STAGES[k].dot}" title="${STAGES[k].label}: ${n(k)}"></i>` : "").join("")}</div>
      <div class="funnel-legend">${pipe.map(k => `<button data-go="jobs" data-seg="${k}"><span class="dot" style="background:${STAGES[k].dot}"></span>${STAGES[k].label}<span class="n">${n(k)}</span></button>`).join("")}
        <button data-go="jobs" data-seg="closed"><span class="dot" style="background:var(--text-3)"></span><span class="muted">Declined or closed</span><span class="n muted">${n("declined") + n("closed")}</span></button>
        ${n("blocked") ? `<button data-go="jobs" data-seg="blocked"><span class="dot" style="background:var(--danger)"></span><span class="muted">Blocked (a wall in the posting)</span><span class="n muted">${n("blocked")}</span></button>` : ""}</div></div></section>
    <section class="panel"><header>${icon("inbox")}<h2>To confirm against your CV</h2><a class="link" href="#/review">${inbox.length} waiting</a></header>
      ${inbox.length ? inbox.slice(0, 4).map(i => `<div class="list-row" data-open="${i._kind}" data-id="${esc(i.id)}">${scoreCell(i.score)}<div class="role"><b>${esc(i.title)}</b><span>${esc(i.employer || "")}</span></div>${verdictBadge(i.verdict)}</div>`).join("") : emptyState("Nothing to confirm", "Every best fit has been read against your CV.")}
    </section>
    <section class="panel"><header>${icon("thesis")}<h2>Thesis</h2><a class="link" href="#/thesis">${S.thesis.length} leads</a></header>
      ${S.thesis.length ? S.thesis.slice(0, 4).map(t => `<div class="list-row" data-open="thesis" data-id="${esc(t.id)}">${scoreCell(t.score)}<div class="role"><b>${esc(t.title)}</b><span>${esc(t.institution)}</span></div><span class="badge plain">${esc(TSTATUS[t.status] || t.status)}</span></div>`).join("") : emptyState("No thesis leads yet")}
      ${tStat.lead ? `<div class="list-row muted" style="cursor:default">${tStat.lead} still to approach: the best next step is a short email to the group.</div>` : ""}
    </section></div></div>`;
}

function chipMenus(rows) {
  return Object.entries(FILTERS).map(([k, f]) => {
    const counts = countBy(rows, f.get); const on = S.filters[k];
    const label = on.size ? `${f.label}: ${[...on].slice(0, 2).join(", ")}${on.size > 2 ? " +" + (on.size - 2) : ""}` : f.label;
    return `<button class="chip ${on.size ? "on" : ""}" data-chip="${k}" aria-haspopup="true">${esc(label)}${on.size ? `<span class="x" data-clear="${k}" role="button" aria-label="Clear ${f.label}">${icon("x", "sm")}</span>` : icon("down", "sm")}</button>`;
  }).join("");
}
function pgJobs() {
  const base = S.jobs.filter(j => passes(j, true)); const segCounts = countBy(base, stageOf);
  const rows = jobsView(); const s = S.sort || defaultSort(S.seg);
  const segN = k => { const f = SEGS.find(x => x.k === k).f; return base.filter(j => f(stageOf(j), j)).length; };
  const anyFilter = Object.values(S.filters).some(x => x.size) || S.q;
  const th = (key, label, cls = "") => `<th class="sortable ${cls}" data-sort="${key}" aria-sort="${s.key === key ? (s.dir === "asc" ? "ascending" : "descending") : "none"}">${label}${s.key === key ? " " + icon(s.dir === "asc" ? "up" : "down", "sm") : ""}</th>`;
  let body;
  if (!rows.length) body = emptyState(anyFilter ? "No roles match these filters" : "Nothing here", anyFilter ? "Try clearing a filter or the search." : "Roles move here as they change stage.");
  else if (S.view === "board") body = board(rows);
  else body = `<div class="table-wrap density-${S.density}"><table class="data"><thead><tr>${th("score", "Score")}${th("role", "Role")}${th("verdict", "Verdict")}${th("deadline", "Deadline")}<th class="hide-sm">Category</th><th class="hide-sm">Country</th>${th("found", "Found", "hide-md")}</tr></thead><tbody>${
    rows.slice(0, S.shown).map(j => { const sg = stageOf(j); return `<tr tabindex="0" data-open="job" data-id="${esc(j.id)}" class="${S.sel && S.sel.id === j.id ? "sel" : ""}" aria-label="${esc(j.title)} at ${esc(j.employer)}">
      <td class="num">${scoreCell(j.score)}</td><td class="role-cell">${roleCell(j)}</td><td>${verdictBadge(j.verdict)}${sg !== "review" && sg !== "candidate" ? `<div style="margin-top:3px">${stageBadge(sg)}</div>` : ""}</td><td>${due(j.deadline).html}</td>
      <td class="hide-sm dim">${j.category ? esc(CATEGORY[j.category]) : esc(j.field || "")}${j.subfield ? `<span class="muted"> · ${esc(SUBFIELD[j.subfield] || j.subfield)}</span>` : ""}</td><td class="hide-sm dim">${esc(j.country || "")}${j.work_route && j.work_route !== "german_student_permit" ? `<span class="muted" title="${esc(ROUTES[j.work_route] || j.work_route)}"> · ${j.work_route === "none_found" ? "no route" : "permit?"}</span>` : ""}</td>
      <td class="hide-md muted">${esc(ago(j.date_found))}</td></tr>`; }).join("")}</tbody></table>${rows.length > S.shown ? `<div class="more-row"><button class="btn" data-more>Show ${Math.min(100, rows.length - S.shown)} more (${rows.length - S.shown} left)</button></div>` : ""}</div>`;
  return `<div class="toolbar"><div class="seg" role="group" aria-label="Stage">${SEGS.map(x => `<button data-seg="${x.k}" aria-pressed="${S.seg === x.k}">${x.label}<span class="n">${segN(x.k)}</span></button>`).join("")}</div>
      <div class="spacer"></div><div class="seg" role="group" aria-label="View"><button data-view="table" aria-pressed="${S.view === "table"}" title="Table">${icon("table")}</button><button data-view="board" aria-pressed="${S.view === "board"}" title="Board">${icon("board")}</button></div>
      <button class="icon-btn" data-density title="Row density: ${S.density}" aria-label="Toggle row density">${icon("rows")}</button></div>
    <div class="toolbar"><label class="field-search">${icon("search")}<input id="q" type="search" placeholder="Filter by title, employer, place..." value="${esc(S.q)}" aria-label="Filter roles"></label>${chipMenus(base)}
      ${anyFilter ? '<button class="btn ghost sm" data-clearall>Clear all</button>' : ""}</div>
    <div class="result-line">${rows.length} ${rows.length === 1 ? "role" : "roles"}${anyFilter ? " match" : ""} <span class="muted">· sorted by ${esc(s.key === "updated" ? "last change" : s.key)} ${s.dir === "asc" ? "(low to high)" : "(high to low)"}</span></div>${body}
    <div class="shortcuts"><span><kbd>j</kbd> <kbd>k</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span><span><kbd>/</kbd> filter</span><span><kbd>a</kbd> approve</span><span><kbd>x</kbd> not for me</span><span><kbd>Ctrl</kbd>+<kbd>K</kbd> search everything</span></div>`;
}
function board(rows) {
  const cols = ["review", "queued", "ready", "applied", "interview"]; const by = countBy(rows, stageOf);
  return `<div class="board">${cols.map(k => `<div class="col" data-col="${k}"><h3>${icon(STAGES[k].icon, "sm")}${STAGES[k].label}<span class="n">${by[k] || 0}</span></h3><div class="col-scroll">${
    rows.filter(j => stageOf(j) === k).slice(0, 60).map(j => `<div class="kcard ${S.sel && S.sel.id === j.id ? "sel" : ""}" draggable="true" data-open="job" data-id="${esc(j.id)}"><b>${esc(j.title)}</b><span class="muted">${esc(j.employer)}</span><div class="row">${scoreCell(j.score)}${due(j.deadline).n !== null ? due(j.deadline).html : ""}</div></div>`).join("") || '<div class="empty muted">Empty</div>'}</div></div>`).join("")}</div>`;
}

const TSTATUS = {lead: "Lead", outreach_drafted: "Draft ready", outreach_sent: "Sent", replied: "Replied", interview: "Interview", accepted: "Accepted", declined: "Declined", closed: "Closed"};
const TKIND = {advertised: "Posting", topic_list: "Topic list", open_call: "Open call", lead: "Enquiry"};
let PILLARS = {other: "Other"};
function pgThesis() {
  const segs = [["all", "All"], ["lead", "Leads"], ["active", "In contact"], ["done", "Closed"]];
  const f = t => S.thesisSeg === "all" || (S.thesisSeg === "lead" && t.status === "lead") || (S.thesisSeg === "active" && ["outreach_drafted", "outreach_sent", "replied", "interview"].includes(t.status)) || (S.thesisSeg === "done" && ["accepted", "declined", "closed"].includes(t.status));
  const rows = S.thesis.filter(f);
  return `<div class="toolbar"><div class="seg">${segs.map(([k, l]) => `<button data-tseg="${k}" aria-pressed="${S.thesisSeg === k}">${l}<span class="n">${S.thesis.filter(t => k === "all" || (k === "lead" ? t.status === "lead" : k === "active" ? ["outreach_drafted", "outreach_sent", "replied", "interview"].includes(t.status) : ["accepted", "declined", "closed"].includes(t.status))).length}</span></button>`).join("")}</div></div>
  ${rows.length ? `<div class="table-wrap density-${S.density}"><table class="data"><thead><tr><th>Score</th><th>Topic</th><th>Verdict</th><th class="hide-sm">Professor</th><th>Status</th></tr></thead><tbody>${rows.map(t => `<tr tabindex="0" data-open="thesis" data-id="${esc(t.id)}" class="${S.sel && S.sel.id === t.id ? "sel" : ""}"><td>${scoreCell(t.score)}</td>
    <td class="role-cell"><div class="role"><b title="${esc(t.title)}">${esc(t.title)}</b><span>${esc(t.institution)}${t.group_name ? " · " + esc(t.group_name) : ""}</span></div></td><td>${verdictBadge(t.verdict)}</td><td class="hide-sm dim">${esc(t.pi_name || "")}</td><td><span class="badge ${t.status === "lead" ? "accent" : t.status === "replied" || t.status === "interview" ? "violet" : t.status === "outreach_sent" ? "info" : ""}">${esc(TSTATUS[t.status] || t.status)}</span></td></tr>`).join("")}</tbody></table></div>` : emptyState("No thesis leads here")}
  <div class="shortcuts"><span>A thesis opportunity is usually a written enquiry to a group, so the status tracks the conversation, not an application.</span></div>`;
}

let KIND = {other: "Other"};
function reviewQueue() {
  const rank = r => { const m = verdictMeta(r.verdict); return (m ? m.rank : 9) * 100 - (r.score || 0); };
  const rows = [...S.jobs.filter(j => j.status === "open" && BEST(j) && ["auto", "legacy"].includes(j.analysis_level)).map(j => ({...j, _kind: "job"})),
                ...S.thesis.filter(t => t.status === "lead" && BEST(t) && ["auto", "legacy"].includes(t.analysis_level)).map(t => ({...t, _kind: "thesis", employer: t.institution}))];
  return rows.sort((a, b) => rank(a) - rank(b));
}
function pgReview() {
  const tabs = [["confirm", "To confirm"], ["moved", "Scores that moved"], ["unreadable", "JD unreadable"]]; const t = S.reviewTab || "confirm";
  const moved = [...S.jobs, ...S.thesis].filter(r => r.score_flag); const unread = [...S.jobs, ...S.thesis].filter(r => r.analysis_level === "unreadable");
  const tag = r => ({...r, _kind: r.institution ? "thesis" : "job", employer: r.employer || r.institution});
  const rows = t === "confirm" ? reviewQueue() : t === "moved" ? moved.map(tag) : unread.map(tag);
  const cnt = k => k === "confirm" ? reviewQueue().length : k === "moved" ? moved.length : unread.length;
  return `<div class="toolbar"><div class="seg">${tabs.map(([k, l]) => `<button data-rtab="${k}" aria-pressed="${t === k}">${l}<span class="n">${cnt(k)}</span></button>`).join("")}</div></div>
  <div class="result-line">${rows.length} ${t === "confirm" ? "best fits read by the script, waiting for a Claude session to read the full JD against your CV and confirm" : t === "moved" ? "rows whose score or verdict changed after it was written" : "postings whose full description could not be fetched (never scored)"}</div>
  ${rows.length ? `<div class="table-wrap density-${S.density}"><table class="data"><thead><tr><th>Score</th><th>Role</th><th>Verdict</th><th class="hide-sm">Category</th><th class="hide-sm">Read</th><th class="hide-md">Found</th></tr></thead><tbody>${rows.slice(0, 200).map(r => `<tr tabindex="0" data-open="${r._kind}" data-id="${esc(r.id)}" class="${S.sel && S.sel.id === r.id ? "sel" : ""}"><td class="num">${scoreCell(r.score)}</td>
    <td class="role-cell"><div class="role"><b title="${esc(r.title)}">${esc(r.title)}</b><span>${esc(r.employer || "")}${r.location ? " · " + esc(String(r.location).slice(0, 36)) : ""}</span></div></td><td>${verdictBadge(r.verdict)}${r.score_flag ? `<div class="muted" style="font-size:11.5px;margin-top:3px">${icon("alert", "sm")} ${esc(String(r.score_flag).slice(0, 70))}</div>` : ""}</td>
    <td class="hide-sm dim">${r.category ? esc(CATEGORY[r.category] || r.category) : ""}${r.subfield ? `<span class="muted"> · ${esc(SUBFIELD[r.subfield] || r.subfield)}</span>` : ""}</td><td class="hide-sm muted">${esc(levelLabel(r.analysis_level))}</td><td class="hide-md muted">${esc(ago(r.date_found || r.created_at))}</td></tr>`).join("")}</tbody></table></div>` : emptyState("Nothing to confirm", "Every best fit has been read against your CV.")}
  <div class="shortcuts"><span>A Claude session confirms with: <kbd>python scripts/analyze.py show &lt;id&gt;</kbd> then <kbd>review &lt;id&gt; --verdict ...</kbd>. The script never overwrites a confirmed verdict; it only flags a change.</span></div>`;
}

// ---------------------------------------------------------------- mail page (rules/mail.md)
const MKIND = {rejection: ["danger", "Rejection"], interview: ["success", "Invitation"], offer: ["success", "Offer"], info_request: ["warning", "Asks you to act"], ack: ["plain", "Received"], sent_application: ["plain", "You sent"], other_job: ["plain", "Read it"], reply: ["plain", "Reply"]};
function mailRow(e, withCmd) {
  const k = MKIND[e.kind] || ["plain", e.kind]; const open = e.ref ? `data-open="${String(e.ref).startsWith("th-") ? "thesis" : "job"}" data-id="${esc(e.ref)}" tabindex="0"` : 'style="cursor:default"';
  return `<div class="list-row" ${open}><span class="badge ${k[0]}" style="min-width:104px;justify-content:center">${esc(k[1])}</span><div class="role"><b>${esc(e.role || e.subject)}</b><span>${esc(e.employer || e.from)} · ${esc(e.date)}${e.role ? " · " + esc(String(e.subject).slice(0, 60)) : ""}${withCmd ? ` · mail_sync.py show ${esc(e.msg_id)}` : ""}</span></div>${e.state === "applied" ? '<span class="badge success">Tracker updated</span>' : e.state === "needs_read" || e.state === "unmatched" ? '<span class="badge warning">To read</span>' : ""}</div>`;
}
function pgMail() {
  const m = S.mail; if (!m) return '<div class="empty"><b>Loading the mail</b></div>'; const st = m.state || {};
  const stat = (n, l, h) => `<div class="stat"><div class="big">${n}</div><div class="lbl">${l}</div><div class="hint">${h}</div></div>`;
  const failed = st.last_error ? `<div class="callout" style="margin-bottom:12px">${icon("alert", "sm")} <b>Gmail could not be read.</b> ${esc(String(st.last_error).slice(0, 160))}. Run <kbd>python scripts/gmail_client.py auth</kbd> in a terminal and approve in the browser.</div>` : "";
  const death = (st.alert_death || []).map(x => `<div class="callout" style="margin-bottom:8px">${icon("alert", "sm")} ${esc(x)}</div>`).join("");
  return `${failed}${death}<div class="stat-row">${stat(m.act_now.length, "Ask you to act", "interviews, offers, documents (14 days)")}${stat(m.rejections.length, "Rejections recorded", "moved to Rejected by mail")}${stat(m.confirmed.length, "Applications confirmed", "sent by you or acknowledged")}${stat(m.unresolved.length, "Mail to settle", "could not be matched with confidence")}</div>
  <div class="grid-2"><div><section class="panel"><header><h2>Needs you</h2><span class="muted">last 14 days</span></header>${m.act_now.map(e => mailRow(e)).join("") || emptyState("Nothing is waiting on you", "No interview, offer or document request in the last 14 days.")}</section>
  <section class="panel"><header><h2>Mail to settle</h2><span class="muted">a Claude session reads these</span></header>${m.unresolved.slice(0, 25).map(e => mailRow(e, true)).join("") || emptyState("Everything was matched")}</section></div>
  <div><section class="panel"><header><h2>Rejections from mail</h2></header>${m.rejections.slice(0, 12).map(e => mailRow(e)).join("") || emptyState("None yet")}</section>
  <section class="panel"><header><h2>Confirmed by mail</h2></header>${m.confirmed.slice(0, 12).map(e => mailRow(e)).join("") || emptyState("None yet")}</section>
  <section class="panel"><header><h2>Alert mail</h2></header><div class="list-row" style="cursor:default"><div class="role"><b>${st.alerts || 0} alert mails read, ${st.filed || 0} postings filed</b><span>last read ${esc(String(st.last_ok || "never").slice(0, 16).replace("T", " "))} via ${esc(st.source || "-")} · ${st.pending_url || 0} Xing links waiting for their posting address</span></div></div></section></div></div>
  <div class="shortcuts"><span>Read-only: the pipeline never replies, labels or sends. Command line: <kbd>python scripts/mail_sync.py run</kbd> · <kbd>queue</kbd> · <kbd>show &lt;id&gt;</kbd> · <kbd>judge &lt;id&gt; --kind K --job ID</kbd>. Document: rules/mail.md</span></div>`;
}

// ---------------------------------------------------------------- pipeline page (rules/pipeline.md)
const OWNER = {script: "Runs by itself", session: "Claude session", owner: "Your decision", request: "On request"};
const PSTATE = {ok: ["success", "Up to date"], stale: ["warning", "Stale"], pending: ["warning", "Work waiting"], manual: ["plain", "Manual"], blocked: ["danger", "Blocked"], warn: ["warning", "Warnings"]};
async function loadPipeline() { try { S.pipeline = await api("/api/pipeline"); } catch (e) { S.pipeline = null; } render(); }
function pgPipeline() {
  const p = S.pipeline; if (!p) { loadPipeline(); return '<div class="empty"><b>Loading the pipeline</b></div>'; }
  const bad = p.check.filter(c => c.severity === "FAIL" || c.severity === "WARN"); const q = p.queue;
  const stat = (n, l, h, go) => `<div class="stat"><div class="big">${n}</div><div class="lbl">${l}</div><div class="hint">${h}</div></div>`;
  return `<div class="stat-row">${stat((q.S10_mail_act_now || []).length, "Mail asks you to act", "interviews, offers, documents to send")}${stat(q.S23_review_queue.length, "Best fits to confirm", "read in full by a Claude session")}${stat(q.S30_ready_to_send.length, "Ready to send", "packages waiting for you")}${stat(q.S30_deadlines_within_7_days.length, "Deadlines this week", "not yet applied")}${stat(bad.filter(c => c.severity === "FAIL").length + " / " + bad.filter(c => c.severity === "WARN").length, "Audit FAIL / WARN", p.state.last_run ? "last unattended run " + esc(p.state.last_run.slice(0, 16).replace("T", " ")) : "no unattended run yet")}</div>
  <div class="grid-2"><div>${p.phases.map(([id, name]) => `<section class="panel"><header><h2>${esc(id)} · ${esc(name)}</h2></header>${p.stages.filter(s => s.phase === id).map(s => { const m = PSTATE[s.state] || ["plain", s.state]; return `<div class="list-row" style="cursor:default"><span class="badge plain" style="min-width:44px;justify-content:center">${esc(s.id)}</span><div class="role"><b>${esc(s.name)}</b><span>${esc(OWNER[s.owner] || s.owner)}${s.detail ? " · " + esc(s.detail) : ""}</span></div><span class="badge ${m[0]}">${m[1]}</span></div>`; }).join("")}</section>`).join("")}</div>
  <div><section class="panel"><header><h2>Audit</h2><span class="muted">${p.check.length} checks</span></header>${bad.length ? bad.map(c => `<div class="list-row" style="cursor:default;align-items:flex-start"><span class="badge ${c.severity === "FAIL" ? "danger" : "warning"}">${c.severity}</span><div class="role"><b>${esc(c.id)} ${esc(c.title)}</b><span>${c.count} · ${esc(c.fix)}</span></div></div>`).join("") : emptyState("All invariants hold")}</section>
  <section class="panel"><header><h2>Mail to settle</h2><a class="link" href="#/mail">Open Mail</a></header>${(q.S10_mail_needs_read || []).slice(0, 6).map(c => `<div class="list-row" style="cursor:default"><div class="role"><b>${esc(c.subject)}</b><span>${esc(c.from)} · ${esc(c.kind)} · ${esc(c.date)}</span></div></div>`).join("") || emptyState("Nothing waiting")}</section></div></div>
  <div class="shortcuts"><span>Command line: <kbd>python scripts/pipeline.py status</kbd> · <kbd>check</kbd> · <kbd>queue</kbd> · <kbd>run</kbd>. Document: rules/pipeline.md</span></div>`;
}

// ---------------------------------------------------------------- drawer
function factBlock(items) { return `<div class="facts">${items.filter(x => x[1] !== "" && x[1] != null).map(([k, v]) => `<div class="fact"><div class="k">${esc(k)}</div><div class="v">${v}</div></div>`).join("")}</div>`; }
function verdictCard(r) {
  if (!r.verdict) return `<div class="sec"><div class="callout info">${r.analysis_level === "unreadable" ? "The full description could not be fetched, so this role is not scored." : "Not analysed yet: the full description is read first, then it is scored."}</div></div>`;
  const cv = r.cv_match || {}; const br = r.score_breakdown || {}; const comps = br.components ? Object.entries(br.components) : []; const hist = Array.isArray(r.score_history) ? r.score_history : [];
  const chips = (arr, cls) => (arr || []).map(x => `<span class="tag ${cls}" title="${esc(x.evidence || "")}">${esc(x.term.split(" (")[0])}${x.asked === "nice" ? " (nice to have)" : ""}</span>`).join("");
  return `<div class="sec"><h3>Verdict</h3><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">${verdictBadge(r.verdict)}<span class="badge plain">${esc(levelLabel(r.analysis_level))}</span>${r.category ? `<span class="badge plain">${esc(CATEGORY[r.category] || r.category)}${r.subfield ? " · " + esc(SUBFIELD[r.subfield] || r.subfield) : ""}</span>` : ""}</div>
    ${r.verdict_reason ? `<div style="margin-top:8px" class="dim">${esc(String(r.verdict_reason).replace(/^REVIEWED: /, "").split(" | ").slice(0, 3).join(" · "))}</div>` : ""}
    ${r.score_flag ? `<div class="callout" style="margin-top:8px">${icon("alert", "sm")} <b>Score moved:</b> ${esc(r.score_flag)}</div>` : ""}</div>
  ${(cv.covered || []).length || (cv.gaps || []).length || (cv.partial || []).length ? `<div class="sec"><h3>Against your CV</h3>${(cv.covered || []).length ? `<div class="muted" style="font-size:12px;margin-bottom:4px">The posting asks for, and your CV shows</div><div class="chips">${chips(cv.covered, "ok")}</div>` : ""}${(cv.partial || []).length ? `<div class="muted" style="font-size:12px;margin:8px 0 4px">Only partly (coursework or weak evidence)</div><div class="chips">${chips(cv.partial, "part")}</div>` : ""}${(cv.gaps || []).length ? `<div class="muted" style="font-size:12px;margin:8px 0 4px">Asked for and not on your CV</div><div class="chips">${chips(cv.gaps, "gap")}</div>` : ""}</div>` : ""}
  ${comps.length ? `<div class="sec"><h3>How it scored</h3><div class="dim">${comps.map(([k, v]) => `<div style="display:flex;justify-content:space-between;gap:12px"><span>${esc(k.replace(/ \([+-]\d\)/, ""))}</span><b class="tnum">${v > 0 ? "+" : ""}${v}</b></div>`).join("")}${br.route ? `<div style="display:flex;justify-content:space-between;gap:12px"><span>route: ${esc(String(br.route.work_route || "").slice(0, 70))}</span><b class="tnum">${br.route.adjustment > 0 ? "+" : ""}${br.route.adjustment}</b></div>` : ""}<div style="display:flex;justify-content:space-between;border-top:1px solid var(--line);margin-top:4px;padding-top:4px"><span>Score</span><b class="tnum">${r.score != null ? r.score : r.fit_score}</b></div></div></div>` : ""}
  ${hist.length > 1 ? `<details class="tech"><summary>Score history (${hist.length})</summary><dl>${hist.slice().reverse().map(h => `<dt>${esc(String(h.at).slice(0, 10))}</dt><dd>${h.from == null ? "" : h.from + " to "}${h.to} · ${esc(h.trigger || "")}</dd>`).join("")}</dl></details>` : ""}`;
}
function jobDrawer(j) {
  const sg = stageOf(j); const d = due(j.deadline); const hard = Array.isArray(j.hard_reqs) ? j.hard_reqs : [], soft = Array.isArray(j.soft_reqs) ? j.soft_reqs : [];
  const btns = [];
  if (sg === "review") btns.push(`<button class="btn primary" data-act="approve" data-id="${esc(j.id)}">${icon("check", "sm")}Approve</button><button class="btn" data-act="recheck" data-id="${esc(j.id)}">Recheck</button><button class="btn" data-act="skip" data-id="${esc(j.id)}">Not for me</button>`);
  if (sg === "blocked") btns.push(`<button class="btn primary" data-act="approve" data-id="${esc(j.id)}">Approve anyway</button><button class="btn" data-act="skip" data-id="${esc(j.id)}">Not for me</button>`);
  if (sg === "queued") btns.push(`<button class="btn" data-act="recheck" data-id="${esc(j.id)}">Recheck</button><button class="btn" data-act="skip" data-id="${esc(j.id)}">Not for me</button>`);
  if (["ready", "queued", "review", "blocked"].includes(sg)) btns.push(`<span class="date-row"><input type="date" id="applied-date" value="${todayISO()}" aria-label="Date applied"><button class="btn ${sg === "ready" ? "primary" : ""}" data-act="applied" data-id="${esc(j.id)}">${icon("send", "sm")}I applied</button></span>`);
  if (sg === "applied") btns.push(`<button class="btn primary" data-act="interview" data-id="${esc(j.id)}">Got an interview</button><button class="btn" data-act="declined" data-id="${esc(j.id)}">Employer declined</button>`);
  if (sg === "interview") btns.push(`<button class="btn" data-act="declined" data-id="${esc(j.id)}">Employer declined</button>`);
  if (["declined", "closed"].includes(sg)) btns.push(`<button class="btn" data-act="reopen" data-id="${esc(j.id)}">Reopen</button>`);
  if (j.package_path) btns.push(`<button class="btn" data-openfolder="${esc(j.id)}">${icon("folder", "sm")}CV folder</button>`);
  const tech = [["id", j.id], ["status", j.status], ["approval", j.approval], ["tier", j.tier], ["source", j.source], ["track", j.track], ["jd_lang", j.jd_lang], ["jd cache", j.jd_path], ["package", j.package_path], ["reference", j.ref_number], ["contact", j.contact_name], ["version", j.version], ["updated", j.updated_at]].filter(x => x[1] != null && x[1] !== "");
  return `<div class="drawer-head"><div class="top-row">${stageBadge(sg)}${scoreCell(j.score)}<span class="spacer"></span><button class="icon-btn" data-close aria-label="Close">${icon("x")}</button></div>
    <h2>${esc(j.title)}</h2><div class="muted">${esc(j.employer)}${j.location ? " · " + esc(j.location) : ""}</div></div>
  <div class="drawer-body">
    ${j.blocked_reason && sg === "blocked" ? `<div class="sec"><div class="callout"><b>A wall in the posting:</b> ${esc(j.blocked_reason)}</div></div>` : ""}
    <div class="sec"><div class="actions">${btns.join("")}</div></div>
    ${verdictCard(j)}
    <div class="sec"><h3>At a glance</h3>${factBlock([["Deadline", j.deadline ? `${d.html} <span class="muted">· ${fmtDate(j.deadline)}</span>` : ""], ["Found", fmtDate(j.date_found)], ["Applied", fmtDate(j.applied_at)], ["Language", esc(j.lang_bar || j.language_bar || "")],
      ["Country", esc(j.country || "") + (j.work_route ? ` <span class="muted">· ${esc(ROUTES[j.work_route] || j.work_route)}</span>` : "")], ["Category", j.category ? esc(CATEGORY[j.category] + (j.subfield ? " · " + (SUBFIELD[j.subfield] || j.subfield) : "")) : ""], ["Field", esc([j.field, j.track].filter(Boolean).join(" · "))], ["Duration", esc(j.duration || "")], ["Start", esc(j.start_window || "")]])}</div>
    ${j.jd_summary ? `<div class="sec"><h3>The role</h3><div>${esc(j.jd_summary)}</div></div>` : ""}
    ${hard.length || soft.length ? `<div class="sec"><h3>Requirements</h3><div class="chips">${hard.map(x => `<span class="tag must">${esc(x)}</span>`).join("")}${soft.map(x => `<span class="tag">${esc(x)}</span>`).join("")}</div>${hard.length ? '<div class="muted" style="font-size:12px;margin-top:6px">Highlighted: required. Plain: nice to have.</div>' : ""}</div>` : ""}
    ${j.constraints ? `<div class="sec"><div class="callout info"><b>CV format clause:</b> ${esc(j.constraints)}</div></div>` : ""}
    <div class="sec"><h3>Your notes</h3>${j.my_notes ? `<div class="my-notes">${esc(j.my_notes)}</div>` : ""}<textarea id="note" placeholder="Add a note. It stays on this role."></textarea><div class="actions" style="margin-top:8px"><button class="btn sm" data-savenote="${esc(j.id)}">Save note</button></div></div>
    ${j.notes ? `<div class="sec"><h3>From the scan</h3><div class="dim">${esc(j.notes)}</div></div>` : ""}
    <div class="sec"><h3>Links</h3><div class="actions">${j.url ? `<a class="btn" href="${esc(j.url)}" target="_blank" rel="noopener">${icon("ext", "sm")}Open the posting${j.url_verified ? "" : " (unverified)"}</a>` : '<span class="muted">No verified link on record</span>'}${j.apply_url && j.apply_url !== j.url ? `<a class="btn" href="${esc(j.apply_url)}" target="_blank" rel="noopener">${icon("ext", "sm")}Apply page</a>` : ""}</div></div>
    <details class="tech"><summary>Technical details</summary><dl>${tech.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></details>
  </div>`;
}
function thesisDrawer(t) {
  const pubs = Array.isArray(t.publications) ? t.publications : [];
  const opts = Object.entries(TSTATUS).map(([k, l]) => `<option value="${k}" ${t.status === k ? "selected" : ""}>${l}</option>`).join("");
  return `<div class="drawer-head"><div class="top-row"><span class="badge accent">${esc(TKIND[t.posting_kind] || t.posting_kind)}</span>${scoreCell(t.score)}<span class="spacer"></span><button class="icon-btn" data-close aria-label="Close">${icon("x")}</button></div>
    <h2>${esc(t.title)}</h2><div class="muted">${esc(t.institution)}${t.department ? " · " + esc(t.department) : ""}${t.group_name ? " · " + esc(t.group_name) : ""}</div></div>
  <div class="drawer-body">
    ${verdictCard(t)}
    <div class="sec"><div class="date-row"><label for="tstatus" class="muted">Status</label><select id="tstatus">${opts}</select><button class="btn sm" data-tsave="${esc(t.id)}">Update</button>${t.posting_url ? `<a class="btn sm" href="${esc(t.posting_url)}" target="_blank" rel="noopener">${icon("ext", "sm")}Page</a>` : ""}</div></div>
    ${t.posting_text ? `<div class="sec"><h3>What the page says</h3><div class="quote">${esc(t.posting_text)}</div>${t.requirements ? `<div style="margin-top:8px"><b>Requirements:</b> ${esc(t.requirements)}</div>` : ""}</div>` : ""}
    <div class="sec"><h3>Professor and contact</h3>${factBlock([["Professor", esc(t.pi_name || "")], ["Role", esc(t.pi_title || "")], ["Contact", esc([t.contact_name, t.contact_email, t.pi_email].filter(Boolean).join(" · "))], ["Location", esc(t.location || "")], ["Language", esc(t.language_bar || "")], ["Route", esc(t.route_note || ROUTES[t.work_route] || "")]])}</div>
    ${t.group_summary ? `<div class="sec"><h3>The group</h3><div>${esc(t.group_summary)}</div></div>` : ""}
    ${t.pi_work_summary ? `<div class="sec"><h3>The professor's work</h3><div>${esc(t.pi_work_summary)}</div>${pubs.length ? `<ul style="margin:8px 0 0;padding-left:18px">${pubs.map(p => `<li>${esc(p.title)} <span class="muted">(${esc(p.journal || "")}, ${esc(p.year || "")})</span> ${p.doi ? `<a href="https://doi.org/${esc(p.doi)}" target="_blank" rel="noopener">DOI</a>` : ""}${p.relevance ? `<div class="muted" style="font-size:12.5px">${esc(p.relevance)}</div>` : ""}</li>`).join("")}</ul><div class="muted" style="font-size:12px;margin-top:4px">Publications from PubMed.</div>` : ""}</div>` : ""}
    ${t.fit_reasoning ? `<div class="sec"><h3>How it fits you</h3><div>${esc(t.fit_reasoning)}</div>${t.gaps ? `<div class="callout info" style="margin-top:8px"><b>Gaps:</b> ${esc(t.gaps)}</div>` : ""}<div class="muted" style="font-size:12.5px;margin-top:6px">Content score ${t.fit_score ?? "-"} ${t.route_adjustment != null ? (t.route_adjustment >= 0 ? "+" : "") + t.route_adjustment + " route" : ""} = ${t.score ?? "-"}</div></div>` : ""}
    <div class="sec"><h3>Your notes</h3>${t.my_notes ? `<div class="my-notes">${esc(t.my_notes)}</div>` : ""}<textarea id="note" placeholder="Add a note."></textarea><div class="actions" style="margin-top:8px"><button class="btn sm" data-tnote="${esc(t.id)}">Save note</button></div></div>
    ${t.notes ? `<div class="sec"><h3>Next step</h3><div class="dim">${esc(t.notes)}</div></div>` : ""}
  </div>`;
}
async function fullRow(kind, id) {
  const row = kind === "job" ? byId(id) : thById(id); if (!row || row._full) return row;
  try { const r = await api(kind === "job" ? `/api/jobs/${encodeURIComponent(id)}` : `/api/thesis/${encodeURIComponent(id)}`); if (r && !r.error) Object.assign(row, r, {_full: true}); } catch (e) { /* the slim row still renders */ }
  return row;
}
function openDrawer(kind, id, keepScroll) {
  const cur = kind === "job" ? byId(id) : thById(id);
  if (cur && !cur._full) fullRow(kind, id).then(() => { if (S.sel && S.sel.id === id) openDrawer(kind, id, true); });
  S.sel = {kind, id}; const row = kind === "job" ? byId(id) : thById(id); if (!row) return closeDrawer();
  const d = $("#drawer"); const scroll = keepScroll ? $(".drawer-body", d)?.scrollTop : 0; d.innerHTML = kind === "job" ? jobDrawer(row) : thesisDrawer(row); d.classList.add("open"); d.setAttribute("aria-hidden", "false");
  if (scroll) $(".drawer-body", d).scrollTop = scroll; if (window.innerWidth < 860) $("#scrim").style.display = "block";
  $$("tr.sel, .kcard.sel").forEach(e => e.classList.remove("sel")); $(`[data-id="${CSS.escape(id)}"]`)?.classList.add("sel");
}
function closeDrawer(silent) { const d = $("#drawer"); d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); $("#scrim").style.display = "none"; S.sel = null; $$("tr.sel, .kcard.sel").forEach(e => e.classList.remove("sel")); if (!silent) $("#q")?.blur(); }

// ---------------------------------------------------------------- chrome: nav, top bar, palette
function renderChrome() {
  const active = S.jobs.filter(j => ACTIVE.includes(stageOf(j))).length; const inbox = reviewQueue().length;
  const th = S.thesis.filter(t => !["accepted", "declined", "closed"].includes(t.status)).length;
  const items = [["today", "Today", "today", ""], ["jobs", "Jobs", "jobs", active], ["thesis", "Thesis", "thesis", th], ["review", "Review", "inbox", inbox], ["mail", "Mail", "mail", S.mail && S.mail.act_now.length ? S.mail.act_now.length : ""], ["pipeline", "Pipeline", "table", S.pipeline ? S.pipeline.check.filter(c => c.severity === "FAIL").length || "" : ""]];
  $("#nav").innerHTML = items.map(([k, l, ic, c]) => `<a class="nav-item" href="#/${k}" aria-current="${S.route === k ? "page" : "false"}">${icon(ic)}${l}${c !== "" ? `<span class="count">${c}</span>` : ""}</a>`).join("");
  const titles = {today: ["Today", new Date().toLocaleDateString(undefined, {weekday: "long", day: "numeric", month: "long"})], jobs: ["Jobs", `${S.jobs.length} roles tracked`], thesis: ["Thesis", `${S.thesis.length} opportunities`], review: ["Review", "Best fits to confirm against your CV"], mail: ["Mail", "What your inbox says about your applications"], pipeline: ["Pipeline", "Every stage, start to end, with live evidence"]};
  $("#title").innerHTML = `<h1>${titles[S.route][0]}</h1><span class="sub hide-sm">${esc(titles[S.route][1])}</span>`;
  $("#live").className = "live" + (S.live ? "" : " stale"); $("#live").innerHTML = `<i></i><span class="hide-sm">${S.live ? "Live" : "Offline, retrying"}</span>`;
  $("#theme").innerHTML = icon(currentTheme() === "dark" ? "sun" : "moon"); $("#theme").setAttribute("aria-label", currentTheme() === "dark" ? "Switch to light theme" : "Switch to dark theme");
}
const currentTheme = () => document.documentElement.getAttribute("data-theme");
function applyTheme(t) { document.documentElement.setAttribute("data-theme", t); }
let pal = {items: [], i: 0};
function openPalette() { const p = $("#palette"); p.style.display = "block"; $("#scrim").style.display = "block"; $("input", p).value = ""; paletteRender(""); $("input", p).focus(); }
function closePalette() { $("#palette").style.display = "none"; if (!$("#drawer").classList.contains("open") || window.innerWidth >= 860) $("#scrim").style.display = "none"; }
function paletteItems(q) {
  const out = []; const ql = q.trim().toLowerCase();
  const pages = [["Today", "today"], ["Jobs", "jobs"], ["Thesis", "thesis"], ["Inbox", "inbox"]].filter(p => !ql || p[0].toLowerCase().includes(ql));
  pages.forEach(p => out.push({g: "Go to", t: p[0], icon: p[1], run: () => go(p[1])}));
  SEGS.filter(s => ql && ("jobs " + s.label).toLowerCase().includes(ql)).forEach(s => out.push({g: "Go to", t: "Jobs: " + s.label, icon: "jobs", run: () => go("jobs", {seg: s.k})}));
  if (ql) {
    S.jobs.filter(j => matchQuery(j, ql)).sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 7).forEach(j => out.push({g: "Roles", t: j.title, meta: j.employer, icon: "jobs", run: () => { if (S.route !== "jobs") go("jobs", {seg: "all"}); openDrawer("job", j.id); }}));
    S.thesis.filter(t => (t.title + " " + t.institution + " " + (t.pi_name || "")).toLowerCase().includes(ql)).slice(0, 3).forEach(t => out.push({g: "Thesis", t: t.title, meta: t.institution, icon: "thesis", run: () => { go("thesis"); openDrawer("thesis", t.id); }}));
  }
  const cmds = [["Switch theme", "sun", () => { const t = currentTheme() === "dark" ? "light" : "dark"; applyTheme(t); store.set("theme", t); render(); }], ["Toggle row density", "rows", () => { S.density = S.density === "compact" ? "comfortable" : "compact"; store.set("density", S.density); render(); }]].filter(c => !ql || c[0].toLowerCase().includes(ql));
  cmds.forEach(c => out.push({g: "Commands", t: c[0], icon: c[1], run: c[2]}));
  return out.slice(0, 14);
}
function paletteRender(q) {
  pal.items = paletteItems(q); pal.i = 0; let last = "";
  $("#palette ul").innerHTML = pal.items.map((it, i) => { const h = it.g !== last ? `<li class="grp" role="presentation">${it.g}</li>` : ""; last = it.g; return `${h}<li role="option" data-pi="${i}" aria-selected="${i === pal.i}">${icon(it.icon)}<span>${esc(it.t)}</span>${it.meta ? `<span class="meta">${esc(it.meta)}</span>` : ""}</li>`; }).join("") || '<li class="muted">No matches</li>';
}
function paletteMove(d) { pal.i = (pal.i + d + pal.items.length) % Math.max(pal.items.length, 1); $$("#palette li[data-pi]").forEach(li => li.setAttribute("aria-selected", String(+li.dataset.pi === pal.i))); $(`#palette li[data-pi="${pal.i}"]`)?.scrollIntoView({block: "nearest"}); }
function paletteRun(i) { const it = pal.items[i]; if (!it) return; closePalette(); it.run(); }

// ---------------------------------------------------------------- render
function render() {
  if (!S.loaded) { $("#view").innerHTML = '<div class="empty"><b>Loading</b></div>'; return; }
  renderChrome();
  const keepQ = document.activeElement && document.activeElement.id === "q" ? {s: document.activeElement.selectionStart} : null;
  $("#view").innerHTML = ({today: pgToday, jobs: pgJobs, thesis: pgThesis, review: pgReview, mail: pgMail, pipeline: pgPipeline})[S.route]();
  if (keepQ) { const q = $("#q"); q.focus(); q.setSelectionRange(keepQ.s, keepQ.s); }
  if (S.sel && $("#drawer").classList.contains("open")) openDrawer(S.sel.kind, S.sel.id, true);
}

// ---------------------------------------------------------------- events
let menuEl = null;
function closeMenu() { menuEl?.remove(); menuEl = null; }
function openChipMenu(btn, key) {
  closeMenu(); const base = S.jobs.filter(j => passes(j, true)); const counts = countBy(base, FILTERS[key].get); const on = S.filters[key];
  const keys = Object.keys(counts).sort((a, b) => counts[b] - counts[a]); const r = btn.getBoundingClientRect();
  menuEl = document.createElement("div"); menuEl.className = "popover"; menuEl.style.top = (r.bottom + window.scrollY + 6) + "px"; menuEl.style.left = Math.min(r.left + window.scrollX, window.innerWidth - 230) + "px";
  menuEl.innerHTML = keys.map(k => `<label><input type="checkbox" value="${esc(k)}" ${on.has(k) ? "checked" : ""}>${esc(k)}<span class="cnt">${counts[k]}</span></label>`).join("");
  menuEl.addEventListener("change", e => { const v = e.target.value; e.target.checked ? on.add(v) : on.delete(v); S.shown = 100; writeHash(); render(); openChipMenu($(`[data-chip="${key}"]`), key); });
  document.body.appendChild(menuEl);
}
function moveSelection(d) {
  const ids = S.route === "jobs" && S.view === "table" ? $$("tbody tr[data-id]").map(r => r.dataset.id) : S.route === "jobs" ? $$(".kcard").map(r => r.dataset.id) : S.route === "thesis" ? $$("tbody tr[data-id]").map(r => r.dataset.id) : []; if (!ids.length) return;
  const i = S.sel ? ids.indexOf(S.sel.id) : -1; const next = ids[Math.max(0, Math.min(ids.length - 1, i + d))]; const kind = S.route === "thesis" ? "thesis" : "job";
  openDrawer(kind, next); $(`[data-id="${CSS.escape(next)}"]`)?.scrollIntoView({block: "nearest"});
}
document.addEventListener("click", async e => {
  const t = e.target;
  if (menuEl && !menuEl.contains(t) && !t.closest("[data-chip]")) closeMenu();
  const a = t.closest("[data-act]");
  if (a) { e.stopPropagation(); if (a.dataset.act === "undo") return undo(); const id = a.dataset.id || S.sel?.id; return act(id, a.dataset.act, a.dataset.act === "applied" ? $("#applied-date")?.value : undefined); }
  if (t.closest("[data-close]")) return closeDrawer();
  if (t.closest("#scrim")) { closePalette(); if (window.innerWidth < 860) closeDrawer(); return; }
  const clr = t.closest("[data-clear]"); if (clr) { S.filters[clr.dataset.clear].clear(); writeHash(); return render(); }
  const chip = t.closest("[data-chip]"); if (chip) return openChipMenu(chip, chip.dataset.chip);
  if (t.closest("[data-clearall]")) { Object.values(S.filters).forEach(s => s.clear()); S.q = ""; writeHash(); return render(); }
  const go_ = t.closest("[data-go]"); if (go_) { const p = {seg: go_.dataset.seg}; go(go_.dataset.go, p); if (go_.dataset.sort) { const [k, d] = go_.dataset.sort.split(":"); S.sort = {key: k, dir: d}; writeHash(); render(); } return; }
  const seg = t.closest("[data-seg]"); if (seg && S.route === "jobs" && seg.closest(".seg")) { S.seg = seg.dataset.seg; S.sort = null; S.shown = 100; writeHash(); return render(); }
  const v = t.closest("[data-view]"); if (v) { S.view = v.dataset.view; store.set("view", S.view); writeHash(); return render(); }
  if (t.closest("[data-density]")) { S.density = S.density === "compact" ? "comfortable" : "compact"; store.set("density", S.density); return render(); }
  const th = t.closest("th[data-sort]"); if (th) { const k = th.dataset.sort; const cur = S.sort || defaultSort(S.seg); S.sort = {key: k, dir: cur.key === k && cur.dir === "desc" ? "asc" : (k === "role" || k === "deadline" ? "asc" : "desc")}; writeHash(); return render(); }
  if (t.closest("[data-more]")) { S.shown += 100; return render(); }
  const ts = t.closest("[data-tseg]"); if (ts) { S.thesisSeg = ts.dataset.tseg; return render(); }
  const rt = t.closest("[data-rtab]"); if (rt) { S.reviewTab = rt.dataset.rtab; return render(); }
  const cp = t.closest("[data-copy]"); if (cp) { try { await navigator.clipboard.writeText(cp.dataset.copy); toast("Link copied"); } catch (er) { toast("Copy failed"); } return; }
  const ds = t.closest("[data-dismiss]"); if (ds) { S.dismissed.add(ds.dataset.dismiss); store.set("dismissed", [...S.dismissed]); toast("Dismissed"); return render(); }
  const of = t.closest("[data-openfolder]"); if (of) { const r = await api(`/api/jobs/${encodeURIComponent(of.dataset.openfolder)}/open-folder`, "POST"); return toast(r.error ? r.error : "Opened the CV folder"); }
  const sn = t.closest("[data-savenote]"); if (sn) { const txt = $("#note").value.trim(); if (!txt) return; const r = await api(`/api/jobs/${encodeURIComponent(sn.dataset.savenote)}/note`, "POST", {note: txt}); if (r.error) return toast(r.error); Object.assign(byId(sn.dataset.savenote), r); toast("Note saved"); return render(); }
  const tn = t.closest("[data-tnote]"); if (tn) { const txt = $("#note").value.trim(); if (!txt) return; const r = await api(`/api/thesis/${encodeURIComponent(tn.dataset.tnote)}/note`, "POST", {note: txt}); if (r.error) return toast(r.error); Object.assign(thById(tn.dataset.tnote), r); toast("Note saved"); return render(); }
  const tsv = t.closest("[data-tsave]"); if (tsv) { const r = await api(`/api/thesis/${encodeURIComponent(tsv.dataset.tsave)}/status`, "POST", {status: $("#tstatus").value}); if (r.error) return toast(r.error); Object.assign(thById(tsv.dataset.tsave), r); toast("Status updated"); return render(); }
  const open = t.closest("[data-open]"); if (open && !t.closest("a, button, input, select")) return openDrawer(open.dataset.open, open.dataset.id);
  const pi = t.closest("#palette li[data-pi]"); if (pi) return paletteRun(+pi.dataset.pi);
  if (t.closest("#theme")) { const n = currentTheme() === "dark" ? "light" : "dark"; applyTheme(n); store.set("theme", n); return render(); }
  if (t.closest("#search-trigger")) return openPalette();
  if (t.closest("#menu")) return $(".side").classList.toggle("open");
  if (t.closest("#nav a")) $(".side").classList.remove("open");
});
document.addEventListener("input", e => { if (e.target.id === "q") { S.q = e.target.value; S.shown = 100; writeHash(); render(); } if (e.target.closest("#palette")) paletteRender(e.target.value); });
document.addEventListener("change", e => {
  if (e.target.matches("[data-idays]")) { S.inbox.days = +e.target.value; render(); }
  if (e.target.matches("[data-ipillar]")) { S.inbox.onPillar = e.target.checked; render(); }
});
document.addEventListener("keydown", e => {
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); return $("#palette").style.display === "block" ? closePalette() : openPalette(); }
  if ($("#palette").style.display === "block") {
    if (e.key === "Escape") closePalette(); else if (e.key === "ArrowDown") { e.preventDefault(); paletteMove(1); } else if (e.key === "ArrowUp") { e.preventDefault(); paletteMove(-1); } else if (e.key === "Enter") { e.preventDefault(); paletteRun(pal.i); } return;
  }
  if (e.key === "Escape") { closeMenu(); if ($("#drawer").classList.contains("open")) closeDrawer(); return; }
  if (typing) return;
  if (e.key === "/" && S.route === "jobs") { e.preventDefault(); $("#q")?.focus(); }
  else if (e.key === "j" || e.key === "ArrowDown") { if (S.route === "jobs" || S.route === "thesis") { e.preventDefault(); moveSelection(1); } }
  else if (e.key === "k" || e.key === "ArrowUp") { if (S.route === "jobs" || S.route === "thesis") { e.preventDefault(); moveSelection(-1); } }
  else if (e.key === "Enter" && document.activeElement.matches("tr[data-id]")) openDrawer(S.route === "thesis" ? "thesis" : "job", document.activeElement.dataset.id);
  else if (S.sel && S.sel.kind === "job" && e.key === "a") act(S.sel.id, "approve"); else if (S.sel && S.sel.kind === "job" && e.key === "x") act(S.sel.id, "skip");
});
// board drag and drop: only moves that are ordinary actions (each has undo)
document.addEventListener("dragstart", e => { const c = e.target.closest?.(".kcard"); if (c) e.dataTransfer.setData("text/plain", c.dataset.id); });
document.addEventListener("dragover", e => { const c = e.target.closest?.(".col"); if (c) { e.preventDefault(); $$(".col.drop").forEach(x => x !== c && x.classList.remove("drop")); c.classList.add("drop"); } });
document.addEventListener("drop", e => {
  const c = e.target.closest?.(".col"); $$(".col.drop").forEach(x => x.classList.remove("drop")); if (!c) return; e.preventDefault();
  const id = e.dataTransfer.getData("text/plain"); const j = byId(id); if (!j) return; const to = c.dataset.col, from = stageOf(j); if (to === from) return;
  const map = {queued: "approve", applied: "applied", interview: "interview", review: "reopen"}; if (!map[to]) return toast("Ready to send is set when a CV package is built");
  act(id, map[to]);
});
window.addEventListener("hashchange", () => { const prev = S.route; readHash(); if (S.route !== prev) closeDrawer(true); render(); });
setInterval(() => load(false), 15000); document.addEventListener("visibilitychange", () => { if (!document.hidden) load(false); });

// ---------------------------------------------------------------- start
applyTheme(S.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
readHash(); render(); load(true);
