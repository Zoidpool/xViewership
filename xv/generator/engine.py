"""Synthetic match engine.

Simulates a match as a chain of possessions. The ball moves from carrier to
receiver; every action is an event: passes (with length, cross / long-ball
flags and the receiver), dribbles, aerial duels, tackles, interceptions,
clearances, blocks, shots with xG / xG on target / shot speed, saves, fouls,
cards, corners, offsides, substitutions, and a physical summary (distance,
top speed) per player at the end.

League personality (tempo, openness, fouls, cards, home advantage) scales the
rates. Run `python -m xv.generator.validate` to compare averages with real
top-flight ranges.

Pitch coordinates: x 0-100 towards the attacking team's target goal,
y 0-100 left to right; the pitch is treated as 105 x 68 metres.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .league import Club, Player

PERIOD_SECONDS = 45 * 60
DEFAULT_LEAGUE = {"home_adv": 4.0, "tempo": 1.0, "open": 1.0, "fouls": 1.0, "cards": 1.0}


def shot_xg(x: float, y: float, header: bool = False) -> float:
    """Expected-goals estimate from shot location (distance + goal angle)."""
    dx = max(0.5, (100 - x) * 1.05)
    dy = abs(y - 50) * 0.68
    dist = math.hypot(dx, dy)
    half_goal = 7.32 / 2
    angle = math.atan2(2 * half_goal * dx, dx * dx + dy * dy - half_goal * half_goal)
    if angle < 0:
        angle += math.pi
    logit = -1.8 + 1.35 * angle - 0.085 * dist
    if header:
        logit -= 0.9
    return round(1 / (1 + math.exp(-logit)), 3)


def metres(x0: float, y0: float, x1: float, y1: float) -> float:
    return math.hypot((x1 - x0) * 1.05, (y1 - y0) * 0.68)


# who tends to have the ball in each third (role weights)
ZONE_WEIGHTS = [
    {"GK": 0.6, "CB": 3.0, "FB": 2.0, "DM": 2.2, "CM": 1.6, "AM": 0.4, "W": 0.4, "ST": 0.2},
    {"CB": 1.0, "FB": 1.8, "DM": 2.0, "CM": 2.6, "AM": 2.0, "W": 1.6, "ST": 0.8},
    {"CB": 0.3, "FB": 1.2, "DM": 0.6, "CM": 1.6, "AM": 2.4, "W": 2.6, "ST": 2.2},
]
DEF_WEIGHTS = [  # defenders by where the *attacking* side has the ball
    {"CB": 0.3, "FB": 0.8, "DM": 1.0, "CM": 1.6, "AM": 1.6, "W": 1.4, "ST": 1.4},
    {"CB": 1.0, "FB": 1.6, "DM": 2.6, "CM": 2.2, "AM": 1.0, "W": 0.8, "ST": 0.4},
    {"CB": 3.2, "FB": 2.2, "DM": 2.0, "CM": 1.0, "AM": 0.3, "W": 0.4, "ST": 0.1},
]
SHOOTER = {"CB": 0.25, "FB": 0.3, "DM": 0.35, "CM": 0.9, "AM": 1.7, "W": 2.0, "ST": 3.4}
HEADER = {"CB": 1.6, "FB": 0.4, "DM": 0.5, "CM": 0.6, "AM": 0.4, "W": 0.7, "ST": 3.0}


@dataclass
class Side:
    club: Club
    is_home: bool
    on_pitch: list[Player]
    bench: list[Player]
    goals: int = 0
    subs_used: int = 0
    sub_windows: list[int] = field(default_factory=list)
    yellows: set[str] = field(default_factory=set)
    sent_off: set[str] = field(default_factory=set)
    entered: dict[str, int] = field(default_factory=dict)  # player id -> minute on
    left: dict[str, int] = field(default_factory=dict)  # player id -> minute off

    @property
    def code(self) -> str:
        return self.club.code

    def outfield(self) -> list[Player]:
        return [p for p in self.on_pitch if p.role != "GK"]

    def keeper(self) -> Player:
        gks = [p for p in self.on_pitch if p.role == "GK"]
        return gks[0] if gks else self.on_pitch[0]


class MatchSim:
    def __init__(self, home: Club, away: Club, match_id: str, seed: int, round_no: int = 1,
                 league: dict | None = None):
        self.rng = random.Random(seed)
        self.match_id = match_id
        self.round_no = round_no
        self.lg = {**DEFAULT_LEAGUE, **(league or {})}
        self.events: list[dict] = []
        self.sides = {"home": self._side(home, True), "away": self._side(away, False)}
        self.period = 1
        self.t = 0.0

    # ---------- setup ----------
    def _side(self, club: Club, is_home: bool) -> Side:
        xi = club.starting_xi()
        s = Side(club=club, is_home=is_home, on_pitch=list(xi), bench=club.bench())
        s.entered = {p.id: 0 for p in xi}
        s.sub_windows = sorted(max(46, min(88, round(self.rng.gauss(m, sd))))
                               for m, sd in ((61, 6), (71, 5), (81, 4)))
        return s

    def _other(self, key: str) -> str:
        return "away" if key == "home" else "home"

    def _strength(self, key: str) -> float:
        side = self.sides[key]
        s = side.club.strength + (self.lg["home_adv"] if side.is_home else 0)
        return s - 6 * len(side.sent_off)

    # ---------- clock / emit ----------
    def _minute(self) -> int:
        return int(self.t // 60) + (0 if self.period == 1 else 45)

    def _clock(self) -> str:
        base = 45 if self.period == 1 else 90
        m = self._minute()
        return f"{base}+{m - base + 1}'" if m >= base else f"{m + 1}'"

    def emit(self, type_: str, team: str | None = None, player: Player | None = None,
             **extra) -> dict:
        ev = {"match_id": self.match_id, "seq": len(self.events), "period": self.period,
              "t": round(self.t, 1), "minute": self._minute(), "clock": self._clock(),
              "type": type_, "team": self.sides[team].code if team else None,
              "player_id": player.id if player else None,
              "player": player.name if player else None}
        ev.update({k: v for k, v in extra.items() if v is not None})
        self.events.append(ev)
        return ev

    def tick(self, lo: float, hi: float) -> None:
        self.t += self.rng.uniform(lo, hi) / self.lg["tempo"]

    # ---------- player picks ----------
    @staticmethod
    def _zone(x: float) -> int:
        return 0 if x < 35 else 1 if x < 68 else 2

    def _pick(self, key: str, weights: dict[str, float], attr: str | None = None,
              exclude: Player | None = None) -> Player:
        pool = [p for p in (self.sides[key].outfield() or self.sides[key].on_pitch)
                if p is not exclude] or self.sides[key].on_pitch
        w = []
        for p in pool:
            base = weights.get(p.role, 0.05)
            if attr:
                base *= 0.5 + getattr(p, attr) / 100
            w.append(base)
        return self.rng.choices(pool, weights=w, k=1)[0]

    def receiver(self, key: str, x: float, exclude: Player | None = None) -> Player:
        if x < 20 and self.rng.random() < 0.25:
            return self.sides[key].keeper()
        z = self._zone(x)
        return self._pick(key, ZONE_WEIGHTS[z], ("passing", "vision", "dribbling")[z], exclude)

    def defender(self, key: str, attacking_x: float, attr: str = "tackling") -> Player:
        return self._pick(key, DEF_WEIGHTS[self._zone(attacking_x)], attr)

    # ---------- game state ----------
    def _intent(self, key: str) -> float:
        me, opp = self.sides[key], self.sides[self._other(key)]
        diff, m = me.goals - opp.goals, self._minute()
        if diff < 0 and m >= 55:
            return 1.0 + min(0.6, (m - 50) / 70) * min(2, -diff)
        if diff > 0 and m >= 60:
            return 1.0 - min(0.3, (m - 55) / 120)
        return 1.0

    # ---------- main loop ----------
    def run(self) -> list[dict]:
        self.emit("match_start", home=self.sides["home"].code, away=self.sides["away"].code,
                  round=self.round_no,
                  lineups={k: [p.id for p in s.on_pitch] for k, s in self.sides.items()},
                  roles={p.id: p.role for s in self.sides.values() for p in s.club.players})
        for period, kickoff in ((1, "home"), (2, "away")):
            self.period, self.t = period, 0.0
            stoppage = self.rng.choice([1, 1, 2, 2, 2, 3, 3, 4]) if period == 1 else \
                self.rng.choice([3, 4, 4, 5, 5, 6, 7, 8])
            self.emit("period_start", period=period)
            end_t, announced = PERIOD_SECONDS + stoppage * 60, False
            key, x, carrier = kickoff, 50.0, None
            while self.t < end_t:
                if not announced and self.t >= PERIOD_SECONDS - 30:
                    self.emit("added_time", minutes=stoppage)
                    announced = True
                self._maybe_subs()
                key, x, carrier = self.possession(key, x, carrier)
            self.emit("period_end", period=period,
                      score={k: s.goals for k, s in self.sides.items()})
        self._physical()
        self.emit("match_end", score={k: s.goals for k, s in self.sides.items()})
        return self.events

    def _physical(self) -> None:
        """Distance covered and top speed per player who played (tracking-style summary)."""
        end = self._minute() + 1
        for key, side in self.sides.items():
            for pid, on in side.entered.items():
                p = next(q for q in side.club.players if q.id == pid)
                mins = max(1, side.left.get(pid, end) - on)
                per90 = {"GK": 5.6, "CB": 9.9, "FB": 10.8, "DM": 11.0, "CM": 11.6, "AM": 11.0,
                         "W": 10.7, "ST": 10.2}[p.role] + (p.stamina - 70) * 0.03
                self.emit("physical", key, p, minutes=mins,
                          distance_km=round(max(0.3, self.rng.gauss(per90, 0.4)) * mins / 90, 2),
                          top_speed_kmh=round(self.rng.gauss(27.5 + (p.pace - 60) * 0.11, 0.9), 1),
                          sprints=max(0, round(self.rng.gauss(p.pace / 3.2, 4) * mins / 90)))

    def _maybe_subs(self) -> None:
        if self.period != 2:
            return
        m = self._minute()
        for key, side in self.sides.items():
            while side.sub_windows and m >= side.sub_windows[0]:
                side.sub_windows.pop(0)
                n = self.rng.choice([1, 1, 2, 2, 2]) if side.subs_used < 3 else 1
                for _ in range(n):
                    if side.subs_used >= 5:
                        break
                    self._substitute(key, side)
                self.tick(20, 40)

    def _substitute(self, key: str, side: Side) -> None:
        cands = [p for p in side.outfield() if p.id not in side.sent_off]
        if not cands or not side.bench:
            return
        off = max(cands, key=lambda p: (100 - p.stamina) + (25 if p.id in side.yellows else 0)
                  + self.rng.uniform(0, 30))
        want = "ST" if self._intent(key) > 1.1 and off.role in ("CB", "FB") else off.role
        bench = [p for p in side.bench if p.role == want] or \
                [p for p in side.bench if p.role != "GK"]
        if not bench:
            return
        on = self.rng.choice(bench)
        side.bench.remove(on)
        side.on_pitch[side.on_pitch.index(off)] = on
        side.entered[on.id] = self._minute()
        side.left[off.id] = self._minute()
        side.subs_used += 1
        self.emit("substitution", key, on, player_off_id=off.id, player_off=off.name)

    # ---------- possession ----------
    def possession(self, key: str, x: float, carrier: Player | None):
        """Play one possession. Returns the next (team, x, carrier)."""
        rng, opp, lg = self.rng, self._other(key), self.lg
        edge = (self._strength(key) - self._strength(opp)) / 100
        intent = self._intent(key)
        carrier = carrier if carrier in self.sides[key].on_pitch else self.receiver(key, x)
        y = rng.uniform(10, 90)
        last_passer: Player | None = None
        for _ in range(40):
            if x > 66:
                shot_p = (0.040 + (x - 66) * 0.0024) * intent * (1 + edge) * lg["open"]
                if rng.random() < shot_p:
                    return self.shot(key, x, header=rng.random() < 0.12, assister=last_passer)
            if rng.random() < 0.022 * lg["fouls"]:
                return self.foul(key, x, carrier)
            if x > 70 and rng.random() < 0.019 * intent:
                fw = self._pick(key, {"ST": 3, "W": 1.5, "AM": 0.5})
                self.emit("offside", key, fw, x=round(x, 1))
                self.tick(15, 30)
                return opp, 100 - x, None
            # take-on
            if carrier.role in ("W", "AM", "FB", "ST", "CM") and x > 40 and \
                    rng.random() < 0.06 * (carrier.dribbling / 65) ** 2:
                d = self.defender(opp, x)
                ok = rng.random() < 0.5 + (carrier.dribbling - d.tackling) / 160
                self.emit("dribble", key, carrier, outcome="success" if ok else "fail",
                          x=round(x, 1), opponent_id=d.id)
                self.tick(1.5, 3)
                if ok:
                    x = min(96.0, x + rng.uniform(5, 12))
                    continue
                self.emit("tackle", opp, d, x=round(100 - x, 1), won=True)
                return opp, 100 - x, d
            # cross from wide areas
            if carrier.role in ("W", "FB") and x > 66 and rng.random() < 0.32 * (carrier.crossing / 65):
                return self.cross(key, x, carrier)
            # long ball from the back
            if (carrier.role == "GK" and x < 15 and rng.random() < 0.65) or \
                    (carrier.role in ("CB", "DM") and x < 40 and rng.random() < 0.10):
                return self.long_ball(key, x, y, carrier)
            # ordinary pass
            progress = rng.gauss(4.5 * intent, 10)
            nx = min(97.0, max(3.0, x + progress))
            ny = min(97.0, max(3.0, y + rng.gauss(0, 16)))
            difficulty = max(0.0, (x - 55) / 100) + max(0.0, progress) / 120
            ok_p = 0.875 + (carrier.passing - 65) * 0.0035 + edge * 0.35 - difficulty * 0.6
            ok_p = min(0.96, max(0.45, ok_p))
            self.tick(2.4, 4.6)
            rec = self.receiver(key, nx, exclude=carrier)
            length = round(metres(x, y, nx, ny), 1)
            if rng.random() < ok_p:
                box = nx > 83 and 21 < ny < 79
                self.emit("pass", key, carrier, outcome="complete", x=round(x, 1), y=round(y, 1),
                          end_x=round(nx, 1), end_y=round(ny, 1), length=length,
                          receiver_id=rec.id, box=box or None)
                last_passer, carrier, x, y = carrier, rec, nx, ny
                continue
            self.emit("pass", key, carrier, outcome="incomplete", x=round(x, 1), y=round(y, 1),
                      end_x=round(nx, 1), end_y=round(ny, 1), length=length)
            r = rng.random()
            if r < 0.45:
                d = self.defender(opp, x, "positioning")
                self.emit("interception", opp, d, x=round(100 - nx, 1))
                return opp, max(5.0, 100 - nx), d
            if r < 0.75:
                d = self.defender(opp, x)
                self.emit("tackle", opp, d, x=round(100 - x, 1), won=True)
                return opp, max(5.0, 100 - nx), d
            self.tick(8, 20)  # out of play
            return opp, max(5.0, 100 - nx), None
        return opp, 100 - x, None

    def aerial(self, key: str, att_roles: dict, def_roles: dict) -> tuple[bool, Player, Player]:
        """Attacker v defender header. Returns (attacker won, attacker, defender)."""
        opp = self._other(key)
        a = self._pick(key, att_roles, "aerial")
        d = self._pick(opp, def_roles, "aerial")
        won = self.rng.random() < 0.42 + (a.aerial - d.aerial) / 140
        w, l = (a, d) if won else (d, a)
        self.emit("aerial", key if won else opp, w, loser_id=l.id)
        return won, a, d

    def cross(self, key: str, x: float, carrier: Player):
        rng, opp = self.rng, self._other(key)
        self.tick(2, 4)
        ok = rng.random() < 0.24 + (carrier.crossing - 65) / 300
        self.emit("pass", key, carrier, outcome="complete" if ok else "incomplete", cross=True,
                  x=round(x, 1), y=round(rng.choice([8, 92]) + rng.uniform(-5, 5), 1),
                  end_x=round(rng.uniform(88, 96), 1), end_y=round(rng.uniform(35, 65), 1),
                  length=round(rng.uniform(18, 32), 1))
        if ok:
            won, a, d = self.aerial(key, HEADER, {"CB": 3, "FB": 1, "DM": 0.6})
            if won:
                return self.shot(key, rng.uniform(88, 95), header=True, assister=carrier,
                                 shooter=a)
            self.emit("clearance", opp, d)
        else:
            d = self._pick(opp, {"CB": 3, "FB": 1.5, "DM": 0.5}, "positioning")
            self.emit("clearance", opp, d)
        if rng.random() < 0.24:
            return self.corner(key)
        return opp, rng.uniform(10, 30), None

    def long_ball(self, key: str, x: float, y: float, carrier: Player):
        rng, opp = self.rng, self._other(key)
        nx = min(92.0, x + rng.uniform(25, 42))
        ny = min(95.0, max(5.0, y + rng.gauss(0, 20)))
        self.tick(3, 5)
        won, a, d = self.aerial(key, {"ST": 3, "W": 1.2, "AM": 0.6}, {"CB": 3, "FB": 1})
        self.emit("pass", key, carrier, outcome="complete" if won else "incomplete", long=True,
                  x=round(x, 1), y=round(y, 1), end_x=round(nx, 1), end_y=round(ny, 1),
                  length=round(metres(x, y, nx, ny), 1), receiver_id=a.id if won else None)
        if won:
            return key, nx, a
        if rng.random() < 0.5:
            self.emit("clearance", opp, d)
        return opp, 100 - nx, None

    def foul(self, key: str, x: float, victim: Player):
        rng, opp, lg = self.rng, self._other(key), self.lg
        side_o = self.sides[opp]
        offender = self.defender(opp, x)
        in_box = x > 84 and rng.random() < 0.13
        self.emit("foul", opp, offender, victim_id=victim.id, victim=victim.name,
                  x=round(100 - x, 1), in_box=in_box or None)
        self.tick(15, 35)
        card_p = (0.13 + (65 - offender.discipline) * 0.004 + (0.08 if x > 60 else 0)) * lg["cards"]
        if in_box:
            card_p += 0.15
        if offender.id in side_o.yellows:
            card_p *= 0.45
        if rng.random() < 0.0015 * lg["cards"]:
            self._send_off(opp, offender, "red", "serious foul play")
        elif rng.random() < card_p:
            self.emit("card", opp, offender, card="yellow")
            if offender.id in side_o.yellows:
                self._send_off(opp, offender, "second_yellow", "second bookable offence")
            else:
                side_o.yellows.add(offender.id)
            self.tick(15, 30)
        if in_box:
            return self.shot(key, 89.5, header=False, penalty=True)
        if x > 74 and rng.random() < 0.18:
            return self.shot(key, x, header=False, free_kick=True)
        return key, x, victim

    def _send_off(self, key: str, player: Player, card: str, reason: str) -> None:
        side = self.sides[key]
        side.sent_off.add(player.id)
        side.left[player.id] = self._minute()
        if player in side.on_pitch:
            side.on_pitch.remove(player)
        self.emit("card", key, player, card=card, reason=reason)

    def corner(self, key: str):
        taker = self._pick(key, {"W": 2, "AM": 2, "CM": 1.5, "FB": 1}, "crossing")
        self.emit("corner", key, taker)
        self.tick(20, 40)
        if self.rng.random() < 0.34:
            won, a, d = self.aerial(key, HEADER, {"CB": 3, "ST": 0.8, "DM": 1})
            if won and self.rng.random() < 0.85:
                return self.shot(key, self.rng.uniform(86, 95), header=True,
                                 from_corner=True, assister=taker, shooter=a)
            self.emit("clearance", self._other(key), d)
        return self._other(key), self.rng.uniform(5, 25), None

    def shot(self, key: str, x: float, header: bool, penalty: bool = False,
             free_kick: bool = False, from_corner: bool = False,
             assister: Player | None = None, shooter: Player | None = None):
        rng, opp = self.rng, self._other(key)
        me, them = self.sides[key], self.sides[opp]
        if penalty:
            shooter = max(me.outfield(), key=lambda p: p.finishing)
            sx, sy, xg = 89.5, 50.0, 0.76
        else:
            if shooter is None:
                shooter = self._pick(key, HEADER if header else SHOOTER,
                                     None if header else "finishing", exclude=assister)
            sx = min(98.0, max(55.0, x + rng.gauss(4, 6)))
            sy = min(92.0, max(8.0, rng.gauss(50, 14 if sx > 85 else 20)))
            xg = shot_xg(sx, sy, header)
            if free_kick:
                xg = round(min(xg, 0.07), 3)
        if assister is shooter or penalty or free_kick:
            assister = None
        gk = them.keeper()
        finish_mod = 1 + (shooter.finishing - 68) / 120
        gk_mod = 1 - (gk.goalkeeping - 68) / 160
        goal_p = min(0.95, xg * finish_mod * gk_mod)
        if rng.random() < goal_p:
            outcome = "goal"
        else:
            rest = rng.random()
            if penalty:
                outcome = "saved" if rest < 0.7 else "off_target"
            elif rest < 0.27 - (0.08 if header else 0):
                outcome = "saved"
            elif rest < 0.53:
                outcome = "blocked"
            elif rest < 0.555:
                outcome = "woodwork"
            else:
                outcome = "off_target"
        on_target = outcome in ("goal", "saved")
        xgot = round(min(0.97, max(xg, xg * rng.gauss(1.5, 0.35))), 3) if on_target else None
        speed = round(rng.gauss(52, 8) if header else rng.gauss(88 + (shooter.finishing - 65) * 0.3, 11), 1)
        if penalty:
            speed = round(rng.gauss(98, 6), 1)
        self.tick(1, 3)
        ev = self.emit("shot", key, shooter, outcome=outcome, xg=xg, xgot=xgot,
                       x=round(sx, 1), y=round(sy, 1), body_part="head" if header else "foot",
                       speed_kmh=max(35.0, speed),
                       situation="penalty" if penalty else "free_kick" if free_kick else
                       "corner" if from_corner else "open_play",
                       key_pass_id=assister.id if assister else None,
                       assist_id=assister.id if (assister and outcome == "goal") else None,
                       assist=assister.name if (assister and outcome == "goal") else None,
                       keeper_id=gk.id if on_target else None)
        if outcome == "goal":
            me.goals += 1
            self.emit("goal", key, shooter, shot_seq=ev["seq"], xg=xg,
                      assist_id=ev.get("assist_id"), assist=ev.get("assist"),
                      keeper_id=gk.id, score={k: s.goals for k, s in self.sides.items()})
            self.tick(50, 80)
            return opp, 50.0, None
        if outcome == "saved":
            self.emit("save", opp, gk, xg=xg, xgot=xgot)
            if rng.random() < 0.3:
                self.tick(5, 10)
                return self.corner(key)
            self.tick(4, 10)
            return opp, 8.0, gk
        if outcome == "blocked":
            b = self._pick(opp, {"CB": 3, "FB": 1.4, "DM": 1.2, "CM": 0.6}, "positioning")
            self.emit("block", opp, b)
            if rng.random() < 0.4:
                return self.corner(key)
            return (key, 75.0, None) if rng.random() < 0.35 else (opp, 15.0, b)
        self.tick(18, 30)  # goal kick
        return opp, 8.0, gk


def simulate_match(home: Club, away: Club, match_id: str, seed: int, round_no: int = 1,
                   league: dict | None = None) -> list[dict]:
    return MatchSim(home, away, match_id, seed, round_no, league).run()
