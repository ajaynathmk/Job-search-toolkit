// job-inbox: the phone side of the job-search tracker (rules/remote.md).
//
// The PC pushes a slim snapshot (POST /api/pc/snapshot, bearer key) and pulls decisions (GET /api/pc/events, POST /api/pc/ack).
// The phone page logs in with a passphrase (cookie session), reads the snapshot and records decisions as events (POST /api/decision).
// Nothing here can reach the PC: decisions wait in KV until the PC asks for them. Events are never applied here.

const enc = new TextEncoder();
const SESSION_DAYS = 60;
const EVENT_TTL = 60 * 60 * 24 * 30;
const MAX_SNAPSHOT = 1.5 * 1024 * 1024;
const MAX_DETAILS = 6 * 1024 * 1024;
const JOB_ACTIONS = new Set(["approve", "recheck", "skip", "applied", "reopen", "note"]);
const THESIS_ACTIONS = new Set(["skip", "note"]);

const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

function safeEq(a, b) {
  a = String(a); b = String(b);
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function hmac(key, data) {
  const k = await crypto.subtle.importKey("raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64u(await crypto.subtle.sign("HMAC", k, enc.encode(data)));
}

async function pbkdf2(pass, saltB64, iterations) {
  const k = await crypto.subtle.importKey("raw", enc.encode(pass), "PBKDF2", false, ["deriveBits"]);
  return b64u(await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: unb64u(saltB64), iterations }, k, 256));
}

const SEC = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
};

function json(obj, status = 200, extra = {}) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json; charset=utf-8", ...SEC, ...extra } });
}

function cookieOf(req, name) {
  const m = (req.headers.get("Cookie") || "").match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? m[1] : "";
}

async function sessionOk(req, env) {
  const v = cookieOf(req, "s");
  const [exp, sig] = v.split(".");
  if (!exp || !sig || Number(exp) < Date.now() / 1000) return false;
  return safeEq(sig, await hmac(env.COOKIE_KEY, "v1." + exp));
}

function pcOk(req, env) {
  const h = req.headers.get("Authorization") || "";
  return h.startsWith("Bearer ") && safeEq(h.slice(7), env.PC_KEY);
}

