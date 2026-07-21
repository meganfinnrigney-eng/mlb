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

## Reading it daily

The live report is published as a Claude Artifact:
**https://claude.ai/code/artifact/cc53d3a4-0284-4b9e-adec-df02706e6765**

A Claude Code Remote Routine ("MLB Daily Analysis — Artifact Refresh", cron
`20 14 * * *`) fires 20 minutes after the GitHub Actions job, pulls the
freshly-generated `docs/artifact_fragment.html`, and redeploys it to that
same URL, so the link never changes. `docs/index.html` (the full HTML page,
not the artifact fragment) is still generated too and works as a plain
GitHub Pages site if you'd rather host it that way instead/as well.

## How it runs

`.github/workflows/daily-report.yml` runs `main.py` once a day (14:00 UTC)
via GitHub Actions `schedule`, and on-demand via `workflow_dispatch`. It
writes `docs/<date>.html` and `docs/index.html` and commits them back to
the repository.

The 14:00 UTC time (rather than an earlier, "well before first pitch"
time) is a deliberate choice: MoundEdge's daily page has been observed to
still show the *previous* day's slate as late as 4am Eastern. If a source
is still stale by the time the report runs, `main.py` detects it (comparing
today's date against MoundEdge's own slate-date subtitle) and the report
shows an explicit "may be stale" banner instead of silently presenting
yesterday's games as today's.

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

Reddit blocks a lot of automated/datacenter traffic outright (confirmed: a
403 "blocked due to network policy" response, even from GitHub's own
runners, not just rate-limiting) — this project retries with backoff and a
descriptive User-Agent, but most days the automated fetch will simply fail.
When it does, the report notes it plainly and skips the Reddit section
rather than crashing.

**To include Reddit sentiment on a given day: paste the daily thread's text
as a message in a Claude session on this project.** No GitHub or git needed
— just paste the text and ask for it to be picked up; it gets written to
`mlb_daily/data/reddit_manual_<YYYY-MM-DD>.txt` and the workflow is
re-run so the report (and the published artifact) reflect it right away.
(Under the hood: `reddit.py` checks for that file before giving up, so
committing it there manually - e.g. via GitHub's web UI - and re-running
`workflow_dispatch` works too, if you'd rather skip the chat step.)

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
