#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Onboarding helpers: everything about setting the toolkit up for one person that does not need judgment.

The judgment (reading a CV and inferring the person's field, asking the questions, researching a country) is done by Claude in a session, following
onboarding/README.md; this script does the mechanical parts around it and checks the result.

    python scripts/onboard.py status                      what is configured, what is missing
    python scripts/onboard.py extract <cv.pdf|docx|md|txt>   CV text -> profile/cv-source.txt (and prints it with a character count)
    python scripts/onboard.py init                        create profile/ with the empty profile.json and domain.json templates
    python scripts/onboard.py check [--profile-dir DIR]   validate profile.json, domain.json and the region packs; exit 1 on errors
    python scripts/onboard.py scaffold-region <code> "<Country name>"   copy regions/_template to profile/regions/<code>/ for researching a new country
    python scripts/onboard.py build-sources               profile/sources.json from the employer directory and the domain's industries
    python scripts/onboard.py doctor                      which tools are installed, and what each missing one switches off
    python scripts/onboard.py demo [--example NAME]       analyse the fictional postings of an example profile; touches none of your data

Nothing here reads a mailbox or the network. The profile folder (profile/) is git-ignored: it is the person's data.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent

KINDS = ["thesis", "student_assistant", "working_student", "internship", "trainee", "entry", "mid", "senior"]
STAGES = ["student", "new_grad", "experienced", "career_change"]
ROLES = ["core", "bridge", "income", "other"]
FITS = ["core", "bridge", "none"]
EVIDENCE_STATUS = ["covered", "partial", "gap"]
AUTH_STATUSES = ["citizen", "permanent_resident", "unrestricted", "eu_citizen", "student_visa", "opt", "work_visa", "needs_sponsorship"]
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def profile_dir() -> Path:
    return Path(os.environ.get("JOBKIT_PROFILE_DIR") or (ROOT / "profile"))


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


# ----------------------------------------------------------------------------- extract

def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader  # type: ignore
        rd = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in rd.pages)
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:tab/>", "\t", xml)
        text = re.sub(r"<[^>]+>", "", xml)
        return (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))
    return path.read_text(encoding="utf-8-sig", errors="replace")


def cmd_extract(args) -> int:
    src = Path(args.file)
    if not src.exists():
        print(f"not found: {src}", file=sys.stderr)
        return 2
    text = re.sub(r"[ \t]+\n", "\n", extract_text(src))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    out = profile_dir() / "cv-source.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(f"{len(text)} characters from {src.name} -> {out}")
    if len(text) < 300:
        print("warning: very little text. A scanned PDF has no text layer: paste the CV text into profile/cv-source.txt by hand.", file=sys.stderr)
    return 0 if len(text) >= 300 else 1


# ----------------------------------------------------------------------------- init / templates

def cmd_init(args) -> int:
    pd = profile_dir()
    pd.mkdir(parents=True, exist_ok=True)
    made = []
    for name in ("profile.json", "domain.json"):
        dst = pd / name
        if dst.exists() and not args.force:
            continue
        shutil.copyfile(ROOT / "onboarding" / "templates" / f"{name.split('.')[0]}.template.json", dst)
        made.append(name)
    print(f"profile folder: {pd}")
    print("created: " + (", ".join(made) if made else "nothing (files exist; use --force to overwrite)"))
    return 0


# ----------------------------------------------------------------------------- check

def _compile(label: str, pattern: str, errors: list[str]) -> None:
    try:
        re.compile(pattern)
    except re.error as e:
        errors.append(f"{label}: invalid regular expression ({e}): {pattern[:80]}")


