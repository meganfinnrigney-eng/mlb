# MLB Daily Analysis

A personal-learning tool that pulls MLB data from four public sources each
day and builds a static HTML report comparing model projections, market
data, and public/Reddit sentiment. It exists to compare predictions against
actual outcomes over time — **it does not include betting units, stake
sizing, or recommended plays anywhere.**

## Sources

1. **[SportsBettingDime](https://www.sportsbettingdime.com/mlb/public-betting-trends/)**
   — public betting splits. Its real percentages are rendered client-side by
   a JS widget with no public JSON/CSV endpoint (checked and confirmed —
   see `scripts/probe_sources.py` for the recon), so this report uses
   MoundEdge's embedded bets%/money% splits instead, which mirror
   SportsBettingDime's numbers.
2. **[DRatings](https://www.dratings.com/predictor/mlb-baseball-predictions/)**
   — model projected score, win probability, and best market lines. Plain
   server-rendered HTML, no JS needed.
3. **[MoundEdge](https://moundedge.github.io/MLB-Summaries/)** — BPP sim
   projections, weather/park effects, pitcher splits, and trend data. Static
   HTML, the richest of the four sources.
4. **Reddit** — today's MLB daily discussion thread, via the
   unauthenticated `.json` endpoints (no OAuth app registration needed).

## How it runs

`.github/workflows/daily-report.yml` runs `main.py` once a day (11:00 UTC,
before first pitch) via GitHub Actions `schedule`, and on-demand via
`workflow_dispatch`. It writes `docs/<date>.html` and `docs/index.html` and
commits them back to the repository.

**Scheduled workflows only fire from the repository's default branch.**
`claude/mlb-daily-analysis-573rh3` is that default branch (this repo had no
commits before this project), so the daily cron is already active - no
merge needed. If you later rename the default branch, move this workflow
file along with it.

### Enabling GitHub Pages (one-time, manual)

To browse the report at a URL instead of viewing raw HTML files in the repo:
Settings → Pages → Source: "Deploy from a branch" → Branch:
`claude/mlb-daily-analysis-573rh3` (or whatever the default branch is named
at the time), folder: `/docs`.

## Reddit fallback

Reddit blocks a lot of automated/datacenter traffic outright — this project
retries with backoff and a descriptive User-Agent, but some days the fetch
will simply fail. When it does, the report notes it and skips the Reddit
section rather than crashing. To include Reddit sentiment on a day the
automated fetch failed, paste the daily thread's text into:

```
mlb_daily/data/reddit_manual_<YYYY-MM-DD>.txt
```

then re-run the workflow (`workflow_dispatch`) — it's picked up automatically.

## Notable-game triggers

Every game is checked against six triggers (thresholds in
`mlb_daily/analysis/build.py`):

- **(a)** model total vs. market total gap `> 1.0` runs
- **(b)** DRatings vs. MoundEdge BPP disagree on winner or total (`> 1.0` run gap)
- **(c)** betting split lopsided — bets% vs money% diverge `> 15` points
- **(d)** starting pitcher's contextual (home/road) ERA vs. season ERA `> 1.0`
- **(e)** weather/park effect (BPP net%) `>= 8%`
- **(f)** MoundEdge's own trend arrow contradicts its L30-vs-season numbers

## Local development / re-probing sources

`scripts/probe_sources.py` is the reconnaissance script used to figure out
each source's structure before writing parsers (kept for future reference —
if a site changes shape, run `.github/workflows/probe-sources.yml` via
`workflow_dispatch` and read the job log). It's not part of the daily
pipeline.

To run the report generator locally: `pip install -r requirements.txt &&
python main.py` (writes to `docs/`). Network access to all four sources is
required — this repo's own dev sandbox couldn't reach any of them due to an
egress policy, which is why the probe workflow exists.
