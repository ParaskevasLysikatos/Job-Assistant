"""Render results: HTML report, CSV export, console summary."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import COUNTRIES, Config
from .matching.scorer import ScoreResult
from .sources.base import JobPosting

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def build_row(job: JobPosting, score: ScoreResult, is_new: bool) -> dict:
    return {
        "match": score.percent,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "country": ", ".join(COUNTRIES[c]["display"]
                             for c in (job.countries or [job.country])),
        "evidence": len(score.detected),
        "date": job.date_posted.isoformat() if job.date_posted else "",
        "sources": ", ".join(job.sources or [job.source]),
        "url": job.url,
        "matched": sorted(score.matched.items(), key=lambda kv: -kv[1]),
        "partial": sorted(score.partial.items(), key=lambda kv: -kv[1]),
        "missing": sorted(score.missing),
        "strength": score.strength,
        "is_new": is_new,
        "remote": job.is_remote,
    }


def _sort_rows(rows: list[dict]) -> list[dict]:
    # Best match first; ties broken by how much the ad actually told us (a 100%
    # match on two keywords is weaker evidence than 90% across a dozen), then by
    # how strong those skills are for you, then by freshness.
    rows = sorted(rows, key=lambda r: r["date"], reverse=True)
    rows.sort(key=lambda r: (r["match"] if r["match"] is not None else -1,
                             r["evidence"], r["strength"]), reverse=True)
    return rows


def write_reports(sections: dict[str, list[dict]], counts: dict, cfg: Config,
                  out_dir: Path, show_seen: bool) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")

    for key in sections:
        sections[key] = _sort_rows(sections[key])

    html = _env.get_template("report.html.j2").render(
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        countries=", ".join(COUNTRIES[c]["display"] for c in cfg.countries),
        days=cfg.posted_within_days,
        threshold=int(cfg.min_match_percent),
        near_floor=int(max(cfg.min_match_percent - 15, 0)),
        sections=sections,
        counts=counts,
        show_seen=show_seen,
    )
    html_path = out_dir / f"report_{stamp}.html"
    html_path.write_text(html, encoding="utf-8")
    (out_dir / "report_latest.html").write_text(html, encoding="utf-8")

    csv_path = out_dir / f"jobs_{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["status", "match_percent", "skills_in_ad", "title", "company",
                         "location", "country", "remote", "new", "date_posted", "sources",
                         "matched_skills", "partial_skills", "missing_skills", "url"])
        for status, rows in sections.items():
            for r in rows:
                writer.writerow([
                    status, r["match"] if r["match"] is not None else "", r["evidence"],
                    r["title"], r["company"], r["location"], r["country"],
                    "yes" if r["remote"] else "", "yes" if r["is_new"] else "",
                    r["date"], r["sources"],
                    " ".join(s for s, _ in r["matched"]),
                    " ".join(s for s, _ in r["partial"]),
                    " ".join(r["missing"]),
                    r["url"],
                ])
    return html_path, csv_path


def print_summary(sections: dict[str, list[dict]], counts: dict, excluded: dict,
                  cfg: Config, html_path: Path, csv_path: Path) -> None:
    p = lambda s="": print(s, flush=True)
    p()
    p("=" * 70)
    p("RESULTS")
    p("=" * 70)
    p(f"Crawled {counts['crawled']} postings -> {counts['unique']} unique after dedup")
    if excluded:
        parts = ", ".join(f"{reason}: {n}" for reason, n in sorted(excluded.items()))
        p(f"Filtered out before scoring: {parts}")
    p(f"Matches >= {cfg.min_match_percent:.0f}%: {len(sections['matches'])} "
      f"| near misses: {len(sections['near'])} "
      f"| low confidence: {len(sections['unscoreable'])}")
    p()
    top = sections["matches"][:10]
    if top:
        p(f"TOP {len(top)} MATCHES:")
        for r in top:
            flags = "".join([" [NEW]" if r["is_new"] else "", " [REMOTE]" if r["remote"] else ""])
            p(f"  {r['match']:5.1f}% ({r['evidence']} skills)  {r['title']} - "
              f"{r['company'] or '?'} ({r['country']}){flags}")
            p(f"          {r['url']}")
    else:
        p("No matches at the current threshold. Ideas: lower matching.min_match_percent,")
        p("raise search.posted_within_days, or add skills in preference.json.")
    p()
    p(f"HTML report: {html_path}")
    p(f"CSV export:  {csv_path}")
