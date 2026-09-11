"""Shared data model and interface for all job sources."""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

# "(m/w/d)", "m/f/d", "(f/m/x)", "(w/m/d)" ... appear in most German-language ads
# and vary between boards, so they must not defeat duplicate detection.
# The letter-boundary guards matter: without them "Java/Angular" would match
# on its "a/A" and the title would be mangled.
GENDER_MARKER = re.compile(
    r"(?<![a-zA-Z])[\(\[]?\s*[mwfdxa](?:\s*[/|]\s*[mwfdxa]){1,3}(?![a-zA-Z])\s*[\)\]]?",
    re.IGNORECASE,
)


@dataclass
class JobPosting:
    title: str
    company: str
    location: str
    country: str            # canonical: germany|austria|netherlands|switzerland|greece
    url: str
    source: str             # e.g. "indeed", "linkedin", "google", "adzuna", "jooble"
    date_posted: date | None = None
    description: str | None = None
    is_remote: bool = False
    english_friendly: bool = False   # ad says English is enough
    demands_german: bool = False     # ad asks for German above ~B2
    url_priority: int = 5   # lower = better URL to keep after dedup (direct link beats aggregator)

    # Filled in by the pipeline:
    sources: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)

    def dedup_key(self) -> str:
        def slug(s: str) -> str:
            return "".join(ch for ch in s.lower() if ch.isalnum())

        company = slug(self.company)
        title = slug(GENDER_MARKER.sub(" ", self.title or ""))
        # One pan-European remote role gets listed under several countries, so
        # remote postings are matched across them. On-site roles keep the
        # country in the key: the same title at the same company in Berlin and
        # in Athens really are two different jobs with two applications.
        scope = "remote" if self.is_remote else self.country
        if not company:
            # Without a company name, title+country is too weak a key and would
            # merge unrelated jobs. Keep them apart; a stray duplicate in the
            # report is far cheaper than silently dropping a real posting.
            company = "anon" + hashlib.sha1(self.url.encode()).hexdigest()[:8]
        return f"{company}|{title}|{scope}"


class Source(ABC):
    """A job source. Implementations must be fail-soft: raise nothing fatal,
    log a warning and return what they could fetch."""

    name: str = "base"

    @abstractmethod
    def fetch(self) -> list[JobPosting]:
        ...
