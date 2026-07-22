"""
Recon pass for a new, genuinely independent prediction source: raw
Statcast (Baseball Savant) and FanGraphs stats via the pybaseball package,
as opposed to DRatings/MoundEdge which aggregate other sites' predictions.

Prints real sample data + column listings to the job log so the actual
scoring formula can be built against real field names rather than guessed
from pybaseball's docs - same recon pattern used for MoundEdge/
SportsBettingDime/Kalshi earlier in this project. This dev sandbox cannot
reach baseballsavant.mlb.com or fangraphs.com directly (confirmed:
requests.exceptions.ProxyError / 403 Forbidden on both, from the sandbox's
outbound proxy), so this only produces real output via GitHub Actions
workflow_dispatch.

Today's probable starting pitchers come from the MLB Stats API
(statsapi.mlb.com), a free, unauthenticated, official endpoint - not one
of this project's four core sources, just used here to know which
pitchers to sample.
"""

import sys
import traceback
from datetime import date, timedelta

import requests


def hr(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def probe_todays_probable_pitchers():
    hr("MLB Stats API: today's probable starting pitchers")
    today = date.today().isoformat()
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today}&hydrate=probablePitcher,team"
    r = requests.get(url, timeout=20)
    print(f"status={r.status_code}")
    data = r.json()
    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            away, home = g["teams"]["away"], g["teams"]["home"]
            entry = {
                "away_team": away["team"]["name"],
                "home_team": home["team"]["name"],
                "away_pitcher": away.get("probablePitcher", {}).get("fullName"),
                "away_pitcher_id": away.get("probablePitcher", {}).get("id"),
                "home_pitcher": home.get("probablePitcher", {}).get("fullName"),
                "home_pitcher_id": home.get("probablePitcher", {}).get("id"),
            }
            games.append(entry)
            print(entry)
    return games


def probe_statcast_pitcher(pitcher_id, pitcher_name):
    import pybaseball as pb

    hr(f"Statcast: {pitcher_name} (id={pitcher_id}) - last 30 days pitch-level data")
    end = date.today()
    start30 = end - timedelta(days=30)
    df30 = pb.statcast_pitcher(str(start30), str(end), pitcher_id)
    print(f"rows (30d): {len(df30)}")
    print(f"columns ({len(df30.columns)}): {list(df30.columns)}")
    if len(df30):
        print("\nsample row (full):")
        print(df30.iloc[0].to_dict())
        relevant = [
            "release_speed", "pitch_type", "description", "events", "type",
            "estimated_woba_using_speedangle", "woba_value", "woba_denom",
            "launch_speed", "launch_angle", "bb_type",
        ]
        present = [c for c in relevant if c in df30.columns]
        print(f"\nrelevant columns present ({len(present)}/{len(relevant)}): {present}")
        missing = [c for c in relevant if c not in df30.columns]
        if missing:
            print(f"relevant columns MISSING: {missing}")
        print("\nfirst 10 rows of relevant columns:")
        print(df30[present].head(10).to_string())


def probe_fangraphs_team_batting():
    import pybaseball as pb

    hr("FanGraphs: team batting (season-to-date, current year)")
    year = date.today().year
    try:
        df = pb.team_batting(year, year)
        print(f"rows: {len(df)}")
        print(f"columns ({len(df.columns)}): {list(df.columns)}")
        relevant = [c for c in df.columns if "wOBA" in c or "wRC" in c or c == "Team"]
        print(f"\nrelevant columns: {relevant}")
        print(df[relevant].head(30).to_string())
        print("\nFANGRAPHS TEAM BATTING: OK")
    except Exception as e:
        print(f"\nFANGRAPHS TEAM BATTING BLOCKED: {type(e).__name__}: {e}")
        print("This is the known FanGraphs/Cloudflare bot-protection pattern in cloud/CI IPs.")
        traceback.print_exc()


def probe_fangraphs_pitching():
    import pybaseball as pb

    hr("FanGraphs: pitching_stats (season-to-date, current year) - for starter-level xFIP/K-BB% etc")
    year = date.today().year
    try:
        df = pb.pitching_stats(year, year, qual=1)
        print(f"rows: {len(df)}")
        print(f"columns ({len(df.columns)}): {list(df.columns)}")
        print("\nFANGRAPHS PITCHING: OK")
    except Exception as e:
        print(f"\nFANGRAPHS PITCHING BLOCKED: {type(e).__name__}: {e}")
        traceback.print_exc()


def probe_savant_team_leaderboard():
    """Workaround candidate #1 for the FanGraphs block: Baseball Savant's
    own custom-leaderboard CSV export, same host as statcast_pitcher (which
    worked), so it should not hit the same Cloudflare block."""
    hr("Workaround candidate: Baseball Savant custom leaderboard CSV (team xwOBA)")
    year = date.today().year
    url = (
        f"https://baseballsavant.mlb.com/leaderboard/custom?year={year}&type=team"
        f"&min=1&selections=xwoba,woba&chart=false&x=xwoba&y=xwoba&r=no"
        f"&chartType=beeswarm&csv=true"
    )
    try:
        r = requests.get(url, timeout=20)
        print(f"status={r.status_code}  bytes={len(r.content)}")
        print(r.text[:2000])
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()


