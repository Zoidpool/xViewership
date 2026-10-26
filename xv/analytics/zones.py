"""Pitch zones: thirds, attacking lanes, half-spaces, a grid, and what happens in each.

All team-level numbers are in the team's own attacking frame (x 0 = own goal,
100 = opponent's goal; y 0 = the team's left touchline when attacking).

  thirds       defensive / middle / attacking (x split at 33.3 and 66.7)
  lanes (3)    left / centre / right (y split at 33.3 and 66.7)
  lanes (5)    left wing / left half-space / centre / right half-space / right wing,
               split at the penalty-box and six-yard-box edges (13.85, 24.84, 43.16, 54.15 m of 68)
  grid         12 x 8 squares for occupancy and possession territory
  bands        6 vertical bands for where passes are played (Football Manager-style strips)
  assist areas 13 zones: six-yard box, box centre/left/right, edge of the box, half-spaces, wings,
               middle third left/centre/right, own third
"""
from __future__ import annotations

from collections import defaultdict

GRID_X, GRID_Y = 12, 8
LANE5_EDGES = [100 * 13.85 / 68, 100 * 24.84 / 68, 100 * 43.16 / 68, 100 * 54.15 / 68]
LANE5_NAMES = ["Left wing", "Left half-space", "Centre", "Right half-space", "Right wing"]
LANE3_NAMES = ["Left", "Centre", "Right"]
THIRD_NAMES = ["Defensive third", "Middle third", "Attacking third"]
# assist zones (team frame): name, x0, x1, y0, y1; the first match wins (six-yard box before the box)
ASSIST_ZONES = [
    ("Six-yard box", 94.8, 100, 36.5, 63.5), ("Box, centre", 84.3, 100, 36.5, 63.5),
    ("Box, left", 84.3, 100, 20.4, 36.5), ("Box, right", 84.3, 100, 63.5, 79.6),
    ("Edge of the box", 66.7, 84.3, 36.5, 63.5), ("Left half-space", 66.7, 84.3, 20.4, 36.5),
    ("Right half-space", 66.7, 84.3, 63.5, 79.6), ("Left wing", 66.7, 100, 0, 20.4),
    ("Right wing", 66.7, 100, 79.6, 100), ("Middle third, left", 33.3, 66.7, 0, 33.3),
    ("Middle third, centre", 33.3, 66.7, 33.3, 66.7), ("Middle third, right", 33.3, 66.7, 66.7, 100),
    ("Own third", 0, 33.3, 0, 100),
]
ASSIST_AREAS = [z[0] for z in ASSIST_ZONES]
ASSIST_TYPES = ["Short pass", "Cross", "Long ball", "Corner", "Free kick", "Penalty", "Individual"]


def third(x: float) -> int:
    return 0 if x < 100 / 3 else 1 if x < 200 / 3 else 2


def lane3(y: float) -> int:
    return 0 if y < 100 / 3 else 1 if y < 200 / 3 else 2


def lane5(y: float) -> int:
    for i, e in enumerate(LANE5_EDGES):
        if y < e:
            return i
    return 4


def cell(x: float, y: float) -> int:
    cx = min(GRID_X - 1, max(0, int(x / 100 * GRID_X)))
    cy = min(GRID_Y - 1, max(0, int(y / 100 * GRID_Y)))
    return cy * GRID_X + cx


def band(x: float) -> int:
    return min(5, max(0, int(x / 100 * 6)))


def assist_area(x: float, y: float) -> int:
    for i, (_, x0, x1, y0, y1) in enumerate(ASSIST_ZONES):
        if x0 <= x <= x1 and y0 <= y <= y1:
            return i
    return len(ASSIST_ZONES) - 1


def empty_team() -> dict:
    return {"pass_bands": [0] * 6, "entries3": [0] * 3, "entries5": [0] * 5,
            "shots3": [0] * 3, "shots_box": 0, "xg_lanes5": [0.0] * 5,
            "assist_areas": [0] * len(ASSIST_ZONES), "assist_types": [0] * 7,
            "conceded_assist_areas": [0] * len(ASSIST_ZONES), "conceded_assist_types": [0] * 7,
            "poss_thirds": [0.0] * 3, "territory": [0.0] * (GRID_X * GRID_Y), "poss_seconds": 0.0}


