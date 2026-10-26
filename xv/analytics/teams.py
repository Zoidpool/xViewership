"""Team season stats, league table, ranks, and league-level observations."""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

from .model import outcome_probs
from .zones import add_team, team_zone_summary

TEAM_STATS = {
    # key: (label, higher_is_better)
    "pts": ("Points", True), "ppg": ("Points per game", True), "gf": ("Goals for", True),
    "ga": ("Goals against", False), "gd": ("Goal difference", True),
    "xgf": ("xG for per match", True), "xga": ("xG against per match", False),
    "xgd": ("xG difference per match", True), "xpts": ("Expected points", True),
    "shots_for": ("Shots per match", True), "shots_against": ("Shots against per match", False),
    "sot_for": ("Shots on target per match", True), "possession": ("Possession %", True),
    "pass_pct": ("Pass accuracy %", True), "field_tilt": ("Field tilt %", True),
    "ppda": ("Passes allowed per defensive action (PPDA)", False),
    "corners_for": ("Corners per match", True), "crosses": ("Crosses per match", True),
    "aerials_won": ("Aerials won per match", True), "fouls": ("Fouls per match", False),
    "yellows": ("Yellow cards per match", False), "clean_sheets": ("Clean sheets", True),
    "btts_pct": ("Both teams scored %", True), "over25_pct": ("Over 2.5 goals %", True),
    "first_goal_pct": ("Scored first %", True), "points_from_behind": ("Points won from behind", True),
}


def _xpts(xg_for: float, xg_against: float) -> float:
    p = outcome_probs(xg_for, xg_against, rho=0.0)
    return 3 * p["home"] + p["draw"]


