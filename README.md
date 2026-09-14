# Job Finder Assistant

A personal, Dockerized job crawler for **Paraskevas Lysikatos**. It crawls job boards
across **Germany, Austria, Netherlands, Switzerland, Greece and Malta**, scores every posting
against your real skill profile, and hands you a ranked HTML report of **apply URLs**
for the jobs that actually fit.

Everything you would want to tweak lives in **`preference.json`** — skills, the match
threshold, how fresh a posting must be, which countries, which job titles to skip.

---

## Quick start

```bash
# 1. (optional) add API keys - the scrapers work without any keys
cp .env.example .env          # then paste your Adzuna / Jooble keys

# 2. build once
docker compose build

# 3. crawl
docker compose run --rm job-finder
```

When it finishes, open **`output/report_latest.html`** in your browser. Every row has an
**Apply ↗** button linking to the original posting.

> First run takes roughly **10–25 minutes** — it is crawling 6 countries × 6 search terms
> across several boards, with polite delays so the boards don't rate-limit you.

---

## How it works

```
preference.json ─┐
resume html ─────┴─► crawl 5 sources across 6 countries ─► dedupe ─► filter ─► score vs your skills ─► report
                       │                  │         │              │
                   Indeed/LinkedIn/    same job   too old,      skill coverage %
                   Google/Adzuna/      from 2     senior title,
                   Jooble              boards     wrong language
                                       = 1 row
```

### 1. Crawl

| Source | Countries | Key needed | Notes |
|---|---|---|---|
| Indeed | all 6 | no | biggest volume |
| LinkedIn Jobs | all 6 | no | rate-limits easily → smaller batches, auto-skipped after 2 failures |
| Google Jobs | all 6 | no | aggregates many small boards |
| Adzuna | DE, AT, NL, CH | yes (free) | no Greek or Maltese market |
| Jooble | all 6 | yes (free) | 500 requests **lifetime** per key → used sparingly |

