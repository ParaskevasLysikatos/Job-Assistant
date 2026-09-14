"""Indeed + LinkedIn Jobs + Google Jobs via the python-jobspy scraper.

No API keys needed. LinkedIn is scraped in a separate, smaller pass (it
rate-limits aggressively); after 2 consecutive LinkedIn failures the rest of
the LinkedIn crawl is skipped for this run (circuit breaker).
"""
from __future__ import annotations

import random
import time
from datetime import date

from ..config import COUNTRIES, Config
from .base import JobPosting, Source


def _clean(value) -> str:
    import pandas as pd
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return str(value).strip()


def _to_bool(value) -> bool:
    import pandas as pd
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return False
    return bool(value)


def _to_date(value) -> date | None:
    import pandas as pd
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value)
        return None if pd.isna(ts) else ts.date()
    except Exception:
        return None


class JobSpySource(Source):
    name = "jobspy"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._linkedin_failures = 0

    def fetch(self) -> list[JobPosting]:
        main_sites = [
            s.removeprefix("jobspy_")
            for s in self.cfg.sources
            if s.startswith("jobspy_") and s != "jobspy_linkedin"
        ]
        linkedin = "jobspy_linkedin" in self.cfg.sources
        hours_old = self.cfg.posted_within_days * 24

        postings: list[JobPosting] = []
        for country in self.cfg.countries:
            display = COUNTRIES[country]["display"]
            for term in self.cfg.terms:
                if main_sites:
                    postings += self._scrape(
                        sites=main_sites, term=term, country=country, display=display,
                        results=self.cfg.results_per_term, hours_old=hours_old,
                    )
                if linkedin and self._linkedin_failures < 2:
                    postings += self._scrape(
                        sites=["linkedin"], term=term, country=country, display=display,
                        results=self.cfg.linkedin_results_per_term, hours_old=hours_old,
                    )
                elif linkedin and self._linkedin_failures == 2:
                    print("[jobspy] LinkedIn rate-limited twice - skipping LinkedIn "
                          "for the rest of this run", flush=True)
                    self._linkedin_failures = 3
        return postings

    def _scrape(self, sites: list[str], term: str, country: str, display: str,
                results: int, hours_old: int) -> list[JobPosting]:
        from jobspy import scrape_jobs

        label = "+".join(sites)
        try:
            df = scrape_jobs(
                site_name=sites,
                search_term=term,
                google_search_term=f"{term} jobs in {display}",
                location=display,
                results_wanted=results,
                hours_old=hours_old,
                country_indeed=COUNTRIES[country]["indeed"],
                linkedin_fetch_description="linkedin" in sites,
                verbose=0,
            )
        except Exception as e:
            print(f"[jobspy] {display} '{term}' {label} FAILED: {type(e).__name__}: {e}", flush=True)
            if sites == ["linkedin"]:
                self._linkedin_failures += 1
            return []
        finally:
            time.sleep(random.uniform(2, 4))  # be polite between scrapes

        if sites == ["linkedin"]:
            self._linkedin_failures = 0
        if df is None or df.empty:
            # A legitimate zero-result search (small market, narrow term) looks
            # identical to a silently broken scrape unless this prints too.
            print(f"[jobspy] {display} '{term}' {label}: 0 jobs", flush=True)
            return []

        postings = []
        for _, row in df.iterrows():
            direct = _clean(row.get("job_url_direct"))
            url = direct or _clean(row.get("job_url"))
            if not url or not _clean(row.get("title")):
                continue
            postings.append(JobPosting(
                title=_clean(row.get("title")),
                company=_clean(row.get("company")),
                location=_clean(row.get("location")) or display,
                country=country,
                url=url,
                source=_clean(row.get("site")) or label,
                date_posted=_to_date(row.get("date_posted")),
                description=_clean(row.get("description")) or None,
                is_remote=_to_bool(row.get("is_remote")),
                url_priority=1 if direct else 2,
            ))
        print(f"[jobspy] {display} '{term}' {label}: {len(postings)} jobs", flush=True)
        return postings