def team_tables(agg: dict) -> dict:
    world = agg["world"]
    clubs = {c["code"]: {**{k: v for k, v in c.items() if k != "players"}} for lg in world["leagues"]
             for c in lg["clubs"]}
    rows = defaultdict(lambda: defaultdict(float))
    form = defaultdict(list)
    per_match = defaultdict(list)
    zacc: dict[str, dict] = defaultdict(dict)
    lacc: dict[str, dict] = defaultdict(dict)
    lmp: dict[str, int] = defaultdict(int)
    for m in sorted(agg["matches"], key=lambda m: m.round):
        for side, opp in ((m.home, m.away), (m.away, m.home)):
            if m.zones:
                add_team(zacc[side], m.zones[side])
                add_team(lacc[m.league], m.zones[side])
                lmp[m.league] += 1
            t, o = m.team[side], m.team[opp]
            gf, ga = t["goals"], o["goals"]
            r = rows[side]
            r["mp"] += 1
            res = "W" if gf > ga else "D" if gf == ga else "L"
            r[res] += 1
            r["pts"] += {"W": 3, "D": 1, "L": 0}[res]
            r["gf"] += gf
            r["ga"] += ga
            r["xgf_sum"] += t.get("xg", 0)
            r["xga_sum"] += o.get("xg", 0)
            r["xpts"] += _xpts(t.get("xg", 0), o.get("xg", 0))
            r["shots_for_sum"] += t.get("shots", 0)
            r["shots_against_sum"] += o.get("shots", 0)
            r["sot_for_sum"] += t.get("sot", 0)
            r["passes"] += t.get("passes", 0)
            r["opp_passes"] += o.get("passes", 0)
            r["passes_ok"] += t.get("passes_ok", 0)
            r["ft"] += t.get("final_third_passes", 0)
            r["opp_ft"] += o.get("final_third_passes", 0)
            r["opp_own60"] += o.get("passes_own60", 0)
            r["def_high"] += t.get("def_actions_high", 0)
            r["corners_sum"] += t.get("corners", 0)
            r["crosses_sum"] += t.get("crosses", 0)
            r["aerials_sum"] += t.get("aerials_won", 0)
            r["fouls_sum"] += t.get("fouls", 0)
            r["yellows_sum"] += t.get("yellows", 0)
            r["clean_sheets"] += ga == 0
            r["btts"] += gf > 0 and ga > 0
            r["over25"] += gf + ga > 2
            first = m.goal_minutes[0][1] if m.goal_minutes else None
            r["scored_first"] += first == side
            if first == opp and res != "L":
                r["points_from_behind"] += 3 if res == "W" else 1
            r["home_pts" if side == m.home else "away_pts"] += {"W": 3, "D": 1, "L": 0}[res]
            r["home_mp" if side == m.home else "away_mp"] += 1
            form[side].append(res)
            per_match[side].append({"round": m.round, "opp": opp, "home": side == m.home,
                                    "gf": gf, "ga": ga, "xgf": round(t.get("xg", 0), 2),
                                    "xga": round(o.get("xg", 0), 2), "res": res})
    out = {}
    for code, r in rows.items():
        mp = r["mp"]
        out[code] = {
            **clubs[code], "mp": int(mp), "w": int(r["W"]), "d": int(r["D"]), "l": int(r["L"]),
            "form": "".join(form[code][-5:]), "matches": per_match[code],
            "values": {
                "pts": int(r["pts"]), "ppg": round(r["pts"] / mp, 2), "gf": int(r["gf"]),
                "ga": int(r["ga"]), "gd": int(r["gf"] - r["ga"]),
                "xgf": round(r["xgf_sum"] / mp, 2), "xga": round(r["xga_sum"] / mp, 2),
                "xgd": round((r["xgf_sum"] - r["xga_sum"]) / mp, 2), "xpts": round(r["xpts"], 1),
                "shots_for": round(r["shots_for_sum"] / mp, 1),
                "shots_against": round(r["shots_against_sum"] / mp, 1),
                "sot_for": round(r["sot_for_sum"] / mp, 1),
                "possession": round(100 * r["passes"] / max(1, r["passes"] + r["opp_passes"]), 1),
                "pass_pct": round(100 * r["passes_ok"] / max(1, r["passes"]), 1),
                "field_tilt": round(100 * r["ft"] / max(1, r["ft"] + r["opp_ft"]), 1),
                "ppda": round(r["opp_own60"] / max(1, r["def_high"]), 1),
                "corners_for": round(r["corners_sum"] / mp, 1), "crosses": round(r["crosses_sum"] / mp, 1),
                "aerials_won": round(r["aerials_sum"] / mp, 1), "fouls": round(r["fouls_sum"] / mp, 1),
                "yellows": round(r["yellows_sum"] / mp, 2), "clean_sheets": int(r["clean_sheets"]),
                "btts_pct": round(100 * r["btts"] / mp), "over25_pct": round(100 * r["over25"] / mp),
                "first_goal_pct": round(100 * r["scored_first"] / mp),
                "points_from_behind": int(r["points_from_behind"]),
            },
            "home_ppg": round(r["home_pts"] / max(1, r["home_mp"]), 2),
            "away_ppg": round(r["away_pts"] / max(1, r["away_mp"]), 2),
            "zones": team_zone_summary(zacc[code], int(mp)) if zacc.get(code) else None,
        }
    # league tables and ranks
    tables = {}
    for lg in world["leagues"]:
        codes = [c["code"] for c in lg["clubs"] if c["code"] in out]
        codes.sort(key=lambda c: (-out[c]["values"]["pts"], -out[c]["values"]["gd"], -out[c]["values"]["gf"]))
        tables[lg["id"]] = codes
        for i, c in enumerate(codes, start=1):
            out[c]["position"] = i
        out_ranks = {}
        for k, (_, hb) in TEAM_STATS.items():
            ordered = sorted(codes, key=lambda c: out[c]["values"][k], reverse=hb)
            for i, c in enumerate(ordered, start=1):
                out[c].setdefault("ranks", {})[k] = i
        out_ranks.clear()
    league_zones = {lid: team_zone_summary(acc, lmp[lid]) for lid, acc in lacc.items() if acc}
    return {"teams": out, "tables": tables, "league_zones": league_zones}


# ---------- league observations ----------
def wilson(k: int, n: int, z: float = 1.645) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(100 * (c - h)), round(100 * (c + h))


OUTCOMES = {
    "home_win": "a home win", "draw": "a draw", "away_win": "an away win",
    "over25": "over 2.5 goals", "under25": "under 2.5 goals", "btts": "both teams to score",
    "late_goal": "a goal after the 80th minute", "red_card": "a red card",
    "comeback": "the team that conceded first avoiding defeat", "clean_sheet": "at least one clean sheet",
}


