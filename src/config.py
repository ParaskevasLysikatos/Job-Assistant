"""Load and validate preference.json + .env into one Config object."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PREFERENCE_FILE = PROJECT_ROOT / "preference.json"

# Canonical country slugs and their per-source identifiers.
COUNTRIES: dict[str, dict] = {
    "germany":     {"display": "Germany",     "adzuna": "de", "jooble": "de", "indeed": "germany"},
    "austria":     {"display": "Austria",     "adzuna": "at", "jooble": "at", "indeed": "austria"},
    "netherlands": {"display": "Netherlands", "adzuna": "nl", "jooble": "nl", "indeed": "netherlands"},
    "switzerland": {"display": "Switzerland", "adzuna": "ch", "jooble": "ch", "indeed": "switzerland"},
    "greece":      {"display": "Greece",      "adzuna": None, "jooble": "gr", "indeed": "greece"},
}

ALL_SOURCES = ["jobspy_indeed", "jobspy_linkedin", "jobspy_google", "adzuna", "jooble"]


@dataclass
class Config:
    # search
    terms: list[str]
    countries: list[str]
    posted_within_days: int
    results_per_term: int
    linkedin_results_per_term: int
    sources: list[str]
    remote_policy: str
    jooble_terms: list[str]
    # matching
    min_match_percent: float
    min_detected_skills: int
    strong_skill_threshold: float
    languages_ok: list[str]
    exclude_title_keywords: list[str]
    skills: dict[str, float]
    # misc
    resume_file: str
    # secrets (from .env / environment)
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    jooble_keys: dict[str, str] = field(default_factory=dict)  # country slug -> key

    def jooble_key_for(self, country: str) -> str:
        return self.jooble_keys.get(country) or self.jooble_keys.get("*", "")


def _fail(msg: str) -> None:
    print(f"[config] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_config(path: Path = PREFERENCE_FILE) -> Config:
    load_dotenv(PROJECT_ROOT / ".env")

    if not path.exists():
        # First run without a preference file: seed one from the resume.
        from .resume_parser import write_default_preferences
        print(f"[config] {path.name} not found - creating a default one seeded from your resume.")
        write_default_preferences(path)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(f"{path.name} is not valid JSON: {e}")

    search = raw.get("search", {})
    matching = raw.get("matching", {})

    countries = [c.strip().lower() for c in search.get("countries", list(COUNTRIES))]
    unknown = [c for c in countries if c not in COUNTRIES]
    if unknown:
        _fail(f"unknown countries in preference.json: {unknown}. Supported: {list(COUNTRIES)}")

    sources = [s.strip().lower() for s in search.get("sources", ALL_SOURCES)]
    unknown = [s for s in sources if s not in ALL_SOURCES]
    if unknown:
        _fail(f"unknown sources in preference.json: {unknown}. Supported: {ALL_SOURCES}")

    remote_policy = search.get("remote_policy", "include")
    if remote_policy not in ("include", "only", "exclude"):
        _fail("search.remote_policy must be one of: include, only, exclude")

    skills_raw = matching.get("skills", [])
    skills: dict[str, float] = {}
    for item in skills_raw:
        if isinstance(item, dict) and "name" in item:
            skills[str(item["name"]).lower()] = float(item.get("proficiency", 0.5))
    if not skills:
        _fail("matching.skills is empty - run with --seed-skills to fill it from your resume")

    jooble_keys: dict[str, str] = {}
    for slug, meta in COUNTRIES.items():
        key = os.environ.get(f"JOOBLE_KEY_{meta['jooble'].upper()}", "").strip()
        if key:
            jooble_keys[slug] = key
    fallback = os.environ.get("JOOBLE_KEY", "").strip()
    if fallback:
        jooble_keys["*"] = fallback

    return Config(
        terms=search.get("terms", ["PHP Developer", "Full Stack Developer"]),
        countries=countries,
        posted_within_days=int(search.get("posted_within_days", 14)),
        results_per_term=int(search.get("results_per_term", 40)),
        linkedin_results_per_term=int(search.get("linkedin_results_per_term", 10)),
        sources=sources,
        remote_policy=remote_policy,
        jooble_terms=search.get("jooble_terms", ["php laravel vue developer", "full stack web developer"]),
        min_match_percent=float(matching.get("min_match_percent", 70)),
        min_detected_skills=int(matching.get("min_detected_skills", 2)),
        strong_skill_threshold=float(matching.get("strong_skill_threshold", 0.5)),
        languages_ok=matching.get("languages_ok", ["en", "de", "el"]),
        exclude_title_keywords=matching.get("exclude_title_keywords", []),
        skills=skills,
        resume_file=raw.get("resume_file", "resume_paraskevas.html"),
        adzuna_app_id=os.environ.get("ADZUNA_APP_ID", "").strip(),
        adzuna_app_key=os.environ.get("ADZUNA_APP_KEY", "").strip(),
        jooble_keys=jooble_keys,
    )
