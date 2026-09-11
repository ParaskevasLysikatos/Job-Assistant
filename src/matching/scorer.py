"""Scoring and filtering of job postings against the user's skill profile.

Match formula (documented in README) - skill COVERAGE of what the ad asks for:
    each skill detected in the ad scores 1.0 if you know it well
    (proficiency >= strong_skill_threshold), 0.5 if you know it a little,
    0 if not at all;  match % = total credit / number of detected skills x 100.
So "75%" reads as "you cover three quarters of the stack this ad asks for".
Proficiency is kept as `strength` to rank equally-matching ads.
Postings with fewer than `min_detected_skills` taxonomy hits cannot be scored
reliably and are reported separately instead of silently dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from langdetect import DetectorFactory, LangDetectException, detect

from ..sources.base import JobPosting
from .taxonomy import detect_skills

DetectorFactory.seed = 0  # langdetect is randomized by default; make it deterministic

REMOTE_HINTS = re.compile(
    r"\b(fully remote|100\s*%\s*remote|remote[- ]first|remote work|work from home|"
    r"home\s*office|homeoffice|work from anywhere|telearbeit)\b",
    re.IGNORECASE,
)

# Below this many characters language detection is unreliable; skip the filter.
MIN_TEXT_FOR_LANG = 80

# Ads demanding German ABOVE a comfortable B2. Plain "gute Deutschkenntnisse"
# is deliberately absent - that is roughly B2 and workable.
GERMAN_FLUENCY = re.compile(
    r"(fließend(e|es)?\s+deutsch|fliessend(e|es)?\s+deutsch|"
    r"fließende\s+deutschkenntnisse|verhandlungssicher\w*\s+deutsch|"
    r"deutsch\w*\s+verhandlungssicher|sehr\s+gute\s+deutschkenntnisse|"
    r"ausgezeichnete\s+deutschkenntnisse|exzellente\s+deutschkenntnisse|"
    r"deutsch\s+als\s+muttersprache|muttersprach\w*\s+deutsch|"
    r"deutsch\s+auf\s+muttersprachlichem\s+niveau|"
    r"deutsch\w*\s*\(?\s*c[12]\s*\)?|c[12][\s-]*niveau\s+deutsch|"
    r"fluent\s+(in\s+)?german|native\s+german|german\s+native|"
    r"excellent\s+german|very\s+good\s+german|business[- ]fluent\s+german|"
    r"proficient\s+in\s+german|german\s+\(?c[12]\)?)",
    re.IGNORECASE,
)

# Ads that say out loud that English is enough.
ENGLISH_FRIENDLY = re.compile(
    r"(english\s+is\s+(our|the)\s+(working|company|official)\s+language|"
    r"(working|company|official)\s+language\s+is\s+english|"
    r"we\s+work\s+in\s+english|english[- ]speaking\s+(team|environment)|"
    r"no\s+german\s+(is\s+)?(required|needed|necessary)|"
    r"german\s+(is\s+)?not\s+(required|needed|necessary)|"
    r"without\s+german|kein\s+deutsch\s+(erforderlich|notwendig)|"
    r"deutsch\s+nicht\s+erforderlich|englisch\s+als\s+arbeitssprache|"
    r"arbeitssprache\s+(ist\s+)?englisch)",
    re.IGNORECASE,
)


def mark_language_fit(job: JobPosting) -> None:
    """Flag whether an ad demands more German than B2, and whether it states
    outright that English suffices."""
    text = f"{job.title or ''} {job.description or ''}"
    job.english_friendly = bool(ENGLISH_FRIENDLY.search(text))
    # An explicit "English is our working language" outranks a boilerplate
    # German-skills line further down the same ad.
    job.demands_german = bool(GERMAN_FLUENCY.search(text)) and not job.english_friendly


def mark_remote(job: JobPosting) -> bool:
    """Set job.is_remote from the ad text if the source didn't flag it.
    Runs before deduplication, which merges pan-European remote listings."""
    if not job.is_remote and REMOTE_HINTS.search(f"{job.title or ''} {job.description or ''}"):
        job.is_remote = True
    return job.is_remote


@dataclass
class ScoreResult:
    percent: float | None            # None -> unscoreable (too few detected skills)
    detected: list[str] = field(default_factory=list)
    matched: dict[str, float] = field(default_factory=dict)   # solid skill -> proficiency
    partial: dict[str, float] = field(default_factory=dict)   # weak skill -> proficiency
    missing: list[str] = field(default_factory=list)
    strength: float = 0.0            # mean proficiency over known skills (ranking tie-break)


@dataclass
class FilterOutcome:
    kept: bool
    reason: str = ""                 # senior_title | language | too_old | remote_policy
                                     # | german_required | not_english
    language: str = ""


class Scorer:
    def __init__(
        self,
        skills: dict[str, float],
        min_detected_skills: int = 2,
        exclude_title_keywords: list[str] | None = None,
        languages_ok: list[str] | None = None,
        posted_within_days: int = 14,
        remote_policy: str = "include",
        strong_skill_threshold: float = 0.5,
        partial_credit: float = 0.5,
        german_requirement: str = "any",
    ):
        self.german_requirement = german_requirement
        self.skills = {k.lower(): float(v) for k, v in skills.items()}
        self.min_detected = min_detected_skills
        self.strong_threshold = strong_skill_threshold
        self.partial_credit = partial_credit
        self.languages_ok = [l.lower() for l in (languages_ok or ["en"])]
        self.posted_within_days = posted_within_days
        self.remote_policy = remote_policy
        self._title_excludes = [
            self._keyword_pattern(k) for k in (exclude_title_keywords or [])
        ]

    @staticmethod
    def _keyword_pattern(keyword: str) -> re.Pattern:
        parts = [re.escape(p) for p in keyword.lower().split()]
        return re.compile(r"(?<!\w)" + r"[\s\-/]+".join(parts) + r"(?!\w)")

    # ---- filtering -------------------------------------------------------

    def filter(self, job: JobPosting, today: date | None = None) -> FilterOutcome:
        today = today or date.today()

        title = (job.title or "").lower()
        for pattern in self._title_excludes:
            if pattern.search(title):
                return FilterOutcome(False, "senior_title")

        if job.date_posted is not None:
            if job.date_posted < today - timedelta(days=self.posted_within_days):
                return FilterOutcome(False, "too_old")

        text = job.description or ""
        mark_remote(job)
        if self.remote_policy == "only" and not job.is_remote:
            return FilterOutcome(False, "remote_policy")
        if self.remote_policy == "exclude" and job.is_remote:
            return FilterOutcome(False, "remote_policy")

        language = ""
        if len(text) >= MIN_TEXT_FOR_LANG:
            try:
                language = detect(text[:1500])
            except LangDetectException:
                language = ""
            if language and language not in self.languages_ok:
                return FilterOutcome(False, "language", language)

        # How much German the job itself demands, independent of the ad's language.
        mark_language_fit(job)
        if self.german_requirement in ("low", "none") and job.demands_german:
            return FilterOutcome(False, "german_required", language)
        if self.german_requirement == "none":
            # Strictly English-workable: an English ad, or one that says so.
            if not job.english_friendly and language and language != "en":
                return FilterOutcome(False, "not_english", language)

        return FilterOutcome(True, "", language)

    # ---- scoring ---------------------------------------------------------

    def score(self, job: JobPosting) -> ScoreResult:
        text = f"{job.title or ''}\n{job.description or ''}"
        detected = detect_skills(text)
        if len(detected) < self.min_detected:
            return ScoreResult(None, detected)

        matched: dict[str, float] = {}
        partial: dict[str, float] = {}
        missing: list[str] = []
        for skill in detected:
            proficiency = self.skills.get(skill, 0.0)
            if proficiency >= self.strong_threshold:
                matched[skill] = proficiency
            elif proficiency > 0:
                partial[skill] = proficiency
            else:
                missing.append(skill)

        credit = len(matched) + self.partial_credit * len(partial)
        percent = 100.0 * credit / len(detected)
        known = list(matched.values()) + list(partial.values())
        strength = sum(known) / len(known) if known else 0.0
        return ScoreResult(round(percent, 1), detected, matched, partial, missing,
                           round(strength, 3))