def league_observations(agg: dict, wf: list[dict]) -> dict:
    world = agg["world"]
    names = {lg["id"]: lg["name"] for lg in world["leagues"]}
    stats = {}
    for lid in names:
        ms = [m for m in agg["matches"] if m.league == lid]
        n = len(ms)
        k = defaultdict(int)
        goals = cards = corners = 0
        for m in ms:
            hg, ag = m.hg, m.ag
            k["home_win"] += hg > ag
            k["draw"] += hg == ag
            k["away_win"] += hg < ag
            k["over25"] += hg + ag > 2
            k["under25"] += hg + ag <= 2
            k["btts"] += hg > 0 and ag > 0
            k["late_goal"] += any(mi > 80 for mi, _ in m.goal_minutes)
            k["red_card"] += (m.team[m.home].get("reds", 0) + m.team[m.away].get("reds", 0)) > 0
            k["clean_sheet"] += hg == 0 or ag == 0
            if m.goal_minutes:
                first = m.goal_minutes[0][1]
                other_goals, first_goals = (ag, hg) if first == m.home else (hg, ag)
                k["comeback"] += other_goals >= first_goals
            goals += hg + ag
            cards += sum(m.team[c].get("yellows", 0) for c in (m.home, m.away))
            corners += sum(m.team[c].get("corners", 0) for c in (m.home, m.away))
        lw = [w for w in wf if w["league"] == lid]
        mk = {o: round(100 * mean(w["market"][o] for w in lw), 1) for o in ("home", "draw", "away", "over25", "btts")} if lw else {}
        ll = {"market": round(mean(-math.log(w["market"][w["result"]]) for w in lw), 4),
              "model": round(mean(-math.log(w["model"][w["result"]]) for w in lw), 4),
              "base": None, "n": len(lw)} if lw else None
        stats[lid] = {
            "name": names[lid], "matches": n,
            "rates": {o: {"k": k[o], "pct": round(100 * k[o] / n, 1), "ci90": wilson(k[o], n)} for o in OUTCOMES},
            "goals_pm": round(goals / n, 2), "yellows_pm": round(cards / n, 2), "corners_pm": round(corners / n, 2),
            "market_expected_pct": {"home_win": mk.get("home"), "draw": mk.get("draw"), "away_win": mk.get("away"),
                                    "over25": mk.get("over25"), "btts": mk.get("btts"),
                                    "under25": round(100 - mk["over25"], 1) if mk else None},
            "log_loss": ll,
        }
    # sentences: which league is most / least likely to see each outcome
    sentences = []
    for o, phrase in OUTCOMES.items():
        ranked = sorted(stats, key=lambda l: -stats[l]["rates"][o]["pct"])
        top, low = ranked[0], ranked[-1]
        t, b = stats[top]["rates"][o], stats[low]["rates"][o]
        gap = round(t["pct"] - b["pct"], 1)
        overlap = t["ci90"][0] <= b["ci90"][1]
        sentences.append({
            "outcome": o, "most": top, "least": low, "gap_pts": gap, "separated": not overlap,
            "text": f"{stats[top]['name']} is the league most likely to see {phrase}: "
                    f"{t['pct']}% of {stats[top]['matches']} matches (90% range {t['ci90'][0]}-{t['ci90'][1]}%), "
                    f"against {b['pct']}% in {stats[low]['name']}."
                    + ("" if not overlap else " The ranges overlap, so treat the order as a lean, not a finding."),
        })
    # where results ran away from what the market expected
    gaps = []
    for lid, s in stats.items():
        for o in ("home_win", "draw", "away_win", "over25", "under25", "btts"):
            exp = s["market_expected_pct"].get(o)
            if exp is None:
                continue
            act = s["rates"][o]["pct"]
            lo, hi = s["rates"][o]["ci90"]
            gaps.append({"league": lid, "outcome": o, "actual": act, "market": exp,
                         "diff": round(act - exp, 1), "outside_range": not (lo <= exp <= hi),
                         "text": f"{s['name']}: {OUTCOMES[o]} happened in {act}% of matches; "
                                 f"the market's prices implied {exp}% on average."})
    gaps.sort(key=lambda g: -abs(g["diff"]))
    return {"leagues": stats, "most_likely": sentences, "market_gaps": gaps[:10]}