def match_zones(events: list[dict], tracking: dict | None) -> tuple[dict, dict]:
    """Returns ({club: team zone counts}, {player id: occupancy grid seconds (team frame)})."""
    start = events[0]
    home, away = start["home"], start["away"]
    opp = {home: away, away: home}
    tz = {home: empty_team(), away: empty_team()}
    last_pass: dict[str, dict] = {}
    for e in events:
        ty, team = e["type"], e.get("team")
        if ty == "pass" and team:
            z = tz[team]
            z["pass_bands"][band(e.get("x", 50))] += 1
            if e["outcome"] == "complete":
                last_pass[e["player_id"]] = e
                if e.get("end_x", 0) > 200 / 3 >= e.get("x", 0):
                    ey = e.get("end_y", e.get("y", 50))
                    z["entries3"][lane3(ey)] += 1
                    z["entries5"][lane5(ey)] += 1
        elif ty == "shot" and team:
            z = tz[team]
            y = e.get("y", 50)
            z["shots3"][lane3(y)] += 1
            z["shots_box"] += e.get("x", 0) > 83
            z["xg_lanes5"][lane5(y)] += e["xg"]
            if e["outcome"] == "goal":
                sit = e.get("situation")
                kp = last_pass.get(e.get("key_pass_id") or "")
                if sit == "penalty":
                    typ, area = 5, 1
                elif sit == "free_kick":
                    typ, area = 4, assist_area(e.get("x", 80), y)
                elif sit == "corner":
                    typ, area = 3, (7 if e["seq"] % 2 else 8)  # taken from the left or right wing
                elif kp:
                    typ = 1 if kp.get("cross") else 2 if kp.get("long") else 0
                    area = assist_area(kp.get("x", 50), kp.get("y", 50))
                else:
                    typ, area = 6, assist_area(e.get("x", 80), y)
                z["assist_areas"][area] += 1
                z["assist_types"][typ] += 1
                tz[opp[team]]["conceded_assist_areas"][area] += 1
                tz[opp[team]]["conceded_assist_types"][typ] += 1

    occ: dict[str, list[float]] = defaultdict(lambda: [0.0] * (GRID_X * GRID_Y))
    if tracking:
        dt = 1.0 / tracking["hz"]
        meta = tracking["players"]
        for f in tracking["frames"]:
            bx, by, side = f[2] / 10, f[3] / 10, f[4]
            owner = home if side == 0 else away
            tbx, tby = (bx, by) if owner == home else (100 - bx, 100 - by)
            z = tz[owner]
            z["poss_thirds"][third(tbx)] += dt
            z["territory"][cell(tbx, tby)] += dt
            z["poss_seconds"] += dt
            pos = f[5]
            for i, p in enumerate(meta):
                x = pos[2 * i]
                if x < 0:
                    continue
                y = pos[2 * i + 1]
                x, y = x / 10, y / 10
                if p["club"] != home:
                    x, y = 100 - x, 100 - y
                occ[p["id"]][cell(x, y)] += dt
    return tz, dict(occ)


def add_team(acc: dict, z: dict) -> None:
    for k, v in z.items():
        if isinstance(v, list):
            cur = acc.setdefault(k, [0] * len(v))
            for i, x in enumerate(v):
                cur[i] += x
        else:
            acc[k] = acc.get(k, 0) + v


def shares(v: list[float]) -> list[float]:
    s = sum(v)
    return [round(100 * x / s, 1) if s else 0.0 for x in v]


def team_zone_summary(acc: dict, mp: int) -> dict:
    """Season zone view of a team: shares (%) and per-match counts."""
    return {
        "pass_bands_pct": shares(acc["pass_bands"]),
        "entries3_pct": shares(acc["entries3"]), "entries5_pct": shares(acc["entries5"]),
        "entries_pm": round(sum(acc["entries3"]) / mp, 1),
        "shots3_pct": shares(acc["shots3"]), "xg_lanes5": [round(x, 2) for x in acc["xg_lanes5"]],
        "assist_areas": acc["assist_areas"], "assist_types": acc["assist_types"],
        "conceded_assist_areas": acc["conceded_assist_areas"], "conceded_assist_types": acc["conceded_assist_types"],
        "poss_thirds_pct": shares(acc["poss_thirds"]),
        "territory_pct": [round(x, 2) for x in shares(acc["territory"])],
    }
