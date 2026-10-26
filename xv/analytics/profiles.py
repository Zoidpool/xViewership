"""Player profiles: per-90 values, percentiles, league averages, archetypes, rankings.

Fair comparison rules:
  - players are compared within their role (GK, CB, FB, DM, CM, AM, W, ST), so a
    full-back is judged against full-backs, not centre-backs;
  - two scopes: the player's league, and all four leagues;
  - the pool is players above the minutes bar: 60% of the minutes their team
    could have played so far (it grows with the season, never a fixed number);
  - percentages need a minimum number of attempts (CATALOG), else they are blank.
Archetypes score each style as a weighted mean of the player's percentiles
(all-league scope, same role); the hidden design style from the generator is
kept only to measure how often the detector recovers it.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean

from .stats import CATALOG, RATING_FACTOR_LABELS

ROLE_NAMES = {"GK": "Goalkeeper", "CB": "Centre-back", "FB": "Full-back", "DM": "Defensive midfielder",
              "CM": "Central midfielder", "AM": "Attacking midfielder", "W": "Winger", "ST": "Striker"}
ROLE_ORDER = ["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"]
MINUTES_SHARE = 0.6
TARGET_RATING = 6.8

# default radar / key stats per role
ROLE_STATS = {
    "GK": ["saves", "save_pct", "goals_prevented", "conceded", "pass_pct", "long_ok", "long_pct", "clean_sheets"],
    "CB": ["aerials_won", "aerial_pct", "tackles", "interceptions", "clearances", "blocks", "pass_pct", "progressive", "long_ok"],
    "FB": ["tackles", "interceptions", "duel_pct", "crosses_ok", "key_passes", "xa", "dribbles_ok", "final_third", "progressive"],
    "DM": ["interceptions", "tackles", "blocks", "duel_pct", "passes", "pass_pct", "long_ok", "progressive", "final_third"],
    "CM": ["passes", "pass_pct", "final_third", "progressive", "key_passes", "tackles", "interceptions", "box_touches", "distance"],
    "AM": ["key_passes", "xa", "big_chances_created", "final_third", "dribbles_ok", "npxg", "shots", "box_touches"],
    "W": ["dribbles_ok", "dribble_pct", "crosses_ok", "key_passes", "xa", "box_touches", "npxg", "shots", "top_speed"],
    "ST": ["goals", "npxg", "xg_per_shot", "sot", "box_touches", "big_chances_missed", "aerials_won", "headers"],
}

# archetype: (id, name, description, weights over stat keys; negative = less is more)
ARCHETYPES = {
    "GK": [("shot_stopper", "Shot-stopper", "Wins points with saves: high save rate and goals prevented.",
            {"saves": 1, "save_pct": 1.2, "goals_prevented": 1.5}),
           ("sweeper", "Sweeper-keeper", "Plays with the feet: lots of accurate passing and long distribution.",
            {"passes": 1, "pass_pct": 1.2, "long_ok": 1, "long_pct": 0.8})],
    "CB": [("ball_playing", "Ball-playing defender", "Starts attacks: passes, progressive passes and long balls.",
            {"passes": 1, "pass_pct": 0.8, "progressive": 1.2, "long_ok": 1, "final_third": 1}),
           ("stopper", "Stopper", "Steps out and wins it: tackles, interceptions, and a few fouls.",
            {"tackles": 1.4, "interceptions": 0.8, "fouls": 0.6, "duels_won": 0.6}),
           ("aerial", "Aerial defender", "Owns the box: headers won, clearances and blocks.",
            {"aerials_won": 1.4, "aerial_pct": 1.2, "clearances": 1, "blocks": 0.5})],
    "FB": [("attacking", "Attacking full-back", "A wide attacker from defence: crosses, dribbles, chances.",
            {"crosses_ok": 1.2, "dribbles_ok": 1, "key_passes": 1, "xa": 0.8, "box_touches": 0.6}),
           ("defensive", "Defensive full-back", "Defender first: tackles, interceptions, clearances.",
            {"tackles": 1.2, "interceptions": 1.2, "clearances": 0.6, "crosses_ok": -0.6}),
           ("inverted", "Inverted full-back", "Steps into midfield to pass: volume, accuracy, progression.",
            {"passes": 1.2, "pass_pct": 1, "progressive": 1, "crosses": -0.6})],
    "DM": [("anchor", "Anchor", "Screens the defence: reads play, intercepts, keeps it simple.",
            {"interceptions": 1.4, "blocks": 0.8, "pass_pct": 0.8, "shots": -0.6, "fouls": -0.4}),
           ("destroyer", "Ball-winner", "Wins the ball back in volume, and fouls when needed.",
            {"tackles": 1.5, "duels_won": 0.8, "fouls": 1}),
           ("regista", "Deep-lying playmaker", "Dictates from deep: passing volume, long balls, progression.",
            {"passes": 1.2, "long_ok": 1, "progressive": 1.2, "final_third": 1})],
    "CM": [("box_to_box", "Box-to-box", "Covers ground at both ends: tackles, box arrivals, shots, distance.",
            {"distance": 1, "tackles": 0.8, "box_touches": 0.8, "shots": 0.8}),
           ("playmaker", "Playmaker", "The chance-maker: key passes, expected assists, final-third passes.",
            {"key_passes": 1.4, "xa": 1.2, "final_third": 1, "big_chances_created": 0.8}),
           ("carrier", "Ball-carrier", "Moves it by dribbling: take-ons and fouls drawn.",
            {"dribbles_ok": 1.6, "dribble_pct": 0.6, "fouls_won": 0.8})],
    "AM": [("playmaker", "Creative No.10", "Makes chances: key passes, xA, big chances created.",
            {"key_passes": 1.4, "xa": 1.2, "big_chances_created": 1}),
           ("shadow_striker", "Shadow striker", "Arrives to score: shots, xG and box touches.",
            {"npxg": 1.3, "shots": 1, "box_touches": 1, "goals": 0.6})],
    "W": [("touchline", "Touchline winger", "Stays wide and delivers: crosses and chances.",
           {"crosses_ok": 1.5, "crosses": 0.8, "key_passes": 0.8, "npxg": -0.5}),
          ("inside_forward", "Inside forward", "Cuts in to shoot: dribbles, shots, xG.",
           {"npxg": 1.2, "shots": 1, "dribbles_ok": 1, "crosses": -0.6})],
    "ST": [("poacher", "Poacher", "Lives in the box: chances, shots on target, little build-up.",
            {"npxg": 1.4, "box_touches": 1, "sot": 0.8, "passes": -0.6}),
           ("target", "Target forward", "Physical focal point: headers won and headed shots.",
            {"aerials_won": 1.6, "headers": 1, "aerial_pct": 0.8}),
           ("complete", "Complete forward", "Scores and creates: xG plus key passes and dribbles.",
            {"npxg": 0.8, "key_passes": 1, "dribbles_ok": 0.8, "xa": 0.8}),
           ("presser", "Pressing forward", "Works without the ball: tackles, interceptions, distance.",
            {"tackles": 1.4, "interceptions": 1, "distance": 0.8})],
}


def _occupancy(grid: list[float] | None) -> dict:
    """Season occupancy: % of time in each 12 x 8 square (team attacking frame) and the average spot."""
    if not grid or not sum(grid):
        return {"grid": None, "avg_pos": None}
    tot = sum(grid)
    gx, gy = 12, 8
    ax = sum(v * ((i % gx) + 0.5) / gx * 100 for i, v in enumerate(grid)) / tot
    ay = sum(v * ((i // gx) + 0.5) / gy * 100 for i, v in enumerate(grid)) / tot
    return {"grid": [round(100 * v / tot, 1) for v in grid], "avg_pos": [round(ax, 1), round(ay, 1)]}


def values(P: dict) -> dict[str, float | None]:
    c, mins = P["c"], P["minutes"]
    out: dict[str, float | None] = {}
    for k, (_, _, kind, _, extra) in CATALOG.items():
        if kind == "count":
            out[k] = round(c.get(k, 0) / mins * 90, 3) if mins else None
        elif kind == "pct":
            num, den, mn = extra
            d = c.get(den, 0)
            if d >= mn:
                ratio = c.get(num, 0) / d
                out[k] = round(ratio if k == "xg_per_shot" else 100 * ratio, 3)
            else:
                out[k] = None
        elif kind == "avg":
            s, n = extra
            out[k] = round(c.get(s, 0) / c[n], 3) if c.get(n) else None
        elif kind == "max":
            out[k] = c.get(k) or None
        else:
            out[k] = c.get(k, 0)
    return out


def percentile(v: float | None, pool: list[float], higher_better: bool) -> int | None:
    if v is None or len(pool) < 5:
        return None
    # inclusive percentile rank: the best in the group is 100, the worst 0; ties share the middle
    below = sum(1 for p in pool if p < v)
    equal = sum(1 for p in pool if p == v)
    if equal:  # the player is in the pool: rank against the others
        pc = 100 * (below + 0.5 * (equal - 1)) / (len(pool) - 1)
    else:      # outside the pool (below the minutes bar): place among the pool
        pc = 100 * below / len(pool)
    return round(pc if higher_better else 100 - pc)


def build_profiles(agg: dict) -> dict:
    world = agg["world"]
    rounds_played = defaultdict(int)
    for m in agg["matches"]:
        rounds_played[m.league] = max(rounds_played[m.league], m.round)

    # put every role on the same scale: shift ratings so each role averages TARGET_RATING
    by_role = defaultdict(list)
    for P in agg["players"].values():
        by_role[P["meta"]["role"]] += [m["rating"] for m in P["ratings"]]
    shift = {role: round(TARGET_RATING - mean(rs), 2) for role, rs in by_role.items() if rs}
    for P in agg["players"].values():
        s = shift.get(P["meta"]["role"], 0)
        for m in P["ratings"]:
            m["rating"] = round(max(3.0, min(10.0, m["rating"] + s)), 2)
            m["factors"]["Role adjustment"] = s
        P["c"]["rating_sum"] = sum(m["rating"] for m in P["ratings"])

    rows = []
    for pid, P in agg["players"].items():
        meta = P["meta"]
        bar = round(rounds_played[meta["league"]] * 90 * MINUTES_SHARE)
        v = values(P)
        rows.append({
            "id": pid, "name": meta["name"], "club": meta["club"], "league": meta["league"],
            "role": meta["role"], "age": meta["age"], "height_cm": meta["height_cm"],
            "foot": meta["foot"], "shirt": meta["shirt"], "design_style": meta["style"],
            "apps": P["apps"], "starts": P["starts"], "minutes": P["minutes"],
            "minutes_bar": bar, "eligible": P["minutes"] >= bar, "values": v,
            "totals": {k: round(P["c"].get(k, 0), 2) for k in
                       ("goals", "assists", "xg", "xa", "shots", "key_passes", "tackles",
                        "interceptions", "saves", "yellows", "reds", "clean_sheets")},
            "ratings": P["ratings"],
            **_occupancy(P.get("grid")),
        })

    # pools: (scope, role) -> stat -> values of eligible players
    pools: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r["eligible"]:
            continue
        for k, v in r["values"].items():
            if v is not None:
                pools[(r["league"], r["role"])][k].append(v)
                pools[("all", r["role"])][k].append(v)

    averages = {f"{scope}|{role}": {k: round(mean(vs), 3) for k, vs in stats.items() if vs}
                for (scope, role), stats in pools.items()}
    pool_sizes = {f"{scope}|{role}": max((len(v) for v in stats.values()), default=0)
                  for (scope, role), stats in pools.items()}

    for r in rows:
        r["pct"] = {}
        r["pct_all"] = {}
        for k, v in r["values"].items():
            hb = CATALOG[k][3]
            r["pct"][k] = percentile(v, pools[(r["league"], r["role"])].get(k, []), hb)
            r["pct_all"][k] = percentile(v, pools[("all", r["role"])].get(k, []), hb)
        scores = []
        for aid, name, desc, w in ARCHETYPES[r["role"]]:
            tot = wsum = 0.0
            for k, wt in w.items():
                p = r["pct_all"].get(k)
                if p is None:
                    continue
                tot += abs(wt) * (p if wt > 0 else 100 - p)
                wsum += abs(wt)
            if wsum:
                scores.append({"id": aid, "name": name, "desc": desc, "score": round(tot / wsum)})
        scores.sort(key=lambda s: -s["score"])
        r["archetypes"] = scores
        top = scores[0] if scores else None
        clear = top and (len(scores) == 1 or top["score"] - scores[1]["score"] >= 6)
        r["archetype"] = {**top, "clear": bool(clear)} if top else None
        # ranking factors: average contribution per rated match
        facs: dict[str, list[float]] = defaultdict(list)
        for m in r["ratings"]:
            for f, val in m["factors"].items():
                facs[f].append(val)
        n = max(1, len(r["ratings"]))
        r["rating_factors"] = sorted(({"factor": f, "per_match": round(sum(vs) / n, 3)}
                                      for f, vs in facs.items()), key=lambda d: -abs(d["per_match"]))

    # rankings by rating within league+role and all+role (eligible only)
    for scope in ("league", "all"):
        groups = defaultdict(list)
        for r in rows:
            if r["eligible"] and r["values"].get("rating") is not None:
                groups[(r["league"] if scope == "league" else "all", r["role"])].append(r)
        for grp in groups.values():
            grp.sort(key=lambda r: -r["values"]["rating"])
            for i, r in enumerate(grp, start=1):
                r[f"rank_{scope}"] = {"rank": i, "of": len(grp)}

    # how often the archetype detector recovers the hidden design style
    elig = [r for r in rows if r["eligible"] and r["archetype"]]
    hits = sum(r["archetype"]["id"] == r["design_style"] for r in elig)
    by_role = {}
    for role in ROLE_ORDER:
        rr = [r for r in elig if r["role"] == role]
        if rr:
            by_role[role] = {"n": len(rr), "hit": sum(r["archetype"]["id"] == r["design_style"] for r in rr),
                             "chance": round(100 / len(ARCHETYPES[role]))}
    return {"players": rows, "averages": averages, "pool_sizes": pool_sizes, "rating_shift": shift,
            "rounds_played": dict(rounds_played),
            "archetype_check": {"n": len(elig), "hit": hits,
                                "pct": round(100 * hits / len(elig)) if elig else None,
                                "by_role": by_role}}