Indeed / LinkedIn / Google are scraped with [JobSpy](https://github.com/speedyapply/JobSpy).
Every source is **fail-soft**: if one breaks or is rate-limited, it logs a warning and the
run continues with the others.

### 2. Deduplicate

The same job usually appears on several boards. Postings are merged on
`company + title + country`, keeping the **best link** (a company's own careers page beats
an aggregator redirect), the longest description, and the earliest posting date. The report's
*Source* column shows every board a job was found on.

German ads carry gender markers — `(m/w/d)`, `(f/m/x)` — that differ between boards, so those
are ignored when comparing titles. **Remote** roles are additionally merged *across* countries,
because one pan-European job gets listed separately under Germany, the Netherlands and
Switzerland; the row then lists all three. On-site roles deliberately keep the country in the
key: the same title at the same company in Berlin and in Athens really are two different jobs.

### 3. Filter (before scoring)

A posting is dropped if it is **too old**, its title contains an **excluded keyword**
(`senior`, `lead`, `praktikum`, …), it is written in a **language you don't read**, or it
conflicts with your **remote policy**. The console prints how many were dropped for each reason.

### 4. Score — what "70% match" means

The scorer detects which technologies an ad asks for (via `src/matching/taxonomy.py`,
which knows that *Nuxt* implies Vue, *Postgres* = *PostgreSQL*, and so on). Then:

| For each skill the ad asks for | Credit |
|---|---|
| you know it well (proficiency ≥ `strong_skill_threshold`, default 0.5) | **1.0** |
| you know it a little (proficiency above 0 but below that) | **0.5** |
| you don't have it | **0** |

```
match % = total credit ÷ number of skills the ad asks for × 100
```

So **75% means you cover three quarters of the stack that ad asks for.** When two jobs tie,
the one matching your *stronger* skills ranks higher.

**Worked example** — an ad mentioning PHP, Laravel, Vue, MySQL, Docker:
you know the first four well (4 × 1.0) and not Docker (0) → 4 ÷ 5 = **80% ✅**

An ad mentioning Java, Spring Boot, Kafka, Kubernetes, Azure:
Java and Spring are weak (2 × 0.5), the rest unknown → 1 ÷ 5 = **20% ❌**

Ads where fewer than `min_detected_skills` (default 2) technologies are recognizable
can't be scored fairly — usually very short or vague ads. They are **not** thrown away;
they go to the report's *Low confidence* section so you can eyeball them.

**Read the percentage together with the "skills in ad" count** shown under it. A short ad
mentioning only *PHP* and *Laravel* scores 100%, but on two keywords — much weaker evidence
than 90% across a dozen. That is why equal scores are ranked by how much the ad actually
revealed, and only then by how strong those skills are for you.

### 5. Report

`output/` gets three files:

- **`report_latest.html`** — always the newest run. Sortable columns, live text filter,
  colour-coded skill chips (green = you know it, amber = half credit, red = missing),
  and an **Apply ↗** button per job. Works in light and dark mode.
- `report_<date>.html` — dated copy, so you keep a history.
- `jobs_<date>.csv` — same data for Excel / Google Sheets.

Jobs are split into **Matches ≥ threshold**, **Near misses** (within 15 points — worth a
glance, or a hint to tune your skills list), and **Low confidence**.

### 6. Repeat runs only show new jobs

Every reported job is remembered in `data/jobs.db` (SQLite). The next run marks fresh
postings **NEW** and hides ones you have already seen, so a daily run is a short list of
genuinely new opportunities. Use `--all` to see everything again.

---

## `preference.json` reference

### `search`

| Field | Default | What it does |
|---|---|---|
| `terms` | 6 dev titles | Search queries sent to each board. More terms = more coverage = slower. |
| `countries` | all 6 | Any of `germany`, `austria`, `netherlands`, `switzerland`, `greece`, `malta`. |
| `posted_within_days` | `14` | **Your date range.** Only postings this fresh. |
| `results_per_term` | `40` | Cap per term per country on Indeed/Google. |
| `linkedin_results_per_term` | `10` | Kept low on purpose — LinkedIn blocks aggressive scraping. |
| `sources` | all 5 sources | Drop entries to disable, e.g. remove `"jobspy_linkedin"` if it keeps failing. |
| `remote_policy` | `include` | `include` (on-site + remote), `only` (remote jobs only), `exclude`. |
| `jooble_terms` | 2 broad queries | Separate, deliberately short list — Jooble keys allow only 500 requests ever. |

### `matching`

| Field | Default | What it does |
|---|---|---|
| `min_match_percent` | `70` | **Your 70% threshold.** Lower it to ~60 if results are thin. |
| `min_detected_skills` | `2` | Below this many recognized skills, an ad goes to *Low confidence*. |
| `strong_skill_threshold` | `0.5` | Proficiency at or above this counts as full credit; below it, half. |
| `languages_ok` | `en, de, el` | Language the **ad is written in** (ISO codes). Add `nl` only if you learn Dutch. |
| `german_requirement` | `low` | How much German the **job** may demand — see below. |
| `exclude_title_keywords` | senior/lead/intern/… | Titles containing any of these are skipped. Includes German terms (`Werkstudent`, `Ausbildung`). |
| `skills` | seeded from your resume | `name` must be a canonical skill from `src/matching/taxonomy.py`; `proficiency` is 0–1. |

#### Working in English: `german_requirement`

`languages_ok` is about the language an ad is *written in*; `german_requirement` is about how
much German the *job* actually demands. They are independent — plenty of German-language ads
are for teams that work in English, and plenty of English ads still want fluent German.

| Value | Effect |
|---|---|
| `any` | No language-requirement filtering. |
| `low` *(current)* | Drops ads demanding German **above ~B2** — "fließend Deutsch", "verhandlungssicher", "sehr gute Deutschkenntnisse", "Deutsch C1", "fluent/native German". Ordinary "gute Deutschkenntnisse" (≈B2) is **kept**, since that is workable for you. |
| `none` | Strictly English-workable: the above, plus any ad not in English plus not stating English suffices. |

Jobs that say outright that English is enough — "English is our working language", "no German
required" — get an **EN OK** badge in the report. That statement also overrides a boilerplate
fluent-German line elsewhere in the same ad, so those jobs are never wrongly dropped.

The phrase lists live in `src/matching/scorer.py` (`GERMAN_FLUENCY`, `ENGLISH_FRIENDLY`) if you
want to tune the wording.

**Tuning your skills is the highest-leverage edit.** If jobs you like keep landing in *Near
misses*, look at the red chips: those are the skills costing you points. Add ones you
actually have, or raise a proficiency you undersold.

Refresh the list from the resume at any time with:

```bash
docker compose run --rm job-finder --seed-skills
```

Values you edited by hand are preserved; only genuinely new skills are appended.

> **Note on the seeded profile:** `rest` (REST APIs) was added at `0.8` because your
> current role — Laravel middleware bridging a backend to a mobile app — is REST API work,
> even though the resume never uses the words. Nearly every ad asks for it, so leaving it
> out would depress every score. Remove it if you disagree. Skills like `docker` and
> `linux` were deliberately **not** added since the resume shows no evidence — add them
> yourself if you have the experience, as they appear in a lot of DACH ads.

---

## Command-line options

```bash
docker compose run --rm job-finder                     # normal run, new jobs only
docker compose run --rm job-finder --all               # include jobs seen in earlier runs
docker compose run --rm job-finder --min-match 60      # one-off looser threshold
docker compose run --rm job-finder --days 30           # one-off wider date range
docker compose run --rm job-finder --max-per-term 10   # quick test run
docker compose run --rm job-finder --self-test         # offline check, no network needed
docker compose run --rm job-finder --seed-skills       # refresh skills from the resume
```

Flags override `preference.json` for that run only; they never rewrite the file.

---

## API keys (both optional)

**Adzuna** — covers DE, AT, NL, CH. Register at
[developer.adzuna.com](https://developer.adzuna.com/) (instant, free, ~1000 calls/month).
Put `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env`.

**Jooble** — covers all 6 countries, including **Greece and Malta**, which Adzuna lacks. A Jooble key
is **tied to the domain you registered it on**. Two ways to set it up:

- *One key* registered at [jooble.org](https://jooble.org/api/about) → put it in `.env` as
  `JOOBLE_KEY`. It is used for every country, with the country name as the search location.
- *Per-country keys* from [de](https://de.jooble.org/api/about) ·
  [at](https://at.jooble.org/api/about) · [nl](https://nl.jooble.org/api/about) ·
  [ch](https://ch.jooble.org/api/about) · [gr](https://gr.jooble.org/api/about) ·
  [mt](https://mt.jooble.org/api/about) → put them in as `JOOBLE_KEY_DE`, `JOOBLE_KEY_AT`, …
  for slightly better local coverage.

The tool tries the regional domain first and automatically falls back to the main one, so
either setup works. Each free key allows **500 requests total, ever** — this tool spends only
2 per country per run (~50 full runs).

Missing keys are not an error: the source simply prints a note and is skipped.

---

## Troubleshooting

**`[jobspy] … LinkedIn … FAILED` / few LinkedIn results** — LinkedIn rate-limits hard. The
tool backs off and skips LinkedIn after two failures. Re-run later, lower
`linkedin_results_per_term`, or remove `"jobspy_linkedin"` from `sources`.

**No matches at all** — check the console's filter breakdown first. Common causes: the date
range is too tight (raise `posted_within_days`), or your skills list is missing things ads
ask for (check the red chips in the *Near misses* section). Try
`--min-match 55 --days 30 --all` to sanity-check the pipeline.

**Everything lands in "Low confidence"** — descriptions weren't fetched (a board changed its
markup, or Adzuna truncated them). Those ads still have working apply links.

**Docker created a *folder* called `preference.json`** — that happens if the file was missing
when the container started. Delete the folder and restore the file:
`rm -rf preference.json && docker compose run --rm job-finder --seed-skills`.

**Results skew German** — that's correct: German-language ads are included because you have
B2. Drop `"de"` from `languages_ok` for English-only postings.

---

## Project layout

```
preference.json          all your settings (edit this)
.env                     API keys (never committed)
src/
  main.py                CLI + pipeline orchestration
  config.py              loads preference.json + .env, validates them
  resume_parser.py       reads skills + proficiency out of the resume HTML
  dedupe.py              cross-board dedup + SQLite "already seen" store
  report.py              HTML + CSV + console output
  sources/               one module per job board
  matching/
    taxonomy.py          skill synonyms (Nuxt→vue, Postgres→postgresql, …)
    scorer.py            the match % and the filters
  templates/report.html.j2
output/                  generated reports (gitignored)
data/jobs.db             seen-jobs store (gitignored)
```

---

## Notes and limits

- **Your LinkedIn profile is not crawled.** It sits behind authentication and scraping it
  breaks LinkedIn's terms of service. Your skills come from the resume instead — and
  `preference.json` is yours to extend with anything else from your profile. LinkedIn
  **job listings** are crawled, which is the part that matters here.
- Matching is deterministic keyword coverage, not an LLM — it costs nothing, runs offline,
  and every score is explainable by the chips in the report. It can't understand
  "experience with a modern PHP framework" as meaning Laravel; add synonyms to
  `taxonomy.py` when you notice gaps.
- Be a good citizen: the crawler sleeps between requests. Don't run it in a tight loop.
- Possible next steps: schedule a daily run (Windows Task Scheduler), email/Telegram the
  new matches, or add a per-job "already applied" flag.
