"""Interpret: turn the raw event stream into live match statistics."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

# League-average attacking output per team per minute, used to judge whether
# a spell of pressure is unusual for *this point* of the match.
XG_PER_TEAM_MINUTE = 1.35 / 90
REQUIRED_FIELDS = {"match_id", "seq", "period", "t", "minute", "type"}


@dataclass
class TeamStats:
    code: str
    goals: int = 0
    shots: int = 0
    on_target: int = 0
    xg: float = 0.0
    passes: int = 0
    passes_ok: int = 0
    final_third_passes: int = 0
    corners: int = 0
    fouls: int = 0
    yellows: int = 0
    reds: int = 0
    offsides: int = 0
    saves: int = 0
    big_chances: int = 0  # shots with xG >= 0.3

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["xg"] = round(self.xg, 2)
        d["pass_accuracy"] = round(100 * self.passes_ok / self.passes) if self.passes else 0
        return d


@dataclass
class PlayerLine:
    id: str
    name: str
    team: str
    goals: int = 0
    assists: int = 0
    shots: int = 0
    xg: float = 0.0
    passes: int = 0
    passes_ok: int = 0
    tackles: int = 0
    interceptions: int = 0
    fouls: int = 0
    yellow: bool = False
    saves: int = 0
    xg_saved: float = 0.0
    subbed_on_minute: int | None = None
    key_passes: int = 0
    xa: float = 0.0
    dribbles: int = 0
    dribbles_ok: int = 0
    aerials_won: int = 0
    clearances: int = 0
    blocks: int = 0
    shot_speed_max: float = 0.0

    def line(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v not in (0, 0.0, False, None) or k in ("name", "team")}
        for k in ("xg", "xa", "xg_saved"):
            if k in d:
                d[k] = round(d[k], 2)
        return d


@dataclass
class MatchState:
    match_id: str = ""
    home: str = ""
    away: str = ""
    round: int = 0
    minute: int = 0
    clock: str = "1'"
    period: int = 1
    finished: bool = False
    teams: dict[str, TeamStats] = field(default_factory=dict)
    players: dict[str, PlayerLine] = field(default_factory=dict)
    # per-minute xG and shots, for momentum windows
    xg_by_minute: dict[str, dict[int, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float)))
    recent: deque = field(default_factory=lambda: deque(maxlen=30))
    score_history: list[tuple[int, str, str]] = field(default_factory=list)  # (minute, team, scorer)

    # ---- queries ----
    def other(self, code: str) -> str:
        return self.away if code == self.home else self.home

    def score(self) -> dict[str, int]:
        return {self.home: self.teams[self.home].goals, self.away: self.teams[self.away].goals}

    def possession(self, code: str) -> int:
        total = sum(t.passes for t in self.teams.values())
        return round(100 * self.teams[code].passes / total) if total else 50

    def field_tilt(self, code: str) -> int:
        total = sum(t.final_third_passes for t in self.teams.values())
        return round(100 * self.teams[code].final_third_passes / total) if total else 50

    def window_xg(self, code: str, minutes: int = 10) -> float:
        lo = self.minute - minutes
        return sum(v for m, v in self.xg_by_minute[code].items() if m > lo)

    def expected_xg_to_now(self) -> float:
        """What an average team would have built by this minute."""
        return XG_PER_TEAM_MINUTE * max(1, self.minute)

    def snapshot(self) -> dict:
        return {
            "match_id": self.match_id, "home": self.home, "away": self.away,
            "minute": self.minute, "clock": self.clock, "period": self.period,
            "finished": self.finished, "score": self.score(),
            "teams": {c: {**t.to_dict(), "possession": self.possession(c),
                          "field_tilt": self.field_tilt(c),
                          "xg_last10": round(self.window_xg(c), 2)}
                      for c, t in self.teams.items()},
            "players": {pid: p.line() for pid, p in self.players.items() if p.name},
        }

    # ---- update ----
    def player(self, ev: dict) -> PlayerLine | None:
        pid = ev.get("player_id")
        if not pid:
            return None
        if pid not in self.players:
            self.players[pid] = PlayerLine(pid, ev.get("player") or pid, ev.get("team") or "")
        pl = self.players[pid]
        if (not pl.name or pl.name == pid) and ev.get("player"):
            pl.name = ev["player"]
        return pl

    def by_id(self, pid: str, team: str) -> PlayerLine:
        return self.players.setdefault(pid, PlayerLine(pid, "", team))

    def apply(self, ev: dict) -> None:
        missing = REQUIRED_FIELDS - ev.keys()
        if missing:
            raise ValueError(f"event {ev.get('seq')} missing {sorted(missing)}")
        t = ev["type"]
        self.minute, self.period = ev["minute"], ev["period"]
        self.clock = ev.get("clock", self.clock)
        if t == "match_start":
            self.match_id, self.home, self.away = ev["match_id"], ev["home"], ev["away"]
            self.round = ev.get("round", 0)
            self.teams = {self.home: TeamStats(self.home), self.away: TeamStats(self.away)}
            return
        team = self.teams.get(ev.get("team") or "")
        p = self.player(ev)
        if t == "pass" and team:
            team.passes += 1
            ok = ev["outcome"] == "complete"
            team.passes_ok += ok
            if ok and ev.get("end_x", 0) > 66:
                team.final_third_passes += 1
            if p:
                p.passes += 1
                p.passes_ok += ok
        elif t == "shot" and team:
            team.shots += 1
            team.xg += ev["xg"]
            team.on_target += ev["outcome"] in ("goal", "saved")
            team.big_chances += ev["xg"] >= 0.3
            self.xg_by_minute[team.code][self.minute] += ev["xg"]
            if p:
                p.shots += 1
                p.xg += ev["xg"]
                p.shot_speed_max = max(p.shot_speed_max, ev.get("speed_kmh", 0))
            if ev.get("key_pass_id"):
                k = self.by_id(ev["key_pass_id"], team.code)
                k.key_passes += 1
                k.xa += ev["xg"]
        elif t == "goal" and team:
            team.goals += 1
            if p:
                p.goals += 1
            if ev.get("assist_id"):
                a = self.players.setdefault(
                    ev["assist_id"], PlayerLine(ev["assist_id"], ev.get("assist") or "", team.code))
                a.assists += 1
            self.score_history.append((self.minute, team.code, ev.get("player") or ""))
        elif t == "save" and team:
            team.saves += 1
            if p:
                p.saves += 1
                p.xg_saved += ev.get("xg", 0)
        elif t == "corner" and team:
            team.corners += 1
        elif t == "foul" and team:
            team.fouls += 1
            if p:
                p.fouls += 1
        elif t == "card" and team:
            if ev["card"] == "yellow":
                team.yellows += 1
                if p:
                    p.yellow = True
            else:
                team.reds += 1
        elif t == "offside" and team:
            team.offsides += 1
        elif t == "tackle" and p:
            p.tackles += 1
        elif t == "interception" and p:
            p.interceptions += 1
        elif t == "dribble" and p:
            p.dribbles += 1
            p.dribbles_ok += ev["outcome"] == "success"
        elif t == "aerial" and p:
            p.aerials_won += 1
        elif t == "clearance" and p:
            p.clearances += 1
        elif t == "block" and p:
            p.blocks += 1
        elif t == "substitution" and p:
            p.subbed_on_minute = self.minute
        elif t == "match_end":
            self.finished = True
        if t != "pass":
            self.recent.append(ev)
