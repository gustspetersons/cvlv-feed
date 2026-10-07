# cvlv-feed

An RSS feed of [cv.lv](https://www.cv.lv) vacancies with a salary from 2000 EUR
that appear for the first time. Renewed ads ("Atjaunināts") that were already
seen stay out.

**Feed:** https://gustspetersons.github.io/cvlv-feed/feed.xml

## How it works

Every two hours a GitHub Actions job pulls the full list behind
`cv.lv/lv/search?salaryFrom=2000` from cv.lv's search API and compares the
vacancy IDs with every ID seen before (`seen.csv` on the `gh-pages` branch).
IDs it has never seen go into the feed, which keeps the last 14 days of them.

A renewal keeps the vacancy's ID, so renewed ads already seen never come back.
An expired ad brought back by a renewal is new, so it does appear, marked
"Atjaunināts".

## Day to day

- **Reading:** subscribe to the feed in an RSS reader (Inoreader). The reader
  remembers what has been read; nothing needs marking by hand here.
- **Excluding employers:** add a name to `excluded_employers.txt`.
- **Backfill:** Actions → Update feed → Run workflow, with a `since` time, adds
  every fresh ad published since then that isn't in the feed yet.
- **If it breaks** (cv.lv changes its API), the run fails and GitHub emails a
  notice.