def probe_bbref_team_batting():
    """Workaround candidate #2 for wRC+ specifically (FanGraphs-proprietary,
    no Savant equivalent): Baseball-Reference via pybaseball, which is a
    different host/scraper path than FanGraphs."""
    import pybaseball as pb

    hr("Workaround candidate: Baseball-Reference team_batting_bref (one sample team)")
    year = date.today().year
    try:
        df = pb.team_batting_bref("NYY", year, year)
        print(f"rows: {len(df)}")
        print(f"columns ({len(df.columns)}): {list(df.columns)}")
        print(df.head(5).to_string())
        print("\nBBREF TEAM BATTING: OK")
    except Exception as e:
        print(f"\nBBREF TEAM BATTING BLOCKED/FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()


def probe_league_wide_statcast_pull():
    """Verifies a full-league (all games, all batters) Statcast pull over a
    rolling window is fast enough to build team-level xwOBA aggregates
    directly from raw pitch-level data - this turned out to be a cleaner
    path than guessing at a Savant team-leaderboard URL, and matches the
    "raw stats, not someone else's aggregation" goal better anyway."""
    import time

    import pybaseball as pb

    hr("Full-league Statcast pull (15-day window) - team xwOBA aggregation feasibility")
    end = date.today()
    start = end - timedelta(days=15)
    t0 = time.time()
    df = pb.statcast(str(start), str(end))
    elapsed = time.time() - t0
    print(f"elapsed: {elapsed:.1f}s, rows: {len(df)}")
    if len(df) == 0:
        print("No rows returned - can't test aggregation.")
        return

    cols = ["home_team", "away_team", "inning_topbot", "woba_value", "woba_denom", "estimated_woba_using_speedangle"]
    present = [c for c in cols if c in df.columns]
    print(f"relevant columns present: {present}")

    # batting team = away_team when inning_topbot == 'Top' (visitors bat top of
    # inning), home_team when 'Bot' - standard Statcast convention
    df = df.dropna(subset=["woba_denom"])
    df = df[df["woba_denom"] > 0]
    df["batting_team"] = df.apply(lambda r: r["away_team"] if r["inning_topbot"] == "Top" else r["home_team"], axis=1)
    df["xwoba_component"] = df["estimated_woba_using_speedangle"].fillna(df["woba_value"])

    team_agg = df.groupby("batting_team").apply(
        lambda g: (g["xwoba_component"] * g["woba_denom"]).sum() / g["woba_denom"].sum()
    )
    print(f"\nteam-level xwOBA aggregate ({len(team_agg)} teams):")
    print(team_agg.sort_values(ascending=False).to_string())
    league_avg = (df["xwoba_component"] * df["woba_denom"]).sum() / df["woba_denom"].sum()
    print(f"\nleague average xwOBA over this window: {league_avg:.3f}")


def probe_park_factors():
    hr("Park factors: checking what pybaseball actually provides")
    import pybaseball as pb

    try:
        df = pb.park_codes()
        print(f"park_codes() columns: {list(df.columns)}")
        print(df.head(5).to_string())
        print(
            "\nNOTE: this is Retrosheet park ID/metadata only (name, location, "
            "years active) - NOT run-scoring park factor numbers. pybaseball has "
            "no dedicated park-factor function; that would need a separate source "
            "(e.g. scraping FanGraphs' guts.aspx?type=pf page directly, or a "
            "small hand-maintained table since factors barely move mid-season)."
        )
    except Exception as e:
        print(f"FAILED: {e}")
        traceback.print_exc()


def main():
    games = probe_todays_probable_pitchers()

    sample_pitchers = []
    for g in games:
        if g["away_pitcher_id"]:
            sample_pitchers.append((g["away_pitcher_id"], g["away_pitcher"]))
        if g["home_pitcher_id"]:
            sample_pitchers.append((g["home_pitcher_id"], g["home_pitcher"]))
        if len(sample_pitchers) >= 2:
            break

    if not sample_pitchers:
        hr("No probable pitchers found in today's schedule - can't sample Statcast pitcher data")
    for pid, name in sample_pitchers:
        try:
            probe_statcast_pitcher(pid, name)
        except Exception as e:
            hr(f"Statcast probe failed for {name} ({pid}): {e}")
            traceback.print_exc()

    try:
        probe_fangraphs_team_batting()
    except Exception as e:
        hr(f"FanGraphs team_batting probe crashed outright: {e}")
        traceback.print_exc()

    try:
        probe_fangraphs_pitching()
    except Exception as e:
        hr(f"FanGraphs pitching_stats probe crashed outright: {e}")
        traceback.print_exc()

    try:
        probe_savant_team_leaderboard()
    except Exception as e:
        hr(f"Savant team leaderboard probe crashed outright: {e}")
        traceback.print_exc()

    try:
        probe_bbref_team_batting()
    except Exception as e:
        hr(f"Baseball-Reference probe crashed outright: {e}")
        traceback.print_exc()

    try:
        probe_league_wide_statcast_pull()
    except Exception as e:
        hr(f"League-wide Statcast pull probe crashed outright: {e}")
        traceback.print_exc()

    probe_park_factors()
    print("\n\nDONE.")


if __name__ == "__main__":
    sys.exit(main())
