/* The start page: a CV in, jobs out. Every piece of text from the server or from a posting is inserted as text, never as HTML. */
"use strict";

const $ = (id) => document.getElementById(id);
const S = { engine: null, status: null, und: null, results: [], filter: "ALL", shown: 30, poll: null, cvReady: false, tailorPoll: null };

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

async function api(path, opts) {
  try {
    const r = await fetch(path, opts);
    const data = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, data };
  } catch (e) {
    return { ok: false, status: 0, data: { error: "The application is not reachable. Is it still running?" } };
  }
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

let toastTimer = null;
function toast(text) {
  const t = $("toast"); t.textContent = text; t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 4500);
}

/* ---------- theme ---------- */
$("theme").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", cur);
  try { localStorage.setItem("theme", JSON.stringify(cur)); } catch (e) {}
});

/* ---------- engine ---------- */
async function loadEngine() {
  const { data } = await api("/api/app/engine");
  S.engine = data;
  const c = data.claude || {};
  const pill = $("engine");
  pill.className = "st-pill " + (c.subscription ? "ok" : "bad");
  pill.textContent = c.subscription ? "Claude subscription ready" : (c.installed ? "Claude: sign in needed" : "Claude Code missing");
  const warn = $("engine-warn");
  if (!c.subscription && !data.configured) {
    warn.hidden = false;
    clear(warn).append(h("strong", { text: c.message || "Claude Code is not ready. " }), h("br"),
      "The application uses your Claude subscription through Claude Code. Install it from claude.com/claude-code, open a terminal, type ",
      h("code", { text: "claude" }), " once and sign in with your Claude account. Then reload this page.");
  } else warn.hidden = true;
  $("dash-link").hidden = !data.configured;
  updateStart();
}

