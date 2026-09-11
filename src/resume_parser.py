"""Extract a skill/proficiency profile from the resume HTML.

Reads the sidebar skill bars (name + width%) and additionally scans the whole
resume text for taxonomy skills mentioned in job descriptions (those get a
default proficiency). Used to create preference.json on first run and by the
--seed-skills flag; afterwards preference.json is the source of truth and can
be edited freely.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .matching.taxonomy import detect_skills

# Token (lowercased) from a skill-bar name -> canonical taxonomy skill.
ALIASES = {
    "laravel": "laravel",
    "vue": "vue", "vue.js": "vue", "vuejs": "vue",
    "php": "php",
    "javascript": "javascript",
    "mysql": "mysql",
    "postgresql": "postgresql", "postgres": "postgresql",
    "angular": "angular",
    "typescript": "typescript",
    "python": "python",
    "django": "django",
    "java": "java",
    "spring boot": "spring", "spring": "spring",
    "c#": "csharp", ".net": "csharp",
    "aws": "aws",
}

TEXT_SCAN_DEFAULT_PROFICIENCY = 0.5


def extract_skills(resume_path: Path) -> dict[str, float]:
    html = resume_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    skills: dict[str, float] = {}

    for item in soup.select(".skill-item"):
        name_el = item.select_one(".skill-name")
        fill_el = item.select_one(".skill-fill")
        if not name_el or not fill_el:
            continue
        width = re.search(r"width:\s*(\d+)\s*%", fill_el.get("style", ""))
        proficiency = int(width.group(1)) / 100 if width else 0.5

        # "Java(Spring Boot) + C#(.NET)" -> ["java", "spring boot", "c#", ".net"]
        raw = name_el.get_text(" ", strip=True).lower()
        tokens: list[str] = []
        for part in raw.split("+"):
            part = part.strip()
            inner = re.findall(r"\(([^)]*)\)", part)
            outer = re.sub(r"\([^)]*\)", "", part).strip()
            tokens.extend(t.strip() for t in [outer, *inner] if t.strip())

        for token in tokens:
            canonical = ALIASES.get(token)
            if canonical:
                skills[canonical] = max(skills.get(canonical, 0), proficiency)

    if "mysql" in skills or "postgresql" in skills:
        skills.setdefault("sql", max(skills.get("mysql", 0), skills.get("postgresql", 0)))

    # Pick up skills only mentioned in the experience text (Symfony, Flask, ...)
    for skill in detect_skills(soup.get_text(" ")):
        skills.setdefault(skill, TEXT_SCAN_DEFAULT_PROFICIENCY)

    return skills


def _skills_as_json(skills: dict[str, float]) -> list[dict]:
    ordered = sorted(skills.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"name": name, "proficiency": round(prof, 2)} for name, prof in ordered]


def default_preferences(skills: dict[str, float], resume_file: str) -> dict:
    return {
        "resume_file": resume_file,
        "search": {
            "terms": [
                "PHP Developer", "Laravel Developer", "Vue.js Developer",
                "Backend Developer", "Full Stack Developer", "Web Developer",
            ],
            "countries": ["germany", "austria", "netherlands", "switzerland", "greece"],
            "posted_within_days": 14,
            "results_per_term": 40,
            "linkedin_results_per_term": 10,
            "sources": ["jobspy_indeed", "jobspy_linkedin", "jobspy_google", "adzuna", "jooble"],
            "remote_policy": "include",
            "jooble_terms": ["php laravel vue developer", "full stack web developer"],
        },
        "matching": {
            "min_match_percent": 70,
            "min_detected_skills": 2,
            "strong_skill_threshold": 0.5,
            "german_requirement": "low",
            "languages_ok": ["en", "de", "el"],
            "exclude_title_keywords": [
                "senior", "sr.", "lead", "principal", "staff", "architect",
                "head of", "director", "chief", "cto", "teamleiter", "leiter",
                "intern", "internship", "praktikum", "praktikant", "werkstudent",
                "trainee", "apprentice", "ausbildung", "thesis",
                # Career-changer / retraining offers, not mid-level dev roles.
                "quereinsteiger", "quereinstieg", "berufseinsteiger",
                "starte deine karriere",
                # Non-engineering roles that keyword matching would otherwise
                # score highly because the ad still lists a tech stack.
                "customer support", "customer service", "technical support",
                "support representative", "sales", "recruiter", "account manager",
                "business development",
            ],
            "skills": _skills_as_json(skills),
        },
    }


def write_default_preferences(path: Path) -> None:
    resume = _find_resume(path.parent)
    skills = extract_skills(resume) if resume else {}
    prefs = default_preferences(skills, resume.name if resume else "resume.html")
    path.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")
    print(f"[resume] wrote {path.name} with {len(skills)} skills seeded from "
          f"{resume.name if resume else 'nothing (no resume html found!)'}")


def seed_skills_into(path: Path) -> None:
    """--seed-skills: refresh matching.skills from the resume, keeping any
    proficiency the user already tuned by hand."""
    prefs = json.loads(path.read_text(encoding="utf-8"))
    resume = path.parent / prefs.get("resume_file", "")
    if not resume.exists():
        found = _find_resume(path.parent)
        if not found:
            print("[resume] ERROR: no resume html found next to preference.json")
            return
        resume = found

    fresh = extract_skills(resume)
    existing = {
        s["name"].lower(): float(s.get("proficiency", 0.5))
        for s in prefs.get("matching", {}).get("skills", [])
        if isinstance(s, dict) and "name" in s
    }
    merged = {**fresh, **existing}  # hand-tuned values win over re-extraction
    added = sorted(set(fresh) - set(existing))
    prefs.setdefault("matching", {})["skills"] = _skills_as_json(merged)
    path.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")
    print(f"[resume] skills refreshed from {resume.name}: {len(merged)} total, "
          f"newly added: {added or 'none'}")


def _find_resume(directory: Path) -> Path | None:
    candidates = sorted(directory.glob("resume*.html")) or sorted(directory.glob("*.html"))
    return candidates[0] if candidates else None
