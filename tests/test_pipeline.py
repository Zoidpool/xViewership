import asyncio
import json
from pathlib import Path

import pytest

from xv.agents.insights import Insight
from xv.agents.narrator import PERSONAS, Narrator, check_line, grounding_errors, relevant
from xv.analytics.model import LiveModel, devig_power, outcome_probs
from xv.analytics.profiles import percentile
from xv.build import build
from xv.generator.engine import shot_xg, simulate_match
from xv.generator.league import SQUAD, build_world, round_robin
from xv.generator.season import build_season, price
from xv.generator.validate import TARGETS, run
from xv.live import featured_fixture, live_events
from xv.workflow import MatchPipeline


@pytest.fixture(scope="module")
def world_dirs(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    build_season(data, seed=11)
    bundle = tmp_path_factory.mktemp("bundle")
    build(data, bundle)
    return data, bundle


# ---------- generator ----------
def test_world_is_deterministic_with_four_leagues_and_full_squads():
    a, b = build_world(5), build_world(5)
    assert list(a) == ["meridian", "calder", "northmarch", "isles"]
    pa = [p.name for c in a["meridian"]["clubs"].values() for p in c.players]
    assert pa == [p.name for c in b["meridian"]["clubs"].values() for p in c.players]
    for lw in a.values():
        for c in lw["clubs"].values():
            assert len(c.players) == sum(SQUAD.values())
            assert [p.role for p in c.starting_xi()] == ["GK", "FB", "CB", "CB", "FB", "DM", "CM", "AM", "W", "ST", "W"]


def test_round_robin_each_pair_home_and_away():
    rounds = round_robin([f"T{i}" for i in range(10)], 1)
    pairs = [p for r in rounds for p in r]
    assert len(rounds) == 18 and len(pairs) == 90 and len(set(pairs)) == 90


def test_xg_is_higher_close_and_central():
    assert shot_xg(94, 50) > shot_xg(80, 50) > shot_xg(80, 15)
    assert shot_xg(94, 50, header=True) < shot_xg(94, 50)


def test_match_events_are_ordered_and_score_matches_goals():
    lw = build_world()["meridian"]
    codes = list(lw["clubs"])
    ev = simulate_match(lw["clubs"][codes[0]], lw["clubs"][codes[1]], "T1", 3, league=lw["league"])
    assert [e["seq"] for e in ev] == list(range(len(ev)))
    assert len([e for e in ev if e["type"] == "goal"]) == sum(ev[-1]["score"].values())
    types = {e["type"] for e in ev}
    assert {"pass", "shot", "dribble", "aerial", "clearance", "physical"} <= types


def test_season_averages_in_realistic_ranges():
    avg = run(60, seed=3)["all"]
    out = [k for k, (lo, hi) in TARGETS.items() if not lo * 0.9 <= avg[k] <= hi * 1.1]
    assert not out, {k: avg[k] for k in out}


def test_tracking_has_22_players_on_the_pitch_and_moves_at_human_speed():
    from xv.generator.tracking import build_tracking
    lw = build_world()["meridian"]
    codes = list(lw["clubs"])
    ev = simulate_match(lw["clubs"][codes[0]], lw["clubs"][codes[1]], "T2", 5, league=lw["league"])
    meta = {p.id: p.to_dict() for c in codes[:2] for p in lw["clubs"][c].players}
    tr = build_tracking(ev, meta)
    widths = {len(f[5]) for f in tr["frames"]}
    assert widths == {2 * len(tr["players"])}  # fixed width, subs included
    first = tr["frames"][0][5]
    assert sum(1 for i in range(0, len(first), 2) if first[i] >= 0) == 22
    assert all(0 <= v <= 1000 for f in tr["frames"] for v in f[5] if v >= 0)
    # the home centre-backs sit deeper (on average) than the home strikers
    idx = {p["id"]: i for i, p in enumerate(tr["players"])}
    def avg_x(role):
        xs = [f[5][2 * idx[p["id"]]] for f in tr["frames"] for p in tr["players"]
              if p["club"] == tr["home"] and p["role"] == role and f[5][2 * idx[p["id"]]] >= 0]
        return sum(xs) / len(xs)
    assert avg_x("CB") < avg_x("CM") < avg_x("ST")


def test_zone_boundaries():
    from xv.analytics.zones import assist_area, cell, lane3, lane5, third
    assert [third(10), third(50), third(90)] == [0, 1, 2]
    assert [lane3(5), lane3(50), lane3(95)] == [0, 1, 2]
    assert [lane5(5), lane5(30), lane5(50), lane5(70), lane5(95)] == [0, 1, 2, 3, 4]
    assert cell(0, 0) == 0 and cell(99.9, 99.9) == 95
    assert assist_area(97, 50) == 0 and assist_area(90, 50) == 1 and assist_area(90, 25) == 2
    assert assist_area(75, 50) == 4 and assist_area(80, 10) == 7 and assist_area(30, 50) == 12


# ---------- analytics ----------
def test_percentiles_respect_direction():
    pool = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(10, pool, True) > percentile(2, pool, True)
    assert percentile(10, pool, False) < percentile(2, pool, False)
    assert percentile(5, [1, 2], True) is None  # pool too small


def test_bundle_has_profiles_archetypes_and_observations(world_dirs):
    _, bundle = world_dirs
    players = json.loads((bundle / "players.json").read_text(encoding="utf-8"))
    elig = [p for p in players if p["eligible"]]
    assert elig and all(p["archetype"] for p in elig)
    assert all(p["minutes"] >= p["minutes_bar"] for p in elig)
    cbs = [p for p in elig if p["role"] == "CB"]
    assert any(p["pct"]["aerials_won"] is not None for p in cbs)
    ins = json.loads((bundle / "insights.json").read_text(encoding="utf-8"))
    assert len(ins["most_likely"]) >= 8 and ins["evaluation"]["all"]["n"] > 100


def test_power_devig_recovers_true_probabilities():
    true = {"home": 0.5, "draw": 0.27, "away": 0.23, "over25": 0.5, "btts": 0.5}
    p = devig_power(price(true)["1x2"])
    assert all(abs(a - b) < 0.01 for a, b in zip(p, [0.5, 0.27, 0.23]))


def test_live_model_moves_the_right_way():
    m = LiveModel(1.5, 1.1, "H", "A")
    base = m.update(30, {"H": 0, "A": 0}, {"H": 0, "A": 0}, {"H": 0.4, "A": 0.3})
    goal = m.update(31, {"H": 1, "A": 0}, {"H": 0, "A": 0}, {"H": 0.8, "A": 0.3})
    red = m.update(32, {"H": 1, "A": 0}, {"H": 1, "A": 0}, {"H": 0.8, "A": 0.3})
    late = m.update(88, {"H": 1, "A": 0}, {"H": 1, "A": 0}, {"H": 1.0, "A": 0.6})
    assert goal["home"] > base["home"] + 0.15
    assert red["home"] < goal["home"]
    assert late["home"] > red["home"]  # the clock protects a lead
    end = m.update(94, {"H": 1, "A": 0}, {"H": 1, "A": 0}, {"H": 1, "A": 0.6}, finished=True)
    assert end["home"] == 1.0
    assert abs(sum(outcome_probs(1.3, 1.1)[k] for k in ("home", "draw", "away")) - 1) < 1e-3


# ---------- live pipeline ----------
def test_workflow_produces_explained_insights_and_probabilities(world_dirs):
    data, bundle = world_dirs
    fx = featured_fixture(bundle)
    pipe = MatchPipeline(data, fx, bundle)

    async def go():
        found, probs = [], []
        for ev in live_events(fx, 4, data):
            out = await pipe.push(ev)
            found.extend(out.insights)
            if out.snapshot and out.snapshot.get("probs"):
                probs.append(out.snapshot["probs"])
        return found, probs

    found, probs = asyncio.run(go())
    kinds = {i.kind for i in found}
    assert {"preview", "half_time", "full_time"} <= kinds
    assert all(i.why for i in found), "every insight must say why"
    assert probs and all(abs(p["home"] + p["draw"] + p["away"] - 1) < 0.01 for p in probs)
    asyncio.run(pipe.push({"match_id": fx["match_id"], "seq": 0, "period": 1, "t": 0,
                           "minute": 0, "type": "pass"}))
    assert pipe.ingest.dropped == 1


# ---------- narration guardrails ----------
def _ins(**facts):
    return Insight("x", "m", 1, 10, "11'", "goal", "PAL", 0.8, "GOAL", facts,
                   [{"code": "c", "text": "a 0.42 xG chance"}])


def test_grounding_rejects_invented_numbers():
    ins = _ins(shot_xg=0.42, season_goals=9)
    assert grounding_errors("His 9th of the season from a 0.42 xG chance", ins) == []
    assert grounding_errors("His 9th goal, 3 in his last 2 games", ins) == [3.0, 2.0]
    assert grounding_errors("o șansă de 0,42 xG", ins) == []  # comma decimals


def test_checker_catches_flipped_scores_repetition_and_wrong_language():
    ins = _ins(score="0-1", shot_xg=0.42)
    an = PERSONAS["analyst"]
    assert check_line("Port Aldwyn lead 0-1 after a 0.42 xG chance", ins, an, "en") == []
    assert any("scoreline" in p for p in check_line("They lead 1-0", ins, an, "en"))
    assert any("repetition" in p for p in check_line("sonululululululu", ins, an, "ro"))
    assert any("English" in p for p in check_line("The goal puts them in front of the home side", ins, an, "ro"))
    assert check_line("Golul îi duce în față cu 0-1", ins, an, "ro") == []


def test_personas_filter_and_template_fallback():
    low = _ins()
    low.importance = 0.4
    assert relevant(low, PERSONAS["analyst"]) and not relevant(low, PERSONAS["fan"])
    assert relevant(low, PERSONAS["fan"], favourite="PAL")
    line = asyncio.run(Narrator().narrate(low, PERSONAS["fan"], "ro"))
    assert line["source"] == "template" and "note" in line
