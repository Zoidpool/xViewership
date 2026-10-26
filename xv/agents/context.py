"""Season context: what was true before kick-off, for the live match's league.

Built from the already-played synthetic matches so live insights can say
"his 9th of the season" or "they have not won in 4". Season progress
(rounds played) drives thresholds, never fixed counts.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SeasonContext:
    league_id: str
    league_name: str
    rounds_played: int
    clubs: dict[str, dict]
    players: dict[str, dict]
    table: list[dict]
    form: dict[str, list[str]]
    player_goals: dict[str, int] = field(default_factory=dict)
    player_assists: dict[str, int] = field(default_factory=dict)
    player_apps: dict[str, int] = field(default_factory=dict)
    player_last_goal_round: dict[str, int] = field(default_factory=dict)
    profiles: dict[str, dict] = field(default_factory=dict)  # player id -> built profile (if available)
    team_profiles: dict[str, dict] = field(default_factory=dict)  # club -> season profile (teams.json)
    league_teams: int = 10

    def position(self, club: str) -> int:
        for i, row in enumerate(self.table, start=1):
            if row["club"] == club:
                return i
        return 0

    def top_scorer_goals(self) -> int:
        return max(self.player_goals.values(), default=0)

    def winless_run(self, club: str) -> int:
        n = 0
        for r in reversed(self.form.get(club, [])):
            if r == "W":
                break
            n += 1
        return n

    def goal_drought(self, player_id: str) -> int:
        last = self.player_last_goal_round.get(player_id)
        apps = self.player_apps.get(player_id, 0)
        return apps if last is None else max(0, self.rounds_played - last)

    def notable_drought(self) -> int:
        return max(3, round(self.rounds_played / 3))

    def club_name(self, code: str) -> str:
        return self.clubs.get(code, {}).get("name", code)


def load_context(data_dir: Path, league: str, before_round: int | None = None,
                 players_json: Path | None = None) -> SeasonContext:
    world = json.loads((data_dir / "world.json").read_text(encoding="utf-8"))
    index = json.loads((data_dir / "season_index.json").read_text(encoding="utf-8"))
    lg = next(l for l in world["leagues"] if l["id"] == league)
    index = [m for m in index if m["league"] == league and "home_goals" in m
             and (before_round is None or m["round"] < before_round)]
    clubs = {c["code"]: c for c in lg["clubs"]}
    players = {p["id"]: p for c in lg["clubs"] for p in c["players"]}

    pts = defaultdict(lambda: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0})
    form: dict[str, list[str]] = defaultdict(list)
    goals: dict[str, int] = defaultdict(int)
    assists: dict[str, int] = defaultdict(int)
    apps: dict[str, int] = defaultdict(int)
    last_goal: dict[str, int] = {}
    for m in sorted(index, key=lambda m: m["round"]):
        h, a, hg, ag = m["home"], m["away"], m["home_goals"], m["away_goals"]
        for club, gf, ga in ((h, hg, ag), (a, ag, hg)):
            row = pts[club]
            row["p"] += 1
            row["gf"] += gf
            row["ga"] += ga
            res = "W" if gf > ga else "D" if gf == ga else "L"
            row[{"W": "w", "D": "d", "L": "l"}[res]] += 1
            row["pts"] += {"W": 3, "D": 1, "L": 0}[res]
            form[club].append(res)
        path = data_dir / "matches" / f"{m['match_id']}.jsonl"
        appeared: set[str] = set()
        with path.open(encoding="utf-8") as f:
            for line in f:
                if '"goal"' not in line and '"match_start"' not in line and '"substitution"' not in line:
                    continue
                ev = json.loads(line)
                if ev["type"] == "match_start":
                    for ids in ev["lineups"].values():
                        appeared.update(ids)
                elif ev["type"] == "substitution":
                    appeared.add(ev["player_id"])
                elif ev["type"] == "goal":
                    goals[ev["player_id"]] += 1
                    last_goal[ev["player_id"]] = m["round"]
                    if ev.get("assist_id"):
                        assists[ev["assist_id"]] += 1
        for pid in appeared:
            apps[pid] += 1
    table = sorted(({"club": c, **r} for c, r in pts.items()),
                   key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"]))
    profiles, team_profiles = {}, {}
    if players_json and players_json.exists():
        profiles = {p["id"]: p for p in json.loads(players_json.read_text(encoding="utf-8"))
                    if p["league"] == league}
        teams_json = players_json.parent / "teams.json"
        if teams_json.exists():
            team_profiles = {c: t for c, t in json.loads(teams_json.read_text(encoding="utf-8"))["teams"].items()
                             if t.get("league") == league}
    return SeasonContext(
        league_id=league, league_name=lg["name"], rounds_played=max((m["round"] for m in index), default=0),
        clubs=clubs, players=players, table=table, form=dict(form), player_goals=dict(goals),
        player_assists=dict(assists), player_apps=dict(apps), player_last_goal_round=last_goal,
        profiles=profiles, team_profiles=team_profiles, league_teams=len(clubs))
