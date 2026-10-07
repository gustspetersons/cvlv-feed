"""RSS feed of cv.lv vacancies (salary from 2000 EUR) that are new to me.

A vacancy counts as new the first time its ID shows up in the live search
results. A renewal ("Atjaunināts") keeps the vacancy's ID, so ads already
seen never come back; an expired ad brought back by a renewal is new to me
and does show up, tagged as such.

State lives next to the feed in the site directory (the gh-pages branch):

    seen.csv    every vacancy ID ever seen, with the time it was first seen
    items.json  the vacancies currently in the feed (last FEED_DAYS days)
    feed.xml    the RSS feed itself
"""

import argparse
import csv
import html
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

API_URL = "https://www.cv.lv/api/v1/vacancy-search-service/search"
SEARCH_PARAMS = {"salaryFrom": 2000, "sorting": "LATEST"}
SEARCH_PAGE = "https://www.cv.lv/lv/search?salaryFrom=2000&sorting=LATEST"
VACANCY_URL = "https://www.cv.lv/lv/vacancy/{id}"
FEED_URL = "https://gustspetersons.github.io/cvlv-feed/feed.xml"
USER_AGENT = "cvlv-feed/1.0 (personal RSS; github.com/gustspetersons/cvlv-feed)"

PAGE_SIZE = 500
MAX_PAGES = 20
FEED_DAYS = 14
RIGA = ZoneInfo("Europe/Riga")

TOWNS = {543: "Rīga"}
REMOTE_TYPES = {
    "ON_SITE": "klātienē",
    "HYBRID": "hibrīds",
    "FULLY_REMOTE": "attālināti",
}


def parse_time(value):
    return datetime.fromisoformat(value) if value else None


def fetch_vacancies():
    """Return every live vacancy matching SEARCH_PARAMS, keyed by ID."""
    vacancies, total, offset = {}, None, 0
    for _ in range(MAX_PAGES):
        params = {**SEARCH_PARAMS, "limit": PAGE_SIZE, "offset": offset}
        request = urllib.request.Request(
            f"{API_URL}?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            page = json.load(response)
        total = page["total"]
        batch = page["vacancies"]
        for vacancy in batch:
            vacancies[vacancy["id"]] = vacancy
        offset += len(batch)
        if not batch or offset >= total:
            break
        time.sleep(1)
    if total and len(vacancies) < total:
        print(f"Warning: got {len(vacancies)} of {total} vacancies")
    return vacancies


def load_seen(path):
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as file:
        return {int(row["id"]): row["first_seen"] for row in csv.DictReader(file)}


def save_seen(path, seen):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["id", "first_seen"])
        writer.writerows(sorted(seen.items()))


def load_excluded(path):
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        line.strip().casefold()
        for line in lines
        if line.strip() and not line.startswith("#")
    ]


def is_excluded(vacancy, excluded):
    employer = (vacancy.get("employerName") or "").casefold()
    return any(name in employer for name in excluded)


def to_item(vacancy, first_seen):
    keys = [
        "id", "positionTitle", "employerName", "salaryFrom", "salaryTo",
        "hourlySalary", "townId", "remoteWorkType", "publishDate",
        "renewedDate", "expirationDate", "keywords",
    ]
    return {**{key: vacancy.get(key) for key in keys}, "firstSeen": first_seen}


def format_salary(item):
    low, high = item["salaryFrom"], item["salaryTo"]
    unit = "€/st." if item["hourlySalary"] else "€/mēn."
    if low and high and high != low:
        return f"{low:g}–{high:g} {unit}"
    if low:
        return f"no {low:g} {unit}"
    return "alga nav norādīta"


def describe(item):
    """HTML body of one feed item."""
    town = TOWNS.get(item["townId"], "ārpus Rīgas")
    remote = REMOTE_TYPES.get(item["remoteWorkType"], "")
    facts = " · ".join(part for part in [format_salary(item), town, remote] if part)
    # cv.lv stores deadlines as 23:59 UTC, so the UTC date is the one it shows.
    deadline = parse_time(item["expirationDate"]).strftime("%d.%m.%Y")
    status = "Atjaunināts" if item["renewedDate"] else "Publicēts"
    published = parse_time(item["publishDate"]).astimezone(RIGA)
    lines = [
        f"<b>{html.escape(item['employerName'] or '')}</b>",
        html.escape(facts),
        f"Pieteikties līdz {deadline}",
        f"{status} {published:%d.%m.%Y %H:%M}",
    ]
    if item.get("keywords"):
        lines.append(html.escape(", ".join(item["keywords"])))
    return "<br>".join(lines)


def build_feed(items, now):
    entries = []
    for item in items:
        title = f"{item['positionTitle']} · {item['employerName']}"
        published = parse_time(item["publishDate"])
        entries.append(
            "<item>"
            f"<title>{escape(title)}</title>"
            f"<link>{VACANCY_URL.format(id=item['id'])}</link>"
            f'<guid isPermaLink="false">cvlv-{item["id"]}</guid>'
            f"<pubDate>{format_datetime(published)}</pubDate>"
            f"<description>{escape(describe(item))}</description>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
        "<channel>"
        "<title>cv.lv · jaunas vakances no 2000 €</title>"
        f"<link>{escape(SEARCH_PAGE)}</link>"
        f'<atom:link href="{FEED_URL}" rel="self" type="application/rss+xml"/>'
        "<description>Vakances, kas cv.lv parādās pirmo reizi</description>"
        "<language>lv</language>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        + "\n".join(entries)
        + "</channel></rss>\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument(
        "--since",
        default="",
        help="also put fresh ads published since this Riga time "
        "(YYYY-MM-DD or YYYY-MM-DD HH:MM) into the feed",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    seen_path = args.site / "seen.csv"
    items_path = args.site / "items.json"

    live = fetch_vacancies()
    if not live:
        raise SystemExit("cv.lv returned no vacancies; leaving state untouched")

    seen = load_seen(seen_path)
    first_run = seen is None
    seen = seen or {}
    excluded = load_excluded(Path("excluded_employers.txt"))
    items = (
        {item["id"]: item for item in json.loads(items_path.read_text("utf-8"))}
        if items_path.exists()
        else {}
    )

    new_ids = [vacancy_id for vacancy_id in live if vacancy_id not in seen]
    for vacancy_id in new_ids:
        seen[vacancy_id] = now.isoformat()
    # First run: everything live counts as covered by the EXPIRING pass.
    feed_ids = [] if first_run else list(new_ids)

    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=RIGA)
        feed_ids += [
            vacancy_id
            for vacancy_id, vacancy in live.items()
            if vacancy["renewedDate"] is None
            and parse_time(vacancy["publishDate"]) >= since
        ]

    added = 0
    for vacancy_id in dict.fromkeys(feed_ids):
        vacancy = live[vacancy_id]
        if vacancy_id in items or is_excluded(vacancy, excluded):
            continue
        items[vacancy_id] = to_item(vacancy, now.isoformat())
        added += 1

    cutoff = now - timedelta(days=FEED_DAYS)
    kept = [item for item in items.values() if parse_time(item["firstSeen"]) >= cutoff]
    kept.sort(key=lambda item: (item["firstSeen"], item["publishDate"]), reverse=True)

    args.site.mkdir(parents=True, exist_ok=True)
    save_seen(seen_path, seen)
    items_path.write_text(
        json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (args.site / "feed.xml").write_text(build_feed(kept, now), encoding="utf-8")
    print(
        f"Live: {len(live)} | first seen now: {len(new_ids)} | "
        f"added to feed: {added} | in feed: {len(kept)}"
    )


if __name__ == "__main__":
    main()
