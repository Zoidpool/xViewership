"""In depth: the season story behind a live moment.

Each insight gets a few sentences of context built from the season so far
(team profiles: match-by-match goals and xG, comebacks, discipline; player
profiles: per-90 values and percentiles within their role). Every number
comes from the season data, so the narrator's fact-checker accepts it.
"""
from __future__ import annotations

from .state import MatchState


def _ord(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


ROLE_PLURAL = {"GK": "goalkeepers", "CB": "centre-backs", "FB": "full-backs", "DM": "defensive midfielders",
               "CM": "central midfielders", "AM": "attacking midfielders", "W": "wingers", "ST": "strikers"}


def season_depth(eng, st: MatchState, ev: dict, kind: str, code: str | None, facts: dict) -> list[tuple[str, str]]:
    ctx = eng.ctx
    tp = ctx.team_profiles
    out: list[tuple[str, str]] = []
    name = eng.name
    if not tp:
        return out

    def team_line(c: str) -> dict | None:
        return tp.get(c)

    def player_line(pid: str | None, keys: list[str]) -> None:
        prof = ctx.profiles.get(pid or "")
        if not prof or not prof.get("eligible"):
            return
        group = ROLE_PLURAL.get(prof["role"], "players")
        bits = []
        for k in keys:
            v, pc = prof["values"].get(k), prof["pct"].get(k)
            if v is None or pc is None:
                continue
            label = {"goals": "goals", "npxg": "non-penalty xG", "xa": "expected assists", "shots": "shots",
                     "key_passes": "key passes", "dribbles_ok": "successful dribbles", "saves": "saves",
                     "save_pct": "save rate", "goals_prevented": "goals prevented", "big_chances_missed":
                     "big chances missed", "fouls": "fouls", "tackles": "tackles won"}.get(k, k)
            rank = f"the best of the league's {group}" if pc == 100 else f"better than {pc}% of the league's {group}"
            bits.append(f"{v:.2f} {label} per 90 ({rank})" if k != "save_pct" else f"a {v:.1f}% save rate ({rank})")
        if bits:
            out.append(("player_season", f"{prof['name']}'s season: " + "; ".join(bits[:3]) + "."))

    if kind == "goal" and code:
        t, opp = team_line(code), st.other(code)
        o = team_line(opp)
        now = st.teams[code].goals
        if t:
            mp = t["mp"]
            k = sum(1 for m in t["matches"] if m["gf"] >= now)
            if now >= 2:
                out.append(("goals_in_game", f"{name(code)} have scored {now} or more in {k} of their {mp} league games"
                            if k else f"the first time this season {name(code)} have scored {now} in a game"))
            out.append(("season_goals", f"{name(code)}'s {_ord(t['values']['gf'] + now)} league goal of the season, "
                        f"{t['values']['xgf']} xG per match on average; {st.teams[code].xg:.2f} xG so far today"))
            sc = st.score()
            if sc[code] == sc[opp] and any(c != code for _, c, _ in st.score_history[:1]):
                pfb = t["values"].get("points_from_behind", 0)
                out.append(("from_behind", f"before today {name(code)} had taken {pfb} points from losing positions this season"
                            if pfb else f"{name(code)} had not taken a single point from a losing position all season"))
        if o:
            conceded_now = st.teams[code].goals
            k2 = sum(1 for m in o["matches"] if m["ga"] >= conceded_now)
            if conceded_now >= 2:
                out.append(("opp_conceded", f"{name(opp)} have conceded {conceded_now} or more in {k2} of {o['mp']} games"
                            if k2 else f"{name(opp)} had never conceded {conceded_now} in a league game this season"))
            else:
                r = o["ranks"]["xga"]
                out.append(("opp_defence", f"{name(opp)} concede {o['values']['xga']} xG per match, "
                            f"{'the best' if r == 1 else _ord(r) + ' best'} in the league"))
        player_line(ev.get("player_id"), ["goals", "npxg", "shots"])
    elif kind == "red_card" and code:
        t = team_line(code)
        if t:
            most = ctx.league_teams + 1 - t["ranks"]["yellows"]
            where = "the most" if most == 1 else "the fewest" if most == ctx.league_teams else f"the {_ord(most)} most"
            out.append(("discipline", f"{name(code)} average {t['values']['yellows']} yellow cards a game, {where} in the league"))
        prof = ctx.profiles.get(ev.get("player_id") or "")
        if prof:
            y = int(prof["totals"].get("yellows", 0))
            out.append(("player_cards", f"{prof['name']} had {y} yellow card{'' if y == 1 else 's'} "
                        f"in {prof['apps']} league games before today"))
        player_line(ev.get("player_id"), ["fouls", "tackles"])
    elif kind == "big_save":
        player_line(ev.get("keeper_id"), ["saves", "save_pct", "goals_prevented"])
        t = team_line(st.other(ev["team"])) if ev.get("team") else None
        if t:
            out.append(("clean_sheets", f"{t['name']} have kept {t['values']['clean_sheets']} clean sheets in {t['mp']} games"))
    elif kind == "big_miss" and code:
        player_line(ev.get("player_id"), ["big_chances_missed", "npxg", "goals"])
        t = team_line(code)
        if t:
            diff = round(t["values"]["gf"] - t["values"]["xgf"] * t["mp"], 1)
            out.append(("finishing", f"{name(code)} have {t['values']['gf']} goals from "
                        f"{round(t['values']['xgf'] * t['mp'], 1)} xG this season ({'+' if diff >= 0 else ''}{diff})"))
    elif kind in ("momentum", "pressure") and code:
        t = team_line(code)
        if t:
            out.append(("season_attack", f"{name(code)} average {t['values']['xgf']} xG and {t['values']['field_tilt']}% "
                        f"field tilt per match this season; today {st.teams[code].xg:.2f} xG and {st.field_tilt(code)}% so far"))
    elif kind == "preview":
        h, a = team_line(st.home), team_line(st.away)
        if h and a:
            out.append(("home_away", f"{name(st.home)} take {h['home_ppg']} points per game at home; "
                        f"{name(st.away)} take {a['away_ppg']} away"))
            out.append(("xg_profile", f"xG per match: {name(st.home)} {h['values']['xgf']} for, {h['values']['xga']} against; "
                        f"{name(st.away)} {a['values']['xgf']} for, {a['values']['xga']} against"))
            meet = [m for m in h["matches"] if m["opp"] == st.away]
            if meet:
                m = meet[-1]
                out.append(("earlier_meeting", f"when they met in round {m['round']}, the score was "
                            f"{m['gf'] if m['home'] else m['ga']}-{m['ga'] if m['home'] else m['gf']} "
                            f"({name(st.home) if m['home'] else name(st.away)} at home), xG "
                            f"{m['xgf'] if m['home'] else m['xga']}-{m['xga'] if m['home'] else m['xgf']}"))
    elif kind in ("half_time", "full_time"):
        for c in (st.home, st.away):
            t = team_line(c)
            if not t:
                continue
            out.append(("vs_season", f"{name(c)}: {st.possession(c)}% possession (season {t['values']['possession']}%), "
                        f"{st.teams[c].xg:.2f} xG (season {t['values']['xgf']} per match)"))
        if kind == "full_time":
            sc = st.score()
            for c in (st.home, st.away):
                t = team_line(c)
                if not t:
                    continue
                pts = t["values"]["pts"] + (3 if sc[c] > sc[st.other(c)] else 1 if sc[c] == sc[st.other(c)] else 0)
                out.append(("table", f"{name(c)} move to {pts} points from {t['mp'] + 1} games"))
    return out
