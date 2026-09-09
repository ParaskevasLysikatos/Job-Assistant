"""Cross-source deduplication and the persistent seen-jobs store."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from .sources.base import JobPosting


def propagate_remote(postings: list[JobPosting]) -> None:
    """One board's full description says "fully remote" while another's truncated
    snippet doesn't, which would key the same job two different ways and leave it
    both merged and unmerged. Agree on remote-ness first: if any copy of a
    company+title says remote, they all do."""
    def slug(s: str) -> str:
        return "".join(ch for ch in (s or "").lower() if ch.isalnum())

    remote_jobs = {(slug(p.company), slug(p.title)) for p in postings if p.is_remote}
    for p in postings:
        if (slug(p.company), slug(p.title)) in remote_jobs:
            p.is_remote = True


def dedupe(postings: list[JobPosting]) -> list[JobPosting]:
    """Merge postings that are the same job (company+title+country).
    Keeps the best URL (direct > board > aggregator), the longest description,
    the earliest posting date, and the union of sources."""
    by_key: dict[str, JobPosting] = {}
    for p in postings:
        key = p.dedup_key()
        current = by_key.get(key)
        if current is None:
            p.sources = [p.source]
            p.countries = [p.country]
            by_key[key] = p
            continue
        if p.source not in current.sources:
            current.sources.append(p.source)
        if p.country not in current.countries:
            current.countries.append(p.country)
        if p.url_priority < current.url_priority:
            current.url, current.url_priority = p.url, p.url_priority
        if len(p.description or "") > len(current.description or ""):
            current.description = p.description
        if p.date_posted and (current.date_posted is None or p.date_posted < current.date_posted):
            current.date_posted = p.date_posted
        current.is_remote = current.is_remote or p.is_remote
    return list(by_key.values())


class SeenStore:
    """SQLite store of every job key ever reported, so repeated runs can
    highlight only NEW positions."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            " key TEXT PRIMARY KEY, first_seen TEXT, title TEXT,"
            " company TEXT, url TEXT, match_percent REAL)"
        )
        self.conn.commit()

    def known_keys(self) -> set[str]:
        return {row[0] for row in self.conn.execute("SELECT key FROM seen")}

    def record(self, jobs: list[tuple[str, str, str, str, float | None]]) -> None:
        today = date.today().isoformat()
        self.conn.executemany(
            "INSERT OR IGNORE INTO seen (key, first_seen, title, company, url, match_percent)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(key, today, title, company, url, match) for key, title, company, url, match in jobs],
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
