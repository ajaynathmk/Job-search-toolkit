-- db/schema.sql
-- The tracker. One row per role. Created by `python scripts/db.py` (db/tracker.db is git-ignored: it is the owner's data).
--
-- my_notes is the owner's field. Nothing but the owner's own explicit input may ever write it:
-- scripts/db.py's update_job() refuses a my_notes write unless the caller passes source="owner".
-- Do not bypass that wrapper with a raw UPDATE against this table.

CREATE TABLE IF NOT EXISTS jobs (
    -- Identity
    id              TEXT PRIMARY KEY,   -- li-<id> / xi-<id> / xm-<token12> / w-<slug>
    title           TEXT NOT NULL,
    employer        TEXT NOT NULL,
    location        TEXT,
    country         TEXT NOT NULL DEFAULT 'ZZ',  -- ISO 3166-1 alpha-2; ZZ = unknown
    work_route      TEXT,               -- how the owner could legally take it (a region pack's route ids); see WORK_ROUTE_VALUES in scripts/db.py
    field           TEXT,               -- legacy free field
    track           TEXT,               -- legacy free field
    tier            INTEGER,            -- 1 or 2, set only after the JD is read
    score           INTEGER,            -- 0-10
    source          TEXT,               -- the board or feed it came from
    date_found      TEXT,               -- ISO date
    status          TEXT NOT NULL DEFAULT 'open',  -- open|applied|interview|rejected|skip

    -- Link
    url             TEXT,
    url_verified    TEXT,               -- ISO date, empty/NULL = unchecked
    ref_number      TEXT,

    -- Dates / urgency
    deadline        TEXT,
    start_window    TEXT,
    duration        TEXT,
    dates_checked   TEXT,
    action_by       TEXT,
    urgency_reason  TEXT,
    rolling         INTEGER NOT NULL DEFAULT 0,   -- boolean
    verify_needed   INTEGER NOT NULL DEFAULT 0,
    last_checked    TEXT,

    -- Workflow
    approval        TEXT NOT NULL DEFAULT 'none',  -- none|requested|prepared|recheck|blocked
    approved_at     TEXT,
    recheck_at      TEXT,
    blocked_reason  TEXT,
    package_path    TEXT,
    apply_channel   TEXT,
    apply_url       TEXT,

    -- Outcome
    applied_at      TEXT,
    closed_at       TEXT,
    status_source   TEXT,               -- "gmail <date>" or empty

    -- JD cache
    jd_read         INTEGER NOT NULL DEFAULT 0,
    jd_fetched_at   TEXT,
    jd_path         TEXT,               -- points at jd/<id>.md
    jd_lang         TEXT,               -- the posting's own language (en, de, fr, ...)
    lang_bar        TEXT,               -- the local-language requirement the analysis found, e.g. 'B2: fluent German'
    category        TEXT,               -- one of the categories in profile/domain.json
    subfield        TEXT,               -- sub-field id inside the category (profile/domain.json)
    verdict         TEXT,               -- APPLY | BACKUP | PLAN | LATER | PASS | BLOCKED | EXPIRED (rules/pipeline.md)
    verdict_reason  TEXT,
    cv_match        TEXT,               -- JSON: what the CV covers, partly covers, lacks (analyze.py)
    analysis_level  TEXT,               -- stub | auto | reviewed | legacy | unreadable
    analyzed_at     TEXT,
    jd_sha          TEXT,               -- hash of the cached JD that was analysed
    score_breakdown TEXT,               -- JSON components of the score
    score_history   TEXT,               -- JSON list of score changes with the reason
    score_flag      TEXT,               -- set when the score changed after it was written
    rule_version    TEXT,
    posted_at       TEXT,               -- the posting's own date, when the source gives it
    watch_id        TEXT,               -- id of the watch item this row came from
    language_bar    TEXT,               -- other languages the posting asks for, e.g. "French B2"
    jd_summary      TEXT,               -- <=120 words
    hard_reqs       TEXT,               -- JSON array of strings
    soft_reqs       TEXT,               -- JSON array of strings
    keywords        TEXT,               -- JSON array of {term,category,tier,pillar,frequency,source}
    constraints     TEXT,
    contact_name    TEXT,

    -- Notes
    notes           TEXT,               -- the run's findings, freely overwritable
    my_notes        TEXT,               -- OWNER ONLY. Automation code must never write this column.
    my_notes_at     TEXT,

    -- Optimistic concurrency
    version         INTEGER NOT NULL DEFAULT 1,

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_approval ON jobs(approval);
CREATE INDEX IF NOT EXISTS idx_jobs_action_by ON jobs(action_by);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_jd_read ON jobs(jd_read);

-- ---------------------------------------------------------------------------
-- thesis: thesis and research-project leads (for students). One row per opportunity: an advertised thesis,
-- a standing topic list, an "open call" (a group that says theses are regularly available), or an
-- unsolicited-approach lead. Holds the group and supervisor profile and the reasoned fit, not just the
-- posting. Written ONLY through scripts/db.py (create_thesis / update_thesis), which applies the same
-- my_notes guard and version pinning as the jobs table. Ignore it if you are not a student.
CREATE TABLE IF NOT EXISTS thesis (
    id              TEXT PRIMARY KEY,   -- th-<institution>-<slug>
    -- the posting, as it stands on the website
    title           TEXT NOT NULL,      -- exact title on the page (or "<Group>: thesis topics" for a list)
    institution     TEXT NOT NULL,      -- university / company / institute
    department      TEXT,               -- faculty / institute / chair
    group_name      TEXT,
    location        TEXT,
    country         TEXT NOT NULL DEFAULT 'ZZ',
    source_type     TEXT,               -- university|company|research_institute|board|other
    posting_kind    TEXT NOT NULL DEFAULT 'advertised',  -- advertised|topic_list|open_call|lead
    posting_url     TEXT,
    url_verified    TEXT,               -- ISO date the link was opened and read
    posted_at       TEXT,
    deadline        TEXT,
    start_window    TEXT,
    duration        TEXT,
    posting_text    TEXT,               -- verbatim excerpt of the real posting / page (what the site says)
    requirements    TEXT,               -- verbatim requirements, quoted
    language_bar    TEXT,
    -- the supervisor and the group's work (real information from their own pages)
    pi_name         TEXT,
    pi_title        TEXT,
    pi_email        TEXT,
    pi_page_url     TEXT,
    contact_name    TEXT,
    contact_email   TEXT,
    group_url       TEXT,
    group_summary   TEXT,               -- what the group does, from its website
    pi_work_summary TEXT,               -- the supervisor's research focus and methods
    publications    TEXT,               -- JSON array of {title, year, journal, pmid, relevance}
    -- fit for the owner
    pillar          TEXT,               -- a thesis pillar id from profile/domain.json, or other
    field           TEXT,
    track           TEXT,
    fit_score       INTEGER,            -- 0-10 content score
    route_adjustment INTEGER,           -- work-authorization adjustment from the region pack
    score           INTEGER,            -- fit_score + route_adjustment, clamped to 0-10
    fit_reasoning   TEXT,               -- why it fits, tied to master-profile evidence ids
    gaps            TEXT,               -- what the owner lacks for it
    -- legal
    work_route      TEXT,
    route_note      TEXT,
    -- workflow
    status          TEXT NOT NULL DEFAULT 'lead',  -- lead|outreach_drafted|outreach_sent|replied|interview|accepted|declined|closed
    outreach_draft_path TEXT,
    outreach_sent_at    TEXT,
    replied_at          TEXT,
    jd_path         TEXT,               -- cached page text under jd/
    source_ref      TEXT,               -- watch item id or sweep that found it
    last_checked    TEXT,
    notes           TEXT,
    my_notes        TEXT,               -- OWNER ONLY (same guard as jobs.my_notes)
    my_notes_at     TEXT,
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_thesis_status ON thesis(status);
CREATE INDEX IF NOT EXISTS idx_thesis_country ON thesis(country);
CREATE INDEX IF NOT EXISTS idx_thesis_pillar ON thesis(pillar);
