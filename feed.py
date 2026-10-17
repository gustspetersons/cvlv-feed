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
import http.client
import json
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

API_URL = "https://www.cv.lv/api/v1/vacancy-search-service/search"
MIN_SALARY = 2000
SEARCH_PARAMS = {"salaryFrom": MIN_SALARY, "sorting": "LATEST"}
SEARCH_PAGE = "https://www.cv.lv/lv/search?salaryFrom=2000&sorting=LATEST"
VACANCY_URL = "https://www.cv.lv/lv/vacancy/{id}"
FEED_URL = "https://gustspetersons.github.io/cvlv-feed/feed.xml"
USER_AGENT = "cvlv-feed/1.0 (personal RSS; github.com/gustspetersons/cvlv-feed)"

PAGE_SIZE = 500
MAX_PAGES = 20
ATTEMPTS = 4  # tries per page before the run gives up
RETRY_WAIT = 15  # seconds before the first retry, doubled for each one after
FEED_DAYS = 14
HOURS_PER_MONTH = 168  # a 40-hour week, to turn an hourly rate into a monthly one
RIGA = ZoneInfo("Europe/Riga")

TOWNS = {543: "Rīga"}
REMOTE_TYPES = {
    "ON_SITE": "klātienē",
    "HYBRID": "hibrīds",
    "FULLY_REMOTE": "attālināti",
}


def parse_time(value):
    return datetime.fromisoformat(value) if value else None


def fetch_page(params):
    """Return one page of search results, retrying when cv.lv drops the line.

    Now and then cv.lv cuts a response off halfway, times out or answers with
    a 5xx; the same request a little later goes through. Other HTTP errors
    (a 4xx other than 429) fail straight away, since a retry won't fix them.
    """
    request = urllib.request.Request(
        f"{API_URL}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            transient = error.code >= 500 or error.code == 429
            if not transient or attempt == ATTEMPTS:
                raise
            reason = f"HTTP {error.code}"
        except (http.client.HTTPException, OSError, json.JSONDecodeError) as error:
            if attempt == ATTEMPTS:
                raise
            reason = type(error).__name__
        wait = RETRY_WAIT * 2 ** (attempt - 1)
        print(
            f"::warning::cv.lv request failed ({reason}) at offset "
            f"{params['offset']}; retry {attempt} of {ATTEMPTS - 1} in {wait} s"
        )
        time.sleep(wait)


def fetch_vacancies():
    """Return every live vacancy matching SEARCH_PARAMS, keyed by ID."""
    vacancies, total, offset = {}, None, 0
    for _ in range(MAX_PAGES):
        page = fetch_page({**SEARCH_PARAMS, "limit": PAGE_SIZE, "offset": offset})
        total = page["total"]
        batch = page["vacancies"]
        for vacancy in batch:
            vacancies[vacancy["id"]] = vacancy
        offset += len(batch)
        if not batch or offset >= total:
            break
        time.sleep(1)
    if total and len(vacancies) < total:
        print(f"::warning::got {len(vacancies)} of {total} vacancies")
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


def fold(text):
    """Normalise text for case-insensitive matching of Latvian letters."""
    return unicodedata.normalize("NFC", text or "").casefold()


def load_excluded(path):
    if not path.exists():
        return []
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [fold(line) for line in lines if line and not line.startswith("#")]


def pays_too_little(vacancy):
    """Is the ad paid by the hour with a floor under MIN_SALARY a month?

    cv.lv lets an hourly ad through when the top of its range clears the salary
    filter, so shift jobs at 7–22 €/h show up. An ad with no floor is kept.
    """
    low = vacancy.get("salaryFrom")
    if not vacancy.get("hourlySalary") or low is None:
        return False
    return low * HOURS_PER_MONTH < MIN_SALARY


def is_excluded(vacancy, employers, titles, keywords):
    """Is the ad underpaid, from an excluded employer, or carrying an excluded word?

    Words in `titles` match the position title only; words in `keywords` match
    the title and cv.lv's own keywords for the ad.
    """
    employer = fold(vacancy.get("employerName"))
    title = fold(vacancy.get("positionTitle"))
    tags = [fold(tag) for tag in vacancy.get("keywords") or []]
    return (
        pays_too_little(vacancy)
        or any(name in employer for name in employers)
        or any(word in title for word in titles + keywords)
        or any(word in tag for word in keywords for tag in tags)
    )


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
    excluded = (
        load_excluded(Path("excluded_employers.txt")),
        load_excluded(Path("excluded_titles.txt")),
        load_excluded(Path("excluded_keywords.txt")),
    )
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
        if vacancy_id in items or is_excluded(vacancy, *excluded):
            continue
        items[vacancy_id] = to_item(vacancy, now.isoformat())
        added += 1

    # Exclusions also clear ads already in the feed, so a list edit applies to
    # the whole feed on the next run.
    cutoff = now - timedelta(days=FEED_DAYS)
    kept = [
        item
        for item in items.values()
        if parse_time(item["firstSeen"]) >= cutoff and not is_excluded(item, *excluded)
    ]
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
