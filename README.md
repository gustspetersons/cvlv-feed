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

cv.lv lets an hourly-paid ad through when the top of its range clears 2000 EUR,
so the feed also drops hourly ads whose lowest rate × 168 hours comes to less
than 2000 EUR a month (under about 11.90 EUR/h).

A renewal keeps the vacancy's ID, so renewed ads already seen never come back.
An expired ad brought back by a renewal is new, so it does appear, marked
"Atjaunināts".

## Day to day

- **Reading:** subscribe to the feed in an RSS reader (Inoreader). The reader
  remembers what has been read; nothing needs marking by hand here.
- **Excluding employers:** add a name to `excluded_employers.txt`.
- **Excluding by word:** add a word stem to `excluded_titles.txt` to match
  position titles only, or to `excluded_keywords.txt` to match titles and
  cv.lv's keywords too ("kasier" catches every ending).
- All three lists also clear matching ads already in the feed on the next run.
- **Backfill:** Actions → Update feed → Run workflow, with a `since` time, adds
  every fresh ad published since then that isn't in the feed yet.
- **If it breaks** (cv.lv changes its API), the run fails and GitHub emails a
  notice. A brief network blip doesn't: each request is retried three times
  over about two minutes, and only a warning shows on the run.
- **Health checks:** the run also fails, after saving its state, when it
  fetches more than 5 ads fewer than the total cv.lv reports (twice in a row),
  or when no new ad has turned up for 4 days. The failed step, "Check feed
  health", says which.
- **Staying on schedule:** GitHub turns schedules off in public repos after 60
  days without activity, which would make the feed go quiet with no email.
  Every run re-enables the workflow to reset that counter.
