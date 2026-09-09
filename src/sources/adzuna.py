"""Adzuna REST API source. Covers Germany, Austria, Netherlands, Switzerland
(Adzuna has no Greek market). Free keys: https://developer.adzuna.com/

Note: Adzuna returns truncated descriptions; some of its jobs may land in the
"low confidence" report section because too few skills are detectable.
"""
from __future__ import annotations

import time
from datetime import datetime

import requests

from ..config import COUNTRIES, Config
from .base import JobPosting, Source

API = "https://api.adzuna.com/v1/api/jobs/{cc}/search/1"


class AdzunaSource(Source):
    name = "adzuna"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def fetch(self) -> list[JobPosting]:
        if not (self.cfg.adzuna_app_id and self.cfg.adzuna_app_key):
            print("[adzuna] no ADZUNA_APP_ID / ADZUNA_APP_KEY in .env - skipping "
                  "(register free at https://developer.adzuna.com/)", flush=True)
            return []

        postings: list[JobPosting] = []
        for country in self.cfg.countries:
            cc = COUNTRIES[country]["adzuna"]
            if cc is None:
                print(f"[adzuna] {country} is not covered by Adzuna - skipping", flush=True)
                continue
            for term in self.cfg.terms:
                try:
                    resp = requests.get(
                        API.format(cc=cc),
                        params={
                            "app_id": self.cfg.adzuna_app_id,
                            "app_key": self.cfg.adzuna_app_key,
                            "what": term,
                            "results_per_page": 50,
                            "max_days_old": self.cfg.posted_within_days,
                            "content-type": "application/json",
                        },
                        timeout=30,
                    )
                except requests.RequestException as e:
                    print(f"[adzuna] {country} '{term}' request failed: {e}", flush=True)
                    continue

                if resp.status_code in (401, 403):
                    print("[adzuna] API keys rejected - check ADZUNA_APP_ID / "
                          "ADZUNA_APP_KEY in .env. Skipping Adzuna.", flush=True)
                    return postings
                if resp.status_code != 200:
                    print(f"[adzuna] {country} '{term}' HTTP {resp.status_code} - skipping", flush=True)
                    continue

                count = 0
                for job in resp.json().get("results", []):
                    url = job.get("redirect_url", "")
                    title = (job.get("title") or "").replace("<strong>", "").replace("</strong>", "")
                    if not url or not title:
                        continue
                    created = None
                    try:
                        created = datetime.fromisoformat(
                            job.get("created", "").replace("Z", "+00:00")).date()
                    except ValueError:
                        pass
                    postings.append(JobPosting(
                        title=title,
                        company=(job.get("company") or {}).get("display_name", ""),
                        location=(job.get("location") or {}).get("display_name", ""),
                        country=country,
                        url=url,
                        source="adzuna",
                        date_posted=created,
                        description=job.get("description") or None,
                        url_priority=3,
                    ))
                    count += 1
                print(f"[adzuna] {country} '{term}': {count} jobs", flush=True)
                time.sleep(0.4)
        return postings
