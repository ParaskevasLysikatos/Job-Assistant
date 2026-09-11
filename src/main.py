"""Job Finder Assistant - crawl job boards, score against your skills, report URLs.

Usage:
    python -m src.main                 # full crawl using preference.json
    python -m src.main --all           # include previously seen jobs in the report
    python -m src.main --min-match 60  # one-off threshold override
    python -m src.main --days 7        # one-off date-range override
    python -m src.main --self-test     # offline sanity check of the matching engine
    python -m src.main --seed-skills   # refresh preference.json skills from the resume
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from .config import PREFERENCE_FILE, PROJECT_ROOT, load_config
from .dedupe import SeenStore, dedupe, propagate_remote
from .matching.scorer import Scorer, ScoreResult, mark_remote
from .sources.base import JobPosting

OUTPUT_DIR = PROJECT_ROOT / "output"
DATA_DIR = PROJECT_ROOT / "data"


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="job-finder", description=__doc__)
    ap.add_argument("--all", action="store_true",
                    help="show previously seen jobs too (default: only NEW ones)")
    ap.add_argument("--min-match", type=float, default=None,
                    help="override matching.min_match_percent for this run")
    ap.add_argument("--days", type=int, default=None,
                    help="override search.posted_within_days for this run")
    ap.add_argument("--max-per-term", type=int, default=None,
                    help="override search.results_per_term for this run")
    ap.add_argument("--self-test", action="store_true",
                    help="run offline tests of the scorer and resume parser, then exit")
    ap.add_argument("--seed-skills", action="store_true",
                    help="re-extract skills from the resume into preference.json, then exit")
    return ap.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.min_match is not None:
        cfg.min_match_percent = args.min_match
    if args.days is not None:
        cfg.posted_within_days = args.days
    if args.max_per_term is not None:
        cfg.results_per_term = args.max_per_term

    print(f"Job Finder | countries: {', '.join(cfg.countries)} | "
          f"posted within {cfg.posted_within_days} days | "
          f"threshold {cfg.min_match_percent:.0f}% | sources: {', '.join(cfg.sources)}",
          flush=True)
    print(f"Search terms: {', '.join(cfg.terms)}", flush=True)

    # --- crawl ------------------------------------------------------------
    sources = []
    if any(s.startswith("jobspy_") for s in cfg.sources):
        from .sources.jobspy_source import JobSpySource
        sources.append(JobSpySource(cfg))
    if "adzuna" in cfg.sources:
        from .sources.adzuna import AdzunaSource
        sources.append(AdzunaSource(cfg))
    if "jooble" in cfg.sources:
        from .sources.jooble import JoobleSource
        sources.append(JoobleSource(cfg))

    postings: list[JobPosting] = []
    for source in sources:
        print(f"\n=== crawling: {source.name} ===", flush=True)
        try:
            postings += source.fetch()
        except Exception as e:  # a broken source must never kill the run
            print(f"[{source.name}] source failed entirely: {type(e).__name__}: {e}", flush=True)

    per_source = Counter(p.source for p in postings)
    print(f"\nCrawl finished: {len(postings)} postings "
          f"({', '.join(f'{s}: {n}' for s, n in per_source.most_common())})", flush=True)

    # --- dedup + filter + score ------------------------------------------
    for job in postings:
        mark_remote(job)          # before dedupe: it merges remote roles across countries
    propagate_remote(postings)
    unique = dedupe(postings)
    scorer = Scorer(
        skills=cfg.skills,
        min_detected_skills=cfg.min_detected_skills,
        exclude_title_keywords=cfg.exclude_title_keywords,
        languages_ok=cfg.languages_ok,
        posted_within_days=cfg.posted_within_days,
        remote_policy=cfg.remote_policy,
        strong_skill_threshold=cfg.strong_skill_threshold,
        german_requirement=cfg.german_requirement,
    )
    excluded: Counter = Counter()
    kept: list[tuple[JobPosting, ScoreResult]] = []
    for job in unique:
        outcome = scorer.filter(job)
        if not outcome.kept:
            excluded[outcome.reason] += 1
            continue
        kept.append((job, scorer.score(job)))

    # --- seen-store -------------------------------------------------------
    store = SeenStore(DATA_DIR / "jobs.db")
    known = store.known_keys()

    from .report import build_row, print_summary, write_reports
    near_floor = max(cfg.min_match_percent - 15, 0)
    sections: dict[str, list[dict]] = {"matches": [], "near": [], "unscoreable": []}
    hidden_seen = 0
    to_record = []
    for job, score in kept:
        if score.percent is None:
            section = "unscoreable"
        elif score.percent >= cfg.min_match_percent:
            section = "matches"
        elif score.percent >= near_floor:
            section = "near"
        else:
            continue  # far below threshold: not reported, and deliberately not
            # remembered either - lowering the threshold later must resurface it
        is_new = job.dedup_key() not in known
        to_record.append((job.dedup_key(), job.title, job.company, job.url, score.percent))
        if not args.all and not is_new:
            hidden_seen += 1
            continue
        sections[section].append(build_row(job, score, is_new))
    store.record(to_record)
    store.close()

    counts = {"crawled": len(postings), "unique": len(unique)}
    html_path, csv_path = write_reports(sections, counts, cfg, OUTPUT_DIR, show_seen=args.all)
    print_summary(sections, counts, dict(excluded), cfg, html_path, csv_path)
    if hidden_seen and not args.all:
        print(f"({hidden_seen} previously seen jobs hidden - run with --all to include them)",
              flush=True)
    return 0


# --------------------------------------------------------------------------
# Offline self-test: no network, no API keys needed.
# --------------------------------------------------------------------------

def run_self_test() -> int:
    from .matching.scorer import Scorer

    profile = {"php": 0.8, "laravel": 0.85, "vue": 0.85, "javascript": 0.8,
               "mysql": 0.75, "git": 0.8, "rest": 0.8, "java": 0.3, "aws": 0.25}
    scorer = Scorer(
        skills=profile, min_detected_skills=2,
        exclude_title_keywords=["senior", "lead", "head of"],
        languages_ok=["en", "de", "el"], posted_within_days=14, remote_policy="include",
        strong_skill_threshold=0.5,
    )

    def job(title, desc, days_ago=1):
        return JobPosting(title=title, company="ACME", location="Berlin",
                          country="germany", url="https://example.com/j/1",
                          source="test", description=desc,
                          date_posted=date.today() - timedelta(days=days_ago))

    results: list[tuple[str, bool]] = []

    laravel_job = job("PHP Developer",
                      "We build web apps with PHP 8, Laravel, Vue.js and MySQL. "
                      "You will design REST APIs and use Git daily in our Berlin team.")
    s = scorer.score(laravel_job)
    results.append((f"Laravel job scores >= 70 (got {s.percent})",
                    s.percent is not None and s.percent >= 70))

    java_job = job("Backend Engineer",
                   "Java services with Spring Boot, Kafka and Kubernetes, deployed on "
                   "Azure. Experience with Scala is a plus for our data pipelines.")
    s = scorer.score(java_job)
    results.append((f"Java/K8s job scores < 70 (got {s.percent})",
                    s.percent is not None and s.percent < 70))

    vague_job = job("Software Developer",
                    "Join our great agile team and work on exciting products!")
    s = scorer.score(vague_job)
    results.append((f"Vague job is unscoreable (got {s.percent})", s.percent is None))

    # Weak skills (proficiency below strong_skill_threshold) earn half credit.
    mixed_job = job("Web Developer",
                    "Our stack is PHP and Laravel on the backend, with some Java "
                    "services and Kubernetes on the side.")
    s = scorer.score(mixed_job)
    results.append((
        f"Partial credit: java weak -> {s.percent}% "
        f"(strong={sorted(s.matched)}, weak={sorted(s.partial)}, none={sorted(s.missing)})",
        "java" in s.partial and "kubernetes" in s.missing and s.percent == 62.5))

    senior = job("Senior PHP Developer", "PHP and Laravel every day.")
    out = scorer.filter(senior)
    results.append((f"'Senior' title filtered (reason={out.reason})",
                    not out.kept and out.reason == "senior_title"))

    quer = Scorer(skills=profile, min_detected_skills=2,
                  exclude_title_keywords=["quereinsteiger"], languages_ok=["en", "de", "el"],
                  posted_within_days=14)
    career_changer = job("Frontend Development mit KI - auch für Quereinsteiger (m/w/d)",
                         "PHP und Laravel.")
    results.append(("Career-changer ('Quereinsteiger') title filtered",
                    not quer.filter(career_changer).kept))

    german = job("PHP Entwickler (m/w/d)",
                 "Wir suchen einen PHP Entwickler mit Laravel und Vue.js Erfahrung "
                 "fuer unser Team in Berlin. Du arbeitest mit MySQL und Git in einem "
                 "agilen Umfeld und entwickelst moderne Webanwendungen.")
    out = scorer.filter(german)
    results.append((f"German posting allowed (lang={out.language or '?'})", out.kept))

    dutch = job("PHP Ontwikkelaar",
                "Wij zoeken een gedreven PHP ontwikkelaar met ervaring in Laravel en "
                "Vue.js. Je werkt samen met ons gezellige team in Amsterdam aan mooie "
                "webapplicaties en koppelingen met externe systemen.")
    out = scorer.filter(dutch)
    results.append((f"Dutch posting excluded (lang={out.language or '?'})",
                    not out.kept and out.reason == "language"))

    old = job("PHP Developer", "PHP and Laravel every day, join our MySQL loving team.",
              days_ago=60)
    out = scorer.filter(old)
    results.append((f"60-day-old posting excluded (reason={out.reason})",
                    not out.kept and out.reason == "too_old"))

    remote = job("PHP Developer",
                 "Work with PHP and Laravel, fully remote within the EU. MySQL a plus.")
    scorer.filter(remote)
    results.append(("Remote heuristic sets is_remote flag", remote.is_remote))

    # German requirement: "low" keeps ads that need workable German, drops the
    # ones demanding fluency, and respects an explicit English-first statement.
    de_scorer = Scorer(
        skills=profile, min_detected_skills=2, languages_ok=["en", "de", "el"],
        posted_within_days=14, german_requirement="low", strong_skill_threshold=0.5,
    )
    fluent = job("PHP Developer", "PHP und Laravel. Wir erwarten verhandlungssicheres "
                                  "Deutsch und Erfahrung mit MySQL.")
    out = de_scorer.filter(fluent)
    results.append((f"Ad demanding fluent German excluded (reason={out.reason})",
                    not out.kept and out.reason == "german_required"))

    ok_german = job("PHP Developer", "PHP and Laravel with MySQL. Gute Deutschkenntnisse "
                                     "sind von Vorteil, English is our working language.")
    out = de_scorer.filter(ok_german)
    results.append((f"B2-level German ad kept, flagged EN-friendly "
                    f"(english_friendly={ok_german.english_friendly})",
                    out.kept and ok_german.english_friendly))

    # An "English is our working language" line must win over a boilerplate
    # fluent-German line elsewhere in the same ad.
    mixed_lang = job("Backend Developer",
                     "PHP, Laravel and MySQL. Fluent German is a plus, but English is "
                     "our working language and no German is required to join.")
    out = de_scorer.filter(mixed_lang)
    results.append((f"English-first ad survives its fluent-German line", out.kept))

    en_only = Scorer(skills=profile, min_detected_skills=2, languages_ok=["en", "de", "el"],
                     posted_within_days=14, german_requirement="none",
                     strong_skill_threshold=0.5)
    german_ad = job("PHP Entwickler", "Wir suchen einen Entwickler mit PHP und Laravel "
                                      "Erfahrung fuer unser Team in Berlin. Du arbeitest "
                                      "mit MySQL in einem agilen Umfeld und entwickelst "
                                      "moderne Webanwendungen fuer unsere Kunden.")
    out = en_only.filter(german_ad)
    results.append((f"german_requirement=none drops a German-language ad "
                    f"(reason={out.reason})", not out.kept))

    # Dedup keys: gender markers must be ignored, tech slashes must survive,
    # and company-less postings must stay distinct.
    a = job("PHP Developer (m/w/d)", "x")
    b = job("PHP Developer", "x")
    results.append((f"'(m/w/d)' ignored when deduping ({a.dedup_key()})",
                    a.dedup_key() == b.dedup_key()))

    c = job("Java/Angular Developer", "x")
    results.append((f"'Java/Angular' not mangled ({c.dedup_key()})",
                    "javaangulardeveloper" in c.dedup_key()))

    d, e = job("Developer", "x"), job("Developer", "x")
    d.company = e.company = ""
    e.url = "https://example.com/j/2"
    results.append(("Company-less postings stay distinct",
                    d.dedup_key() != e.dedup_key()))

    from .dedupe import dedupe as dedupe_fn
    from .dedupe import propagate_remote as propagate_fn
    merged = dedupe_fn([a, b])
    results.append((f"Duplicate pair merges into 1 row (got {len(merged)}, "
                    f"sources={merged[0].sources if merged else []})", len(merged) == 1))

    # One pan-European remote role listed under 3 countries, where only the
    # board with the full description revealed that it is remote.
    spread = [job("Platform Engineer", "Fully remote across the EU. PHP and Laravel."),
              job("Platform Engineer", "PHP and Laravel."),
              job("Platform Engineer", "PHP and Laravel.")]
    spread[1].country, spread[2].country = "austria", "switzerland"
    for j in spread:
        scorer.filter(j)          # sets is_remote on the first one only
    propagate_fn(spread)
    collapsed = dedupe_fn(spread)
    results.append((f"Remote role merges across countries (got {len(collapsed)} row, "
                    f"countries={collapsed[0].countries if collapsed else []})",
                    len(collapsed) == 1 and len(collapsed[0].countries) == 3))

    # Render the real templates to a throwaway dir: a broken template would
    # otherwise only blow up at the very end of a 20-minute crawl.
    import tempfile

    from .config import load_config
    from .report import build_row, write_reports
    try:
        rows = [build_row(laravel_job, scorer.score(laravel_job), is_new=True),
                build_row(mixed_job, scorer.score(mixed_job), is_new=False)]
        demo = {"matches": rows[:1], "near": rows[1:], "unscoreable": []}
        with tempfile.TemporaryDirectory() as tmp:
            html_path, csv_path = write_reports(
                demo, {"crawled": 2, "unique": 2}, load_config(),
                Path(tmp), show_seen=False)
            html = html_path.read_text(encoding="utf-8")
        ok = ("Apply" in html and laravel_job.title in html
              and csv_path.name.startswith("jobs_"))
        results.append((f"HTML + CSV report render ({len(html)} bytes)", ok))
    except Exception as e:
        results.append((f"HTML + CSV report render raised {type(e).__name__}: {e}", False))

    from .resume_parser import _find_resume, extract_skills
    resume = _find_resume(PROJECT_ROOT)
    if resume:
        skills = extract_skills(resume)
        results.append(
            (f"Resume parsed: {len(skills)} skills incl. laravel={skills.get('laravel')} "
             f"php={skills.get('php')}",
             skills.get("laravel", 0) >= 0.8 and skills.get("php", 0) >= 0.7
             and len(skills) >= 10))
    else:
        results.append(("Resume html found next to preference.json", False))

    failures = 0
    for label, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}", flush=True)
        failures += 0 if ok else 1
    print(f"\nSelf-test: {len(results) - failures}/{len(results)} passed", flush=True)
    return 1 if failures else 0


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.self_test:
        return run_self_test()
    if args.seed_skills:
        from .resume_parser import seed_skills_into, write_default_preferences
        if PREFERENCE_FILE.exists():
            seed_skills_into(PREFERENCE_FILE)
        else:
            write_default_preferences(PREFERENCE_FILE)
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