/* ---------- the CV ---------- */
function setCv(info) {
  S.cvReady = true;
  const ok = $("cv-ok"); ok.hidden = false;
  ok.textContent = `Got it: ${info.file || "your CV"}, ${Number(info.chars).toLocaleString()} characters, written in ${info.language === "de" ? "German" : "English"}.`;
  $("cv-err").hidden = true;
  $("drop-title").textContent = "Choose another CV, or drop it here";
  updateStart();
}
function cvError(r) {
  const e = $("cv-err"); e.hidden = false;
  e.textContent = (r.data.error || "That did not work.") + (r.data.hint ? " " + r.data.hint : "");
}
async function upload(file) {
  if (!file) return;
  const fd = new FormData(); fd.append("file", file); fd.append("notes", $("notes").value);
  $("cv-ok").hidden = true; $("start-hint").textContent = "Reading the file…";
  const r = await api("/api/app/cv", { method: "POST", body: fd });
  r.ok ? setCv(r.data) : cvError(r);
}
$("file").addEventListener("change", (e) => upload(e.target.files[0]));
const drop = $("drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => upload(e.dataTransfer.files[0]));
$("toggle-paste").addEventListener("click", () => { const p = $("paste"); p.hidden = !p.hidden; });
$("paste-use").addEventListener("click", async () => {
  const r = await post("/api/app/cv", { text: $("paste-text").value });
  if (r.ok) { setCv(r.data); await post("/api/app/notes", { text: $("notes").value }); } else cvError(r);
});

function running() { return S.status && S.status.status === "running"; }
function updateStart() {
  const c = (S.engine || {}).claude || {};
  const ready = (S.cvReady || (S.status && S.status.cv_now && S.status.cv_now.has)) && !running();
  const engineOk = c.subscription || (S.engine && S.engine.configured);
  $("start").disabled = !(ready && engineOk);
  $("start").textContent = S.engine && S.engine.configured ? "Update my jobs" : "Find my jobs";
  $("start-hint").textContent = running() ? "A run is in progress." : (!ready ? "Add your CV to begin." : (!engineOk ? "Claude Code needs to be ready first." :
    "It takes from ten minutes to a couple of hours, depending on how much there is to read. You can close this page: it keeps working."));
}
$("start").addEventListener("click", async () => {
  await post("/api/app/notes", { text: $("notes").value });
  const r = await post("/api/app/run", { budget: Number($("budget").value) || 8, review_limit: Number($("review-limit").value) || 0 });
  if (!r.ok) return toast(r.data.error || "Could not start");
  startPolling();
  await refreshStatus();
});
$("stop").addEventListener("click", async () => { await post("/api/app/stop", {}); toast("It will stop after the step it is on."); });
$("stop-now").addEventListener("click", async () => { await post("/api/app/stop", { now: true }); await refreshStatus(); });
$("again").addEventListener("click", () => $("start").click());

/* ---------- progress ---------- */
const ICON = { pending: "", running: "", done: "✓", skipped: "–", error: "!" };
function renderRun(st) {
  const show = st.status !== "idle" || st.stages.some((s) => s.status !== "pending");
  $("card-run").hidden = !show;
  if (!show) return;
  const ol = clear($("stages"));
  for (const s of st.stages) ol.append(h("li", { class: s.status }, h("span", { class: "ico", text: ICON[s.status] || "" }),
    h("div", {}, h("div", { class: "label", text: s.label }), s.message ? h("div", { class: "msg", text: s.message }) : null)));
  const isRun = st.status === "running";
  $("stop").hidden = !isRun; $("stop-now").hidden = !isRun;
  $("again").hidden = !(st.status === "error" || st.status === "stopped");
  $("again").textContent = st.status === "stopped" ? "Carry on" : "Press Start again";
  const err = $("run-err");
  err.hidden = !st.error;
  if (st.error) clear(err).append(h("strong", { text: st.error }), st.hint ? h("div", { text: st.hint }) : null);
  $("run-msg").textContent = isRun ? "Working. You can close this page and come back." : (st.status === "done" ? "Finished." : "");
  const u = st.cost_usd || 0;
  $("usage").textContent = u > 0 ? `Claude usage this run: about $${u.toFixed(2)} at list price. On a subscription that is not charged; it is what the run took from your plan.` : "";
  $("log").textContent = (st.log || []).join("\n");
}

async function refreshStatus() {
  const { data } = await api("/api/app/status");
  S.status = data;
  renderRun(data);
  const understood = data.stages.find((s) => s.id === "configure");
  if (understood && understood.status === "done") await loadUnderstood();
  const read = data.stages.find((s) => s.id === "read");
  if (read && (read.status === "done" || read.status === "running" || data.status === "done")) await loadResults();
  const tail = Object.values(data.tailor || {}).some((t) => t.status === "running");
  if (tail && !S.tailorPoll) S.tailorPoll = setInterval(refreshStatus, 4000);
  if (!tail && S.tailorPoll) { clearInterval(S.tailorPoll); S.tailorPoll = null; loadResults(); }
  updateStart();
  return data;
}
function startPolling() {
  if (S.poll) return;
  S.poll = setInterval(async () => {
    const d = await refreshStatus();
    if (d.status !== "running") { clearInterval(S.poll); S.poll = null; await loadEngine(); await loadResults(); }
  }, 2500);
}

/* ---------- what was understood, and corrections ---------- */
const STAGES_OF_LIFE = [["student", "Student"], ["new_grad", "New graduate"], ["experienced", "Experienced"], ["career_change", "Changing field"]];
const KINDS = [["thesis", "Thesis"], ["student_assistant", "Student assistant"], ["working_student", "Working student"], ["internship", "Internship"], ["trainee", "Trainee"], ["entry", "Entry level"], ["mid", "Mid level"], ["senior", "Senior"]];
const AUTH = [["unrestricted", "I can work without a permit"], ["citizen", "Citizen"], ["permanent_resident", "Permanent resident"], ["eu_citizen", "EU/EEA citizen in an EU country"], ["student_visa", "Student visa"], ["opt", "Student work permit (OPT or similar)"], ["work_visa", "Work visa tied to an employer"], ["needs_sponsorship", "I need an employer to sponsor me"]];
const LEVELS = ["a1", "a2", "b1", "b2", "c1", "c2", "native"];

async function loadUnderstood() {
  const { data } = await api("/api/app/understood");
  S.und = data;
  if (!data.configured) { $("card-understood").hidden = true; return; }
  $("card-understood").hidden = false;
  renderUnderstood(data);
}
function lowConf(key) {
  const a = ((S.und || {}).assumptions || []).find((x) => String(x.key).split(".")[0] === key);
  return a && a.confidence !== "high" && a.source !== "you" ? a : null;
}
function field(label, key, control, help) {
  const a = lowConf(key);
  return h("div", { class: "st-field" }, h("span", {}, label, a ? h("span", { class: "st-low", text: "check this", title: a.why || "" }) : null), control,
    help || (a && a.why ? h("span", { class: "why", text: a.why }) : null));
}
function renderUnderstood(u) {
  const el = clear($("und-body"));
  el.append(h("p", { text: (u.categories || []).length ? "Fields: " + u.categories.join(", ") : "" }));
  el.append(h("div", { class: "st-tags" }, (u.subfields || []).map((s) => h("span", { class: "st-tag " + (s.role || ""), text: s.label + (s.role ? " · " + s.role : "") }))));
  const ev = u.evidence || {};
  el.append(h("p", { class: "st-muted", text: `Your CV shows ${ev.covered || 0} skills and tools clearly, ${ev.partial || 0} partly. Postings often ask for ${ev.gap || 0} more that it does not show.` }));
  if ((u.search_terms || []).length) el.append(h("p", { class: "st-muted", text: "Searching for: " + u.search_terms.join(", ") }));
  el.append(h("p", { class: "st-muted", text: "Everything below was filled in from your CV. Correct what is wrong: the jobs are re-scored straight away." }));

  const stage = h("select", { id: "e-stage" }, STAGES_OF_LIFE.map(([v, t]) => h("option", { value: v, selected: u.career_stage === v, text: t })));
  const kinds = h("div", { class: "st-tags", id: "e-kinds" }, KINDS.map(([v, t]) => h("label", { class: "st-check" },
    h("input", { type: "checkbox", value: v, checked: (u.levels_sought || []).includes(v) }), t)));
  const auth = h("select", { id: "e-auth" }, AUTH.map(([v, t]) => h("option", { value: v, selected: (u.work_authorization || {}).status === v, text: t })));
  const regions = h("input", { type: "text", id: "e-regions", value: (u.regions || []).join(", "), placeholder: "de, eu" });
  const cities = h("input", { type: "text", id: "e-cities", value: (u.cities || []).join(", "), placeholder: "Munich, Berlin" });
  const remote = h("label", { class: "st-check" }, h("input", { type: "checkbox", id: "e-remote", checked: u.remote_ok !== false }), "Remote work is fine");
  const income = h("label", { class: "st-check" }, h("input", { type: "checkbox", id: "e-income", checked: !!u.accept_unrelated_income }), "A job outside my field is fine if it pays");
  const langs = h("div", { id: "e-langs" }, (u.languages || []).map((l) => langRow(l.code, l.level)));
  const addLang = h("button", { class: "st-linkbtn", type: "button", onclick: () => langs.append(langRow("", "b1")) }, "Add a language");
  const doclang = h("input", { type: "text", id: "e-doclang", value: u.document_language || "", placeholder: "en" });

  el.append(field("Where you are in your career", "career_stage", stage),
    field("Kinds of role you want", "levels_sought", kinds),
    field("Countries to search (region codes, home market first)", "regions", regions, h("span", { class: "why", text: "Ready-made: " + ((S.engine || {}).region_packs || []).join(", ") + ". Another country needs its rules researched first." })),
    field("Right to work in your home market", "work_authorization", auth, h("span", { class: "why", text: "A permit that limits your hours or needs an employer lowers the score of roles that cannot give it. Only say what is true." })),
    field("Languages and levels (be honest: a stated level is treated as a promise)", "languages", h("div", {}, langs, addLang)),
    field("Cities", "cities", cities), h("div", { class: "st-field" }, remote, income),
    field("Language of your CV and letters", "document_language", doclang),
    h("div", { class: "st-actions" }, h("button", { class: "st-btn primary", type: "button", id: "save-edits", onclick: saveEdits }, "Save and re-score"),
      h("span", { class: "st-muted", id: "edit-msg" })));
}
function langRow(code, level) {
  return h("div", { class: "st-lang" }, h("input", { type: "text", value: code, placeholder: "en", "aria-label": "Language code", class: "lang-code" }),
    h("select", { "aria-label": "Level", class: "lang-level" }, LEVELS.map((l) => h("option", { value: l, selected: l === level, text: l.toUpperCase() }))));
}
const csv = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
async function saveEdits() {
  const edits = {
    career_stage: $("e-stage").value,
    levels_sought: [...document.querySelectorAll("#e-kinds input:checked")].map((i) => i.value),
    work_authorization: { status: $("e-auth").value, note: ((S.und || {}).work_authorization || {}).note || "" },
    regions: csv($("e-regions").value), cities: csv($("e-cities").value), remote_ok: $("e-remote").checked, accept_unrelated_income: $("e-income").checked,
    languages: [...document.querySelectorAll("#e-langs .st-lang")].map((r) => ({ code: r.querySelector(".lang-code").value.trim().toLowerCase(), level: r.querySelector(".lang-level").value })).filter((l) => l.code),
    document_language: $("e-doclang").value.trim().toLowerCase(),
  };
  $("save-edits").disabled = true; $("edit-msg").textContent = "Checking…";
  const r = await post("/api/app/assumptions", { edits });
  $("save-edits").disabled = false;
  if (!r.ok) { $("edit-msg").textContent = (r.data.error || "Not saved") + " " + (r.data.hint || ""); return; }
  $("edit-msg").textContent = "Saved. Re-scoring every posting (a minute or two)…";
  setTimeout(async () => { await loadUnderstood(); await loadResults(); $("edit-msg").textContent = ""; toast("Jobs re-scored with your corrections."); }, 6000);
}

/* ---------- the jobs ---------- */
const FILTERS = [["ALL", "All"], ["APPLY", "Apply"], ["BACKUP", "Backup"], ["PLAN", "Plan"], ["LATER", "Later"], ["CONF", "Read twice"]];
async function loadResults() {
  const { data } = await api("/api/app/results");
  S.results = data.results || [];
  const c = data.counts || {};
  $("card-results").hidden = false;
  $("res-counts").textContent = c.postings ? `${c.postings} postings found, ${c.read_in_full} read in full, ${c.best_fits} worth your time, ${c.confirmed} confirmed by a second reading` : "";
  renderFilters(); renderJobs();
  loadExtras();
}
function renderFilters() {
  const box = clear($("filters"));
  for (const [v, t] of FILTERS) {
    const n = v === "ALL" ? S.results.length : v === "CONF" ? S.results.filter((r) => r.confirmed).length : S.results.filter((r) => r.verdict === v).length;
    box.append(h("button", { class: "st-chip", type: "button", "aria-pressed": String(S.filter === v), onclick: () => { S.filter = v; S.shown = 30; renderFilters(); renderJobs(); } }, `${t} ${n}`));
  }
}
function daysLeft(d) {
  if (!/^\d{4}-\d{2}-\d{2}/.test(d || "")) return null;
  return Math.ceil((new Date(d.slice(0, 10)) - new Date(new Date().toDateString())) / 86400000);
}
function renderJobs() {
  const box = clear($("res-list"));
  const rows = S.results.filter((r) => S.filter === "ALL" || (S.filter === "CONF" ? r.confirmed : r.verdict === S.filter));
  if (!rows.length) { box.append(h("p", { class: "st-muted", text: running() ? "Nothing yet. Jobs appear here as they are read." : "No jobs in this view." })); return; }
  const tailor = (S.status && S.status.tailor) || {};
  for (const r of rows.slice(0, S.shown)) {
    const dl = daysLeft(r.deadline);
    const t = tailor[r.id];
    box.append(h("article", { class: "st-job" + (r.approval === "skip" ? " skipped" : "") },
      h("div", { class: "st-job-head" },
        h("div", { class: "st-score", text: r.score ?? "–", title: "Score out of 10" }),
        h("div", {}, h("h3", { text: r.title }),
          h("div", { class: "meta" }, h("span", { class: "st-badge " + r.verdict, text: r.verdict }), r.confirmed ? h("span", { class: "st-badge conf", text: "read twice" }) : null,
            [r.employer, r.place].filter(Boolean).join(" · "),
            dl !== null ? h("span", { class: "st-deadline" + (dl >= 0 && dl <= 7 ? " soon" : ""), text: dl < 0 ? " · deadline passed" : ` · deadline in ${dl} day${dl === 1 ? "" : "s"}` }) : null))),
      r.why ? h("p", { class: "st-why", text: r.why }) : null,
      r.covered.length ? h("div", { class: "st-fit" }, h("b", { text: "Your CV shows: " }), r.covered.join(", ")) : null,
      r.gaps.length ? h("div", { class: "st-fit" }, h("b", { text: "Not on your CV: " }), r.gaps.join(", ")) : null,
      h("div", { class: "st-job-actions" },
        r.url ? h("a", { class: "st-btn secondary sm", href: r.url, target: "_blank", rel: "noopener noreferrer", text: "Open the posting" }) : null,
        !r.verified && r.url ? h("span", { class: "st-muted", text: "link not checked yet" }) : null,
        !t && r.kind === "job" ? h("button", { class: "st-btn primary sm", type: "button", onclick: () => buildApplication(r) }, "Approve and write my application") : null,
        r.kind === "job" ? h("button", { class: "st-btn danger sm", type: "button", onclick: () => notForMe(r) }, "Not for me") : null),
      t ? tailorBlock(r, t) : null));
  }
  moreButton(box, rows.length);
}
function moreButton(box, total) {
  if (total <= S.shown) return;
  box.append(h("p", {}, h("button", { class: "st-btn secondary", type: "button", onclick: () => { S.shown += 30; renderJobs(); } }, `Show 30 more (${total - S.shown} left)`)));
}
function tailorBlock(r, t) {
  if (t.status === "running") return h("p", { class: "st-callout info", text: t.message || "Writing…" });
  if (t.status === "error") return h("p", { class: "st-callout bad", text: t.message });
  return h("div", {}, h("p", { class: "st-ok", text: "Your application is ready. Read it, then send it yourself: the application never sends anything." }),
    h("div", { class: "st-files" }, (t.files || []).map((f) => h("a", { href: `/api/app/package/${encodeURIComponent(r.id)}/${encodeURIComponent(f)}`, target: "_blank", rel: "noopener", text: f }))));
}
async function buildApplication(r) {
  if (!confirm(`Write a tailored CV and cover letter for:\n${r.title} at ${r.employer}?\n\nIt takes a few minutes and uses part of your Claude plan. Nothing is sent to anyone.`)) return;
  const x = await post(`/api/app/tailor/${encodeURIComponent(r.id)}`, {});
  if (!x.ok) return toast(x.data.error || "Could not start");
  toast("Writing your application. You can keep browsing.");
  startPolling(); await refreshStatus();
}
async function notForMe(r) {
  const x = await post(`/api/jobs/${encodeURIComponent(r.id)}/reject`, {});
  if (x.ok) { r.approval = "skip"; S.results = S.results.filter((q) => q.id !== r.id); renderFilters(); renderJobs(); toast("Removed from your list."); }
  else toast("Could not save that.");
}

/* ---------- the rest of the toolkit ---------- */
let extrasLoaded = false;
async function loadExtras() {
  if (extrasLoaded) return;
  extrasLoaded = true;
  $("card-extras").hidden = false;
  const { data } = await api("/api/app/extras");
  const box = clear($("extras"));
  const time = h("input", { type: "text", value: "07:30", style: "width:90px", "aria-label": "Time of day" });
  const sched = h("div", { class: "st-extra" }, h("h3", { text: "Run by itself every day" }),
    h("p", { class: "st-muted", text: "Collects new postings and re-scores them once a day, on its own. It does not use Claude; the second reading waits for you here." }),
    h("div", { class: "st-actions" }, time, h("button", { class: "st-btn secondary sm", type: "button", onclick: async () => { const r = await post("/api/app/schedule", { action: "install", time: time.value }); toast(r.ok ? "Scheduled." : (r.data.error || "Failed")); } }, "Turn on"),
      h("button", { class: "st-btn secondary sm", type: "button", onclick: async () => { await post("/api/app/schedule", { action: "remove" }); toast("Turned off."); } }, "Turn off")),
    h("p", { class: "st-muted", text: data.schedule || "" }));
  const prev = h("div", {});
  const digest = h("div", { class: "st-extra" }, h("h3", { text: "Daily summary by e-mail" }),
    h("p", { class: "st-muted", text: "A short e-mail to yourself with the day's best fits. The only mail this application ever sends, and only to your own address." }),
    h("div", { class: "st-actions" },
      h("button", { class: "st-btn secondary sm", type: "button", onclick: async () => { const r = await post("/api/app/digest", {}); clear(prev); if (r.ok) prev.append(h("iframe", { class: "st-iframe", sandbox: "", srcdoc: r.data.html, title: "Preview" })); } }, "Preview"),
      h("button", { class: "st-btn secondary sm", type: "button", onclick: async () => { const r = await post("/api/app/digest", { send: true }); toast(r.ok ? "Sent to you." : ((r.data.error || "Not sent") + " " + (r.data.hint || ""))); } }, "Send it to me now")), prev);
  const g = data.gmail || {};
  const gmail = h("div", { class: "st-extra" }, h("h3", { text: "Gmail: replies and job alerts" }),
    h("p", { class: "st-muted", text: g.token ? "Connected. It only reads: replies to your applications and job-alert e-mails. It never replies, deletes or sends." : g.credentials ? "Credentials found. Run the sign-in once: python scripts/gmail_client.py auth" : "Not connected. It needs a one-time setup in your Google account; the steps are in docs/GMAIL.md. Optional." }));
  const p = data.phone || {};
  const phone = h("div", { class: "st-extra" }, h("h3", { text: "Approve from your phone" }),
    h("p", { class: "st-muted", text: p.configured ? "Set up. Decisions you make on the phone are applied here the next time the computer is on." : "Not set up. It needs a free Cloudflare account; the steps are in docs/PHONE.md. Optional." }));
  const tools = h("details", { class: "st-details" }, h("summary", { text: "Tools on this computer" }), h("pre", { class: "st-log", text: data.tools || "" }));
  box.append(sched, digest, gmail, phone, tools);
}

/* ---------- start ---------- */
(async function init() {
  await loadEngine();
  const st = await refreshStatus();
  if (st.cv && st.cv.file) { S.cvReady = true; const ok = $("cv-ok"); ok.hidden = false; ok.textContent = `Your CV on file: ${st.cv.file}, ${Number(st.cv.chars).toLocaleString()} characters. Drop another to replace it.`; }
  if (st.status === "running") startPolling();
  else if (st.status === "done" || (S.engine && S.engine.configured)) await loadResults();
  updateStart();
})();
