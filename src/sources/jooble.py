"""Jooble REST API source. Covers all 5 countries.

A Jooble key is tied to the domain it was registered on. We try the country's
regional domain first (de.jooble.org, ...) and fall back to the main jooble.org
domain with the country as the search location - that way a single key
registered on jooble.org works for every country. Whichever style answers first
is reused for the rest of the run, so the fallback costs one extra request.

Budget-aware: the free key allows only 500 requests over its LIFETIME, so this
source sends just len(jooble_terms) requests per country per run (2 by default,
i.e. 10 requests per full run). Keys per country: https://<cc>.jooble.org/api/about
"""
from __future__ import annotations

import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from ..config import COUNTRIES, Config
from .base import JobPosting, Source


class JoobleSource(Source):
    name = "jooble"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.use_main_domain = False   # set once a regional key turns out to be rejected

    def _query(self, key: str, cc: str, display: str, term: str):
        """POST the search, falling back from the regional domain to jooble.org.
        Returns the successful response, or None if the key works on neither."""
        attempts = ["main"] if self.use_main_domain else ["regional", "main"]
        for attempt in attempts:
            regional = attempt == "regional"
            url = f"https://{cc}.jooble.org/api/{key}" if regional else f"https://jooble.org/api/{key}"
            # On the global domain the location must name the country, or the
            # search would return jobs from anywhere in the world.
            body = {"keywords": term, "location": "" if regional else display}
            try:
                resp = requests.post(url, json=body, timeout=30)
            except requests.RequestException as e:
                print(f"[jooble] {display} '{term}' request failed: {e}", flush=True)
                return None

            if resp.status_code in (401, 403):
                if regional:
                    print(f"[jooble] key not valid on {cc}.jooble.org - "
                          "retrying on the main jooble.org domain", flush=True)
                    continue
                return None
            if resp.status_code != 200:
                print(f"[jooble] {display} '{term}' HTTP {resp.status_code}", flush=True)
                return None

            if not regional and not self.use_main_domain:
                self.use_main_domain = True   # remember: skip the regional attempt from now on
            return resp
        return None

    def fetch(self) -> list[JobPosting]:
        if not self.cfg.jooble_keys:
            print("[jooble] no JOOBLE_KEY_* in .env - skipping (optional; register "
                  "per-country at https://de.jooble.org/api/about etc.)", flush=True)
            return []

        postings: list[JobPosting] = []
        for country in self.cfg.countries:
            key = self.cfg.jooble_key_for(country)
            if not key:
                print(f"[jooble] no key for {country} - skipping that country", flush=True)
                continue
            cc = COUNTRIES[country]["jooble"]
            display = COUNTRIES[country]["display"]

            for term in self.cfg.jooble_terms:
                resp = self._query(key, cc, display, term)
                if resp is None:
                    print(f"[jooble] key works on neither {cc}.jooble.org nor "
                          f"jooble.org - skipping {country}", flush=True)
                    break

                count = 0
                for job in resp.json().get("jobs", []):
                    url = job.get("link", "")
                    if not url or not job.get("title"):
                        continue
                    updated = None
                    try:
                        updated = datetime.fromisoformat(job.get("updated", "")[:19]).date()
                    except ValueError:
                        pass
                    snippet = BeautifulSoup(job.get("snippet") or "", "html.parser").get_text(" ").strip()
                    postings.append(JobPosting(
                        title=job["title"],
                        company=job.get("company") or "",
                        location=job.get("location") or display,
                        country=country,
                        url=url,
                        source="jooble",
                        date_posted=updated,
                        description=snippet or None,
                        url_priority=4,
                    ))
                    count += 1
                print(f"[jooble] {country} '{term}': {count} jobs", flush=True)
                time.sleep(0.4)
        return postings