def validate(pdir: Path | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors would break or mislead the analysis; warnings are things worth a look."""
    pdir = pdir or profile_dir()
    errors: list[str] = []
    warns: list[str] = []
    prof = read_json(pdir / "profile.json")
    dom = read_json(pdir / "domain.json")
    if prof is None:
        errors.append(f"{pdir / 'profile.json'} is missing or is not valid JSON")
        prof = {}
    if dom is None:
        errors.append(f"{pdir / 'domain.json'} is missing or is not valid JSON")
        dom = {}
    # ---- profile
    if not prof.get("name"):
        errors.append("profile.name is empty")
    if not EMAIL.match(prof.get("email") or ""):
        errors.append("profile.email is missing or not an address (it is where the digest is sent, to you only)")
    if prof.get("career_stage") not in STAGES:
        errors.append(f"profile.career_stage must be one of {STAGES}")
    sought = prof.get("levels_sought") or []
    if not sought:
        warns.append("profile.levels_sought is empty: the career stage's default kinds are used")
    for k in sought:
        if k not in KINDS:
            errors.append(f"profile.levels_sought: unknown kind '{k}' (kinds: {KINDS})")
    regions = ([prof.get("region")] if prof.get("region") else []) + list(prof.get("regions") or [])
    if not regions:
        errors.append("profile.regions is empty: name the region pack(s), home market first (e.g. [\"de\", \"eu\"] or [\"us\"])")
    for c in regions:
        if not ((ROOT / "regions" / c / "region.json").exists() or (pdir / "regions" / c / "region.json").exists()):
            errors.append(f"region pack '{c}' not found in regions/ or {pdir / 'regions'} (scaffold one: onboard.py scaffold-region)")
    langs = prof.get("languages") or []
    if not langs:
        errors.append("profile.languages is empty: list every language with a level (a1-c2 or native); the analysis compares postings against these")
    codes = set()
    sys.path.insert(0, str(ROOT / "scripts"))
    from config import LEVELS  # noqa: E402
    for x in langs:
        if not x.get("code"):
            errors.append("profile.languages: an entry has no code")
        codes.add((x.get("code") or "").lower())
        if str(x.get("level", "")).lower() not in LEVELS[1:]:
            errors.append(f"profile.languages: level '{x.get('level')}' for {x.get('code')} must be one of {LEVELS[1:]}")
    if "en" not in codes:
        warns.append("profile.languages has no English entry: postings that ask for English are then treated as a wall")
    wa = (prof.get("work_authorization") or {}).get("status")
    if wa not in AUTH_STATUSES:
        errors.append(f"profile.work_authorization.status must be one of {AUTH_STATUSES}")
    if not prof.get("document_language"):
        warns.append("profile.document_language is unset: CVs and letters default to English")
    if not prof.get("cities") and not prof.get("remote_ok", True):
        warns.append("profile has no preferred cities and remote_ok is false: no role gets a location point")
    # ---- domain
    cats = {c.get("id"): c for c in dom.get("categories") or []}
    if not cats:
        errors.append("domain.categories is empty")
    for cid, c in cats.items():
        if c.get("fit") not in FITS:
            errors.append(f"domain.categories[{cid}].fit must be one of {FITS}")
    if cats and not any(c.get("fit") == "core" for c in cats.values()):
        errors.append("domain.categories needs at least one category with fit 'core' (the person's own field)")
    subs = dom.get("subfields") or []
    if not subs:
        errors.append("domain.subfields is empty: infer the person's fields from their CV (onboarding/README.md)")
    ids = set()
    for s in subs:
        sid = s.get("id")
        if not sid or sid in ids:
            errors.append(f"domain.subfields: missing or duplicate id '{sid}'")
        ids.add(sid)
        if s.get("category") not in cats:
            errors.append(f"domain.subfields[{sid}].category '{s.get('category')}' is not a category")
        if s.get("role") not in ROLES:
            errors.append(f"domain.subfields[{sid}].role must be one of {ROLES}")
        if not s.get("terms"):
            errors.append(f"domain.subfields[{sid}] has no terms: nothing can ever classify into it")
        for t in s.get("terms") or []:
            _compile(f"domain.subfields[{sid}].terms", t, errors)
        if s.get("core_if_re"):
            _compile(f"domain.subfields[{sid}].core_if_re", s["core_if_re"], errors)
        if not 1 <= int(s.get("weight", 3)) <= 5:
            errors.append(f"domain.subfields[{sid}].weight must be 1 to 5")
        if s.get("role") in ("core", "bridge") and not s.get("aliases"):
            warns.append(f"domain.subfields[{sid}] has no aliases: the watches cannot tell this field from a title")
    if subs and not any(s.get("role") == "core" for s in subs):
        errors.append("domain.subfields needs at least one 'core' sub-field")
    for e in dom.get("cv_evidence") or []:
        if e.get("status") not in EVIDENCE_STATUS:
            errors.append(f"domain.cv_evidence[{e.get('term')}].status must be one of {EVIDENCE_STATUS}")
        if not e.get("re"):
            errors.append(f"domain.cv_evidence[{e.get('term')}] has no regular expression")
        else:
            _compile(f"domain.cv_evidence[{e.get('term')}]", e["re"], errors)
    if not dom.get("cv_evidence"):
        warns.append("domain.cv_evidence is empty: no posting is compared with the CV")
    for p in dom.get("penalty_subfields") or []:
        if p.get("subfield") not in ids:
            errors.append(f"domain.penalty_subfields: '{p.get('subfield')}' is not a sub-field")
    for key in ("industry_regex", "income_context_re"):
        if dom.get(key):
            _compile(f"domain.{key}", dom[key] if isinstance(dom[key], str) else "|".join(dom[key]), errors)
    for w in (dom.get("walls") or []) + (prof.get("walls") or []):
        if not w.get("label") or not w.get("re"):
            errors.append(f"a wall needs a label and a re: {w}")
        else:
            _compile(f"wall '{w['label']}'", w["re"], errors)
    if not dom.get("search_terms"):
        warns.append("domain.search_terms is empty: the board queries fall back to the labels of the core sub-fields")
    if not dom.get("priority_employers"):
        warns.append("domain.priority_employers is empty: no employer gets the priority point")
    # ---- region packs
    for c in regions:
        rp = ROOT / "regions" / c / "region.json"
        rp = rp if rp.exists() else pdir / "regions" / c / "region.json"
        reg = read_json(rp, {}) or {}
        if not reg.get("scope_countries") and not reg.get("primary_countries") and c not in ("eu",):
            errors.append(f"region pack {c}: no primary_countries or scope_countries")
        for i, r in enumerate(reg.get("route_rules") or []):
            if "adj" not in r or "route" not in r:
                errors.append(f"region {c} route_rules[{i}] needs adj and route")
            for k in ("employer_re", "url_re", "text_re", "not_text_re"):
                if (r.get("when") or {}).get(k):
                    _compile(f"region {c} route_rules[{i}].{k}", r["when"][k], errors)
        for w in reg.get("walls") or []:
            _compile(f"region {c} wall '{w.get('label')}'", w.get("re") or "", errors)
    return errors, warns


def cmd_check(args) -> int:
    if args.profile_dir:
        os.environ["JOBKIT_PROFILE_DIR"] = args.profile_dir
    errors, warns = validate(Path(args.profile_dir) if args.profile_dir else None)
    for w in warns:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR:   {e}")
    print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
    return 1 if errors else 0


# ----------------------------------------------------------------------------- status

def cmd_status(args) -> int:
    import config
    cfg = config.get()
    pd = profile_dir()
    print(f"profile folder : {pd}")
    for name in ("profile.json", "domain.json", "cv-source.txt", "master-profile.md", "sources.json"):
        print(f"  {name:20} {'ok' if (pd / name).exists() else 'missing'}")
    masters = sorted(p.name for p in pd.glob("master-cv-*.md")) if pd.exists() else []
    print(f"  master CVs           {', '.join(masters) or 'none yet'}")
    print(json.dumps(cfg.summary(), indent=1, ensure_ascii=False))
    errors, _ = validate()
    print("configuration valid:", "yes" if not errors else f"no ({len(errors)} errors: run `onboard.py check`)")
    return 0 if cfg.configured and not errors else 1


# ----------------------------------------------------------------------------- scaffold a new region pack

def cmd_scaffold(args) -> int:
    code = args.code.lower()
    dst = profile_dir() / "regions" / code
    if dst.exists() and not args.force:
        print(f"{dst} exists (use --force to overwrite)", file=sys.stderr)
        return 1
    shutil.copytree(ROOT / "regions" / "_template", dst, dirs_exist_ok=True)
    rp = dst / "region.json"
    reg = read_json(rp, {})
    reg.update({"code": code, "name": args.name})
    write_json(rp, reg)
    print(f"created {dst}\nNext: research the country as described in rules/regions.md and fill region.json, legal.md and cv-conventions.md.")
    return 0


# ----------------------------------------------------------------------------- build sources

def cmd_build_sources(args) -> int:
    import config
    cfg = config.get()
    directory = config.resource("employers.json", {}).get("employers", [])
    want = {t.lower() for t in (cfg.domain.get("industries") or [])}
    chosen = [e for e in directory if want & {t.lower() for t in e.get("tags", [])}] if want else []
    out = read_json(profile_dir() / "sources.json", {}) or {}
    out.setdefault("workday", [])
    out.setdefault("ats", [])
    have = {(w.get("tenant") or w.get("slug")) for w in out["workday"] + out["ats"]}
    added = []
    for e in chosen:
        key = e.get("tenant") or e.get("slug")
        if key in have:
            continue
        have.add(key)
        if e["adapter"] == "workday":
            out["workday"].append({"institution": e["name"], "tenant": e["tenant"], "wd": e["wd"], "site": e["site"]})
        else:
            item = {"adapter": e["adapter"], "institution": e["name"], "slug": e["slug"]}
            if e.get("terms"):
                item["terms"] = e["terms"]
            out["ats"].append(item)
        added.append(e["name"])
    out["workday_terms"] = out.get("workday_terms") or (cfg.search_terms()[:6] + (["intern", "internship"] if cfg.student_stage else []))
    write_json(profile_dir() / "sources.json", out)
    print(f"industries in the domain: {sorted(want) or 'none set (domain.industries)'}")
    print(f"added {len(added)} employers from resources/employers.json: {', '.join(added) or 'none'}")
    print("For employers not in the directory follow rules/employers.md, then add them to profile/sources.json.")
    return 0


# ----------------------------------------------------------------------------- doctor

def _have(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def cmd_doctor(args) -> int:
    rows = []

    def add(name, ok, needed_for, how):
        rows.append((name, ok, needed_for, how))

    add("Python 3.10+", sys.version_info >= (3, 10), "everything", "install Python 3.10 or newer")
    for mod, pkg in (("requests", "requests"), ("bs4", "beautifulsoup4"), ("lxml", "lxml"), ("dateutil", "python-dateutil"), ("flask", "flask"), ("pypdf", "pypdf")):
        add(f"python: {pkg}", _have(mod), "watches, intake, dashboard, CV text extraction", "pip install -r requirements.txt")
    add("python: google-api-python-client", _have("googleapiclient") and _have("google_auth_oauthlib"), "Gmail: replies to applications, alert mail, the digest e-mail",
        "pip install -r requirements.txt, then see docs/GMAIL.md")
    add("python: playwright", _have("playwright"), "reading LinkedIn / Xing postings (rendered browser)", "pip install playwright && playwright install chromium")
    add("node.js", bool(_which("node")), "building the CV and letter (.docx)", "install Node.js 18+, then `npm install`")
    add("node: docx package", (ROOT / "node_modules" / "docx").exists(), "building the CV and letter (.docx)", "npm install")
    add("bash", bool(_which("bash")), "scripts/ship-package.sh (the CV quality gate)", "on Windows install Git for Windows (Git Bash)")
    add("LibreOffice", bool(_which("soffice", "libreoffice")) or any(Path(p).exists() for p in (r"C:\Program Files\LibreOffice\program\soffice.exe", "/Applications/LibreOffice.app/Contents/MacOS/soffice")),
        "PDF versions of the CV and letter (the .docx still builds without it)", "install LibreOffice")
    add("Gmail credentials", (ROOT / "config" / "gmail_credentials.json").exists(), "Gmail pass and the digest e-mail", "docs/GMAIL.md")
    add("Cloudflare wrangler (npx)", bool(_which("npx")), "the phone inbox (optional)", "install Node.js; docs/PHONE.md")
    pd = profile_dir()
    add("profile/profile.json", (pd / "profile.json").exists(), "everything: it says who you are", "run /start")
    add("profile/domain.json", (pd / "domain.json").exists(), "scoring and classification", "run /start")
    print(f"{'':4}{'tool':38}{'what it switches on':58}fix")
    bad = 0
    for name, ok, needed, how in rows:
        mark = "ok" if ok else "--"
        print(f"{mark:4}{name:38}{needed[:56]:58}{'' if ok else how}")
        bad += 0 if ok else 1
    core_missing = [n for n, ok, _, _ in rows if not ok and n.startswith(("Python", "python: requests", "python: beautifulsoup4", "python: lxml", "python: flask"))]
    print(f"\n{bad} item(s) missing; the core (Python and its packages) is {'complete' if not core_missing else 'NOT complete: ' + ', '.join(core_missing)}.")
    print("Optional tools only switch their own feature off: the watches, intake, analysis and dashboard run without them.")
    return 1 if core_missing else 0


# ----------------------------------------------------------------------------- demo

def cmd_demo(args) -> int:
    ex_dir = ROOT / "examples" / args.example
    if not (ex_dir / "profile.json").exists():
        names = sorted(p.name for p in (ROOT / "examples").iterdir() if (p / "profile.json").exists()) if (ROOT / "examples").exists() else []
        print(f"example '{args.example}' not found; available: {names}", file=sys.stderr)
        return 2
    # the configuration is read at import time from JOBKIT_PROFILE_DIR, so run the analysis in a child process pointed at the example
    env = {**os.environ, "JOBKIT_PROFILE_DIR": str(ex_dir)}
    code = (
        "import json,sys,pathlib;sys.path.insert(0,r'%s');import analyze,config;cfg=config.get();"
        "out=[];\n"
        "for f in sorted(pathlib.Path(r'%s').glob('*.md')):\n"
        "    t=f.read_text(encoding='utf-8');head=t.split('\\n---\\n',1);meta={};body=t\n"
        "    if len(head)==2:\n"
        "        for line in head[0].splitlines():\n"
        "            if ':' in line: k,v=line.split(':',1);meta[k.strip().lower()]=v.strip()\n"
        "        body=head[1]\n"
        "    row={'title':meta.get('title',f.stem),'employer':meta.get('employer',''),'location':meta.get('location',''),'country':meta.get('country','ZZ'),'url':meta.get('url',''),'source':'demo'}\n"
        "    a=analyze.analyze_text(row,body)\n"
        "    out.append({'file':f.name,'title':row['title'],'country':row['country'],'kind':a['kind'],'category':a['category'],'subfield':a['subfield'],'score':a['score'],'verdict':a['verdict'],'route':a['work_route'],'walls':[w['wall'] for w in a['walls']],'reason':a['reason']})\n"
        "print(json.dumps(out))" % (str(ROOT / "scripts"), str(ex_dir / "postings"))
    )
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return 1
    rows = json.loads(r.stdout)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    prof = read_json(ex_dir / "profile.json", {})
    print(f"Example '{args.example}': {prof.get('name')} ({prof.get('career_stage')}, regions {prof.get('regions')}, authorization {prof['work_authorization']['status']})\n")
    for x in rows:
        print(f"{x['verdict']:8} score {x['score']:>2}  {x['title'][:62]:62} {x['country']} {x['kind']}")
        print(f"         {x['category']}/{x['subfield']}  route {x['route']}" + (f"  WALL: {'; '.join(x['walls'])}" if x['walls'] else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    e = sub.add_parser("extract")
    e.add_argument("file")
    i = sub.add_parser("init")
    i.add_argument("--force", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--profile-dir")
    s = sub.add_parser("scaffold-region")
    s.add_argument("code")
    s.add_argument("name")
    s.add_argument("--force", action="store_true")
    sub.add_parser("build-sources")
    sub.add_parser("doctor")
    d = sub.add_parser("demo")
    d.add_argument("--example", default="de-bioinformatics-student")
    d.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    return {"status": cmd_status, "extract": cmd_extract, "init": cmd_init, "check": cmd_check, "scaffold-region": cmd_scaffold, "build-sources": cmd_build_sources,
            "doctor": cmd_doctor, "demo": cmd_demo}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
