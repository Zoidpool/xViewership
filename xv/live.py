"""The live match: which fixture is featured, and its synthetic event stream."""
from __future__ import annotations

import json
from pathlib import Path

from .generator.engine import simulate_match
from .generator.league import build_world

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BUNDLE = ROOT / "docs" / "data"


def fixtures(bundle: Path = BUNDLE) -> list[dict]:
    return json.loads((bundle / "fixtures.json").read_text(encoding="utf-8"))


def featured_fixture(bundle: Path = BUNDLE, league: str = "meridian", match_id: str | None = None) -> dict:
    """The requested fixture, else the league's closest call between two top-half sides."""
    fx = [f for f in fixtures(bundle) if f["league"] == league]
    if match_id:
        return next(f for f in fixtures(bundle) if f["match_id"] == match_id)
    teams = json.loads((bundle / "teams.json").read_text(encoding="utf-8"))["teams"]
    pos = lambda c: teams.get(c, {}).get("position", 99)
    return min(fx, key=lambda f: (pos(f["home"]) + pos(f["away"]),
                                  abs(f["model"]["home"] - f["model"]["away"])))


def live_events(fixture: dict, seed: int, data_dir: Path = DATA) -> list[dict]:
    world_doc = json.loads((data_dir / "world.json").read_text(encoding="utf-8"))
    world = build_world(world_doc["seed"])
    lw = world[fixture["league"]]
    return simulate_match(lw["clubs"][fixture["home"]], lw["clubs"][fixture["away"]],
                          fixture["match_id"], seed, fixture["round"], lw["league"])


def tracking_for(fixture: dict, events: list[dict], data_dir: Path = DATA) -> tuple[dict, list]:
    """Synthetic positions (1 per second) and compact on-ball actions for the live pitch."""
    from .generator.tracking import actions, build_tracking
    world_doc = json.loads((data_dir / "world.json").read_text(encoding="utf-8"))
    clubs = build_world(world_doc["seed"])[fixture["league"]]["clubs"]
    meta = {p.id: p.to_dict() for code in (fixture["home"], fixture["away"]) for p in clubs[code].players}
    return build_tracking(events, meta), actions(events, fixture["home"])


def dramatic_seed(fixture: dict, tries: int = 300, data_dir: Path = DATA) -> int:
    """A seed whose match has goals, a lead change and a late twist (for demos)."""
    best, best_score = 1, -1
    for seed in range(1, tries + 1):
        ev = live_events(fixture, seed, data_dir)
        goals = [e for e in ev if e["type"] == "goal"]
        leaders, lead_changes, late = [], 0, 0
        for g in goals:
            s = g["score"]
            lead = "home" if s["home"] > s["away"] else "away" if s["away"] > s["home"] else None
            if leaders and lead and leaders[-1] and lead != leaders[-1]:
                lead_changes += 1
            leaders.append(lead)
            late += g["minute"] >= 75
        reds = sum(1 for e in ev if e["type"] == "card" and e["card"] != "yellow")
        score = min(len(goals), 5) + 3 * min(lead_changes, 1) + 2 * min(late, 1) + min(reds, 1) \
            + (2 if leaders and leaders[0] is not None and leaders[-1] != leaders[0] else 0)
        if score > best_score:
            best, best_score = seed, score
    return best
