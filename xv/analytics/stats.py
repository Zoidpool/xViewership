"""Season aggregation: every player's and team's counts from the event files.

One pass over each match produces per-player counts, minutes, a match rating
with its factor breakdown, and per-team match rows. Everything downstream
(per-90 rates, percentiles, archetypes, team ranks, models) reads from here.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..generator.tracking import build_tracking
from .zones import GRID_X, GRID_Y, match_zones

# key: (label, category, kind, higher_is_better, extra)
#   kind "count" -> shown per 90; "pct" -> ratio of two counts (extra = (num, den, min attempts));
#   "avg" -> mean of a per-event value (extra = (sum key, count key)); "max" -> season max;
#   "total" -> season total, not per 90
CATALOG: dict[str, tuple] = {
    # attacking
    "goals": ("Goals", "Attacking", "count", True, None),
    "npxg": ("Non-penalty xG", "Attacking", "count", True, None),
    "xg": ("Expected goals (xG)", "Attacking", "count", True, None),
    "shots": ("Shots", "Attacking", "count", True, None),
    "sot": ("Shots on target", "Attacking", "count", True, None),
    "sot_pct": ("Shots on target %", "Attacking", "pct", True, ("sot", "shots", 8)),
    "xg_per_shot": ("xG per shot", "Attacking", "pct", True, ("npxg", "np_shots", 8)),
    "finishing": ("Goals minus xG", "Attacking", "count", True, None),
    "big_chances": ("Big chances (xG 0.3+)", "Attacking", "count", True, None),
    "big_chances_missed": ("Big chances missed", "Attacking", "count", False, None),
    "headers": ("Headed shots", "Attacking", "count", True, None),
    "box_touches": ("Touches in the box", "Attacking", "count", True, None),
    "offsides": ("Offsides", "Attacking", "count", False, None),
    "shot_speed": ("Average shot speed (km/h)", "Attacking", "avg", True, ("shot_speed_sum", "shots")),
    "shot_speed_max": ("Fastest shot (km/h)", "Attacking", "max", True, None),
    # creating
    "assists": ("Assists", "Creating", "count", True, None),
    "xa": ("Expected assists (xA)", "Creating", "count", True, None),
    "key_passes": ("Key passes", "Creating", "count", True, None),
    "big_chances_created": ("Big chances created", "Creating", "count", True, None),
    "crosses_ok": ("Accurate crosses", "Creating", "count", True, None),
    "cross_pct": ("Cross accuracy %", "Creating", "pct", True, ("crosses_ok", "crosses", 10)),
    "dribbles_ok": ("Successful dribbles", "Creating", "count", True, None),
    "dribble_pct": ("Dribble success %", "Creating", "pct", True, ("dribbles_ok", "dribbles", 8)),
    "fouls_won": ("Fouls won", "Creating", "count", True, None),
    # passing
    "passes": ("Passes", "Passing", "count", True, None),
    "passes_ok": ("Accurate passes", "Passing", "count", True, None),
    "pass_pct": ("Pass accuracy %", "Passing", "pct", True, ("passes_ok", "passes", 50)),
    "final_third": ("Passes into the final third", "Passing", "count", True, None),
    "progressive": ("Progressive passes", "Passing", "count", True, None),
    "long_ok": ("Accurate long balls", "Passing", "count", True, None),
    "long_pct": ("Long-ball accuracy %", "Passing", "pct", True, ("long_ok", "long", 8)),
    "pass_length": ("Average pass length (m)", "Passing", "avg", True, ("pass_len_sum", "passes")),
    "pass_difficulty": ("Pass difficulty (0-100)", "Passing", "avg", True, ("pass_diff_sum", "passes")),
    # defending
    "tackles": ("Tackles won", "Defending", "count", True, None),
    "interceptions": ("Interceptions", "Defending", "count", True, None),
    "clearances": ("Clearances", "Defending", "count", True, None),
    "blocks": ("Blocked shots", "Defending", "count", True, None),
    "def_actions": ("Defensive actions", "Defending", "count", True, None),
    "dribbled_past": ("Dribbled past", "Defending", "count", False, None),
    # duels
    "aerials_won": ("Aerial duels won", "Duels", "count", True, None),
    "aerial_pct": ("Aerial duels won %", "Duels", "pct", True, ("aerials_won", "aerials", 8)),
    "duels_won": ("Duels won", "Duels", "count", True, None),
    "duel_pct": ("Duels won %", "Duels", "pct", True, ("duels_won", "duels", 15)),
    # discipline
    "fouls": ("Fouls committed", "Discipline", "count", False, None),
    "yellows": ("Yellow cards", "Discipline", "total", False, None),
    "reds": ("Red cards", "Discipline", "total", False, None),
    # goalkeeping
    "saves": ("Saves", "Goalkeeping", "count", True, None),
    "save_pct": ("Save %", "Goalkeeping", "pct", True, ("saves", "sot_faced", 15)),
    "goals_prevented": ("Goals prevented (xGOT - goals)", "Goalkeeping", "count", True, None),
    "conceded": ("Goals conceded", "Goalkeeping", "count", False, None),
    "clean_sheets": ("Clean sheets", "Goalkeeping", "total", True, None),
    # physical
    "distance": ("Distance covered (km)", "Physical", "count", True, None),
    "top_speed": ("Top speed (km/h)", "Physical", "max", True, None),
    "sprints": ("Sprints", "Physical", "count", True, None),
    # overall
    "rating": ("xV rating", "Overall", "avg", True, ("rating_sum", "rated_apps")),
}

# match rating: 6.0 + factor contributions (shown as the "ranking factors")
RATING_FACTORS = {
    "goals": 1.0, "assists": 0.7, "xg": 0.35, "xa": 0.35, "key_passes": 0.12,
    "dribbles_ok": 0.08, "box_touches": 0.02, "tackles": 0.12, "interceptions": 0.1,
    "clearances": 0.05, "blocks": 0.1, "aerials_won": 0.06, "saves": 0.22,
    "goals_prevented": 0.6, "fouls": -0.05, "dribbled_past": -0.06, "yellows": -0.3,
    "reds": -1.5, "big_chances_missed": -0.25,
}
RATING_FACTOR_LABELS = {
    "goals": "Goals", "assists": "Assists", "xg": "Chance quality (xG)", "xa": "Chances created (xA)",
    "key_passes": "Key passes", "dribbles_ok": "Dribbles", "box_touches": "Box presence",
    "tackles": "Tackles", "interceptions": "Interceptions", "clearances": "Clearances",
    "blocks": "Blocks", "aerials_won": "Aerial duels", "saves": "Saves",
    "goals_prevented": "Goals prevented", "fouls": "Fouls", "dribbled_past": "Beaten by dribbles",
    "yellows": "Cards", "reds": "Cards", "big_chances_missed": "Big chances missed",
    "passing": "Passing accuracy", "result": "Team result", "conceded": "Goals conceded",
}


def pass_difficulty(e: dict) -> float:
    """0-100: longer, more forward, into the box, or crossed = harder."""
    fwd = max(0.0, e.get("end_x", 0) - e.get("x", 0))
    d = (e.get("length", 15) / 40) * 35 + min(fwd, 40) / 40 * 30
    d += 20 if e.get("end_x", 0) > 83 else 0
    d += 15 if e.get("cross") else 0
    return min(100.0, d)


@dataclass
class MatchRow:
    match_id: str
    league: str
    round: int
    home: str
    away: str
    hg: int
    ag: int
    team: dict[str, dict] = field(default_factory=dict)  # club -> team counts for the match
    goal_minutes: list[tuple[int, str]] = field(default_factory=list)  # (minute, club)
    zones: dict[str, dict] = field(default_factory=dict)  # club -> zone counts (zones.match_zones)


def _minutes(lineup_ids, events, end=90) -> dict[str, tuple[int, int]]:
    on = {pid: 0 for pid in lineup_ids}
    off: dict[str, int] = {}
    for e in events:
        if e["type"] == "substitution":
            on[e["player_id"]] = min(e["minute"], end)
            off[e["player_off_id"]] = min(e["minute"], end)
        elif e["type"] == "card" and e["card"] != "yellow":
            off[e["player_id"]] = min(e["minute"], end)
    return {pid: (m, off.get(pid, end)) for pid, m in on.items()}


def aggregate(data_dir: Path) -> dict:
    world = json.loads((data_dir / "world.json").read_text(encoding="utf-8"))
    index = json.loads((data_dir / "season_index.json").read_text(encoding="utf-8"))
    players: dict[str, dict] = {}
    for lg in world["leagues"]:
        for c in lg["clubs"]:
            for p in c["players"]:
                players[p["id"]] = {"meta": p, "c": defaultdict(float), "apps": 0, "starts": 0,
                                    "minutes": 0, "ratings": [], "grid": [0.0] * (GRID_X * GRID_Y)}
    matches: list[MatchRow] = []
    for m in index:
        if "home_goals" not in m:
            continue
        path = data_dir / "matches" / f"{m['match_id']}.jsonl"
        events = [json.loads(l) for l in path.open(encoding="utf-8")]
        row = _one_match(m, events, players)
        tracking = build_tracking(events, {pid: P["meta"] for pid, P in players.items()
                                           if P["meta"]["club"] in (row.home, row.away)})
        row.zones, occ = match_zones(events, tracking)
        for pid, grid in occ.items():
            g = players[pid]["grid"]
            for i, v in enumerate(grid):
                g[i] += v
        matches.append(row)
    return {"world": world, "index": index, "players": players, "matches": matches}


def _one_match(m: dict, events: list[dict], players: dict) -> MatchRow:
    start = events[0]
    home, away = start["home"], start["away"]
    lineup = start["lineups"]["home"] + start["lineups"]["away"]
    mins = _minutes(lineup, events)
    tc = {home: defaultdict(float), away: defaultdict(float)}
    pc: dict[str, defaultdict] = defaultdict(lambda: defaultdict(float))
    opp = {home: away, away: home}
    roles = start["roles"]
    for e in events:
        t, team, pid = e["type"], e.get("team"), e.get("player_id")
        c = pc[pid] if pid else None
        if t == "pass":
            ok = e["outcome"] == "complete"
            tc[team]["passes"] += 1
            tc[team]["passes_ok"] += ok
            c["passes"] += 1
            c["passes_ok"] += ok
            c["pass_len_sum"] += e.get("length", 0)
            c["pass_diff_sum"] += pass_difficulty(e)
            if e.get("cross"):
                c["crosses"] += 1
                c["crosses_ok"] += ok
                tc[team]["crosses"] += 1
            if e.get("long"):
                c["long"] += 1
                c["long_ok"] += ok
            if ok:
                if e.get("end_x", 0) > 66 >= e.get("x", 0):
                    c["final_third"] += 1
                if e.get("end_x", 0) > 66:
                    tc[team]["final_third_passes"] += 1
                if e.get("end_x", 0) - e.get("x", 0) >= 15 and e.get("end_x", 0) > 40:
                    c["progressive"] += 1
                if e.get("box") and e.get("receiver_id"):
                    pc[e["receiver_id"]]["box_touches"] += 1
            if e.get("x", 100) < 60:
                tc[team]["passes_own60"] += 1
        elif t == "shot":
            pen = e.get("situation") == "penalty"
            c["shots"] += 1
            c["np_shots"] += not pen
            c["xg"] += e["xg"]
            c["npxg"] += 0 if pen else e["xg"]
            c["sot"] += e["outcome"] in ("goal", "saved")
            c["big_chances"] += e["xg"] >= 0.3
            c["big_chances_missed"] += e["xg"] >= 0.3 and e["outcome"] != "goal"
            c["headers"] += e.get("body_part") == "head"
            c["shot_speed_sum"] += e.get("speed_kmh", 0)
            c["shot_speed_max"] = max(c["shot_speed_max"], e.get("speed_kmh", 0))
            tc[team]["shots"] += 1
            tc[team]["xg"] += e["xg"]
            tc[team]["sot"] += e["outcome"] in ("goal", "saved")
            if e.get("key_pass_id"):
                k = pc[e["key_pass_id"]]
                k["key_passes"] += 1
                k["xa"] += e["xg"]
                k["big_chances_created"] += e["xg"] >= 0.3
            if e.get("xgot") is not None and e.get("keeper_id"):
                g = pc[e["keeper_id"]]
                g["xgot_faced"] += e["xgot"]
                g["sot_faced"] += 1
        elif t == "goal":
            c["goals"] += 1
            if e.get("assist_id"):
                pc[e["assist_id"]]["assists"] += 1
            if e.get("keeper_id"):
                pc[e["keeper_id"]]["conceded"] += 1
        elif t == "save":
            c["saves"] += 1
        elif t == "dribble":
            c["dribbles"] += 1
            ok = e["outcome"] == "success"
            c["dribbles_ok"] += ok
            c["duels"] += 1
            c["duels_won"] += ok
            if e.get("opponent_id"):
                d = pc[e["opponent_id"]]
                d["duels"] += 1
                d["duels_won"] += not ok
                d["dribbled_past"] += ok
        elif t in ("tackle", "interception", "clearance", "block"):
            key = {"tackle": "tackles", "interception": "interceptions", "clearance": "clearances",
                   "block": "blocks"}[t]
            c[key] += 1
            c["def_actions"] += 1
            if t != "block" and e.get("x", 0) > 40:
                tc[team]["def_actions_high"] += 1
            if t == "tackle":
                c["duels"] += 0  # counted with the dribble that it stopped, if any
        elif t == "aerial":
            c["aerials"] += 1
            c["aerials_won"] += 1
            c["duels"] += 1
            c["duels_won"] += 1
            l = pc[e["loser_id"]]
            l["aerials"] += 1
            l["duels"] += 1
            tc[team]["aerials_won"] += 1
        elif t == "foul":
            c["fouls"] += 1
            tc[team]["fouls"] += 1
            if e.get("victim_id"):
                pc[e["victim_id"]]["fouls_won"] += 1
        elif t == "card":
            if e["card"] == "yellow":
                c["yellows"] += 1
                tc[team]["yellows"] += 1
            else:
                c["reds"] += 1
                tc[team]["reds"] += 1
        elif t == "offside":
            c["offsides"] += 1
            tc[team]["offsides"] += 1
        elif t == "corner":
            tc[team]["corners"] += 1
        elif t == "physical":
            c["distance"] += e["distance_km"]
            c["top_speed"] = max(c["top_speed"], e["top_speed_kmh"])
            c["sprints"] += e["sprints"]

    hg, ag = events[-1]["score"]["home"], events[-1]["score"]["away"]
    goals = {home: hg, away: ag}
    for club in (home, away):
        tc[club]["goals"] = goals[club]
    row = MatchRow(m["match_id"], m["league"], m["round"], home, away, hg, ag,
                   {k: dict(v) for k, v in tc.items()},
                   [(e["minute"] + 1, e["team"]) for e in events if e["type"] == "goal"])

    for pid, (on, off) in mins.items():
        played = max(0, off - on)
        if pid not in players or played <= 0:
            continue
        P = players[pid]
        c = pc[pid]
        club = P["meta"]["club"]
        c["goals_prevented"] = c["xgot_faced"] - c["conceded"]
        conceded_team = goals[opp[club]]
        if roles.get(pid) == "GK" and conceded_team == 0 and played >= 60:
            c["clean_sheets"] = 1
        if roles.get(pid) != "GK":
            c["conceded"] = 0  # only keepers carry goals conceded
        c["finishing"] = c["goals"] - c["xg"]
        P["apps"] += 1
        P["starts"] += on == 0
        P["minutes"] += played
        for k, v in c.items():
            if k in ("top_speed", "shot_speed_max"):
                P["c"][k] = max(P["c"][k], v)
            else:
                P["c"][k] += v
        if played >= 30:
            r, factors = match_rating(c, roles.get(pid), goals[club], conceded_team)
            P["ratings"].append({"match_id": m["match_id"], "round": m["round"], "rating": r,
                                 "minutes": played, "factors": factors})
            P["c"]["rating_sum"] += r
            P["c"]["rated_apps"] += 1
    return row


def match_rating(c: dict, role: str | None, gf: int, ga: int) -> tuple[float, dict]:
    f = {}
    for k, w in RATING_FACTORS.items():
        v = c.get(k, 0) * w
        if v:
            lab = RATING_FACTOR_LABELS[k]
            f[lab] = f.get(lab, 0) + v
    if c.get("passes", 0) >= 10:
        f["Passing accuracy"] = (c["passes_ok"] / c["passes"] - 0.8) * 2.5
    f["Team result"] = 0.3 if gf > ga else -0.2 if gf < ga else 0.05
    if role in ("GK", "CB", "FB", "DM"):
        f["Goals conceded"] = -0.18 * ga + (0.3 if ga == 0 else 0)
    r = max(3.0, min(10.0, 6.0 + sum(f.values())))
    return round(r, 2), {k: round(v, 2) for k, v in f.items() if abs(v) >= 0.01}