async function listEvents(env, { pendingOnly = false, limit = 300 } = {}) {
  const out = [];
  let cursor;
  do {
    const page = await env.KV.list({ prefix: "ev:", cursor });
    for (const k of page.keys) {
      const raw = await env.KV.get(k.name);
      if (!raw) continue;
      const ev = JSON.parse(raw);
      if (!pendingOnly || ev.status === "pending") out.push(ev);
      if (out.length >= limit) return out;
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out;
}

const isDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(s));

async function route(req, env, url, p) {
  const method = req.method;

  // ------------------------------------------------------------------ the PC
  if (p.startsWith("/api/pc/")) {
    if (!pcOk(req, env)) return json({ error: "unauthorised" }, 401);
    if (p === "/api/pc/snapshot" && method === "POST") {
      const text = await req.text();
      if (text.length > MAX_SNAPSHOT) return json({ error: "snapshot too large" }, 413);
      const snap = JSON.parse(text);
      if (!snap || !Array.isArray(snap.items)) return json({ error: "bad snapshot" }, 400);
      await env.KV.put("snapshot", text);
      return json({ ok: true, items: snap.items.length });
    }
    if (p === "/api/pc/details" && method === "POST") {
      const text = await req.text();
      if (text.length > MAX_DETAILS) return json({ error: "details too large" }, 413);
      const d = JSON.parse(text);
      if (!d || typeof d.details !== "object") return json({ error: "bad details" }, 400);
      await env.KV.put("details", text);
      return json({ ok: true, items: Object.keys(d.details).length });
    }
    if (p === "/api/pc/events" && method === "GET") return json({ events: await listEvents(env, { pendingOnly: true }) });
    if (p === "/api/pc/ack" && method === "POST") {
      const { results } = await req.json();
      let n = 0;
      for (const r of results || []) {
        const raw = await env.KV.get(r.id);
        if (!raw || !String(r.id).startsWith("ev:")) continue;
        const ev = JSON.parse(raw);
        ev.status = r.ok ? "applied" : "failed";
        ev.msg = String(r.msg || "").slice(0, 200);
        ev.done_at = new Date().toISOString();
        await env.KV.put(r.id, JSON.stringify(ev), { expirationTtl: EVENT_TTL });
        n++;
      }
      return json({ ok: true, acked: n });
    }
    return json({ error: "not found" }, 404);
  }

  // ------------------------------------------------------------------ login
  if (p === "/api/login" && method === "POST") {
    const ip = req.headers.get("CF-Connecting-IP") || "unknown";
    const rlKey = "rl:" + ip;
    const tries = Number((await env.KV.get(rlKey)) || 0);
    if (tries >= 8) return json({ error: "too many attempts, try again in an hour" }, 429);
    let pass = "";
    try { pass = String((await req.json()).passphrase || ""); } catch { /* empty */ }
    const [iter, salt, hash] = String(env.PASS_HASH || "").split("$");
    const ok = !!(iter && salt && hash) && safeEq(await pbkdf2(pass, salt, Number(iter)), hash);
    if (!ok) {
      await env.KV.put(rlKey, String(tries + 1), { expirationTtl: 3600 });
      return json({ error: "wrong passphrase" }, 401);
    }
    await env.KV.delete(rlKey);
    const exp = Math.floor(Date.now() / 1000) + SESSION_DAYS * 86400;
    const cookie = `s=${exp}.${await hmac(env.COOKIE_KEY, "v1." + exp)}; Path=/; Max-Age=${SESSION_DAYS * 86400}; HttpOnly; Secure; SameSite=Strict`;
    return json({ ok: true }, 200, { "Set-Cookie": cookie });
  }
  if (p === "/api/logout" && method === "POST") {
    return json({ ok: true }, 200, { "Set-Cookie": "s=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict" });
  }

  // ------------------------------------------------------------------ the phone (needs the session)
  if (!(await sessionOk(req, env))) return json({ error: "login required" }, 401);

  if (p === "/api/snapshot" && method === "GET") {
    const raw = await env.KV.get("snapshot");
    const cutoff = Date.now() - 14 * 86400 * 1000;
    const events = (await listEvents(env)).filter((e) => Date.parse(e.created) > cutoff);
    return json({ snapshot: raw ? JSON.parse(raw) : null, events });
  }

  if (p === "/api/detail" && method === "GET") {
    const id = url.searchParams.get("id") || "";
    const raw = await env.KV.get("details");
    const d = raw ? JSON.parse(raw).details[id] : null;
    return d ? json(d) : json({ error: "no details yet: they arrive with the next PC sync" }, 404);
  }

  if (p === "/api/decision" && method === "POST") {
    const b = await req.json();
    const kind = b.kind === "thesis" ? "thesis" : "job";
    const allowed = kind === "thesis" ? THESIS_ACTIONS : JOB_ACTIONS;
    if (!allowed.has(b.action)) return json({ error: "action not allowed" }, 400);
    const raw = await env.KV.get("snapshot");
    const snap = raw ? JSON.parse(raw) : { items: [] };
    if (!snap.items.some((i) => i.id === b.id && i.kind === kind)) return json({ error: "unknown role" }, 400);
    const ev = { id: "", item: String(b.id).slice(0, 160), kind, action: b.action, status: "pending", created: new Date().toISOString() };
    if (b.action === "applied") {
      if (b.date && !isDate(b.date)) return json({ error: "date must be YYYY-MM-DD" }, 400);
      ev.date = b.date || ev.created.slice(0, 10);
    }
    if (b.action === "note") {
      const note = String(b.note || "").trim().slice(0, 1000);
      if (!note) return json({ error: "note is empty" }, 400);
      ev.note = note;
    } else if (b.note) {
      ev.note = String(b.note).trim().slice(0, 1000);
    }
    ev.id = `ev:${String(Date.now()).padStart(15, "0")}:${b64u(crypto.getRandomValues(new Uint8Array(6)))}`;
    await env.KV.put(ev.id, JSON.stringify(ev), { expirationTtl: EVENT_TTL });
    return json({ ok: true, event: ev });
  }

  if (p === "/api/decision" && method === "DELETE") {
    const id = url.searchParams.get("ev") || "";
    if (!id.startsWith("ev:")) return json({ error: "bad id" }, 400);
    const raw = await env.KV.get(id);
    if (!raw) return json({ error: "not found" }, 404);
    if (JSON.parse(raw).status !== "pending") return json({ error: "the PC already handled it" }, 409);
    await env.KV.delete(id);
    return json({ ok: true });
  }

  return json({ error: "not found" }, 404);
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;
    if (!p.startsWith("/api/")) {
      const r = await env.ASSETS.fetch(req);
      const h = new Headers(r.headers);
      Object.entries(SEC).forEach(([k, v]) => h.set(k, v));
      h.set("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'");
      return new Response(r.body, { status: r.status, headers: h });
    }
    try {
      return await route(req, env, url, p);
    } catch (e) {
      return json({ error: "server error" }, 500);
    }
  },
};
