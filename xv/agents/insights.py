"""Explain: decide which moments matter and why.

Each detector returns an Insight with:
  facts  - every number a narrator is allowed to use (the evidence)
  why    - deterministic reasons, each tied to facts, so a viewer can see
           exactly what triggered the card
Thresholds scale with match minute and season progress, not fixed counts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..analytics.profiles import ARCHETYPES
from ..analytics.stats import CATALOG
from .context import SeasonContext
from .depth import season_depth
from .state import XG_PER_TEAM_MINUTE, MatchState


@dataclass
class Insight:
    id: str
    match_id: str
    seq: int
    minute: int
    clock: str
    kind: str
    team: str | None
    importance: float  # 0..1; personas filter on this
    title: str
    facts: dict[str, Any]
    why: list[dict[str, str]] = field(default_factory=list)
    depth: list[dict[str, str]] = field(default_factory=list)  # season context (depth.py)

    def to_dict(self) -> dict:
        return asdict(self)


ARCH_WEIGHTS = {aid: w for role in ARCHETYPES.values() for aid, _, _, w in role}
STAT_LABELS = {k: v[0] for k, v in CATALOG.items()}


def _a(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


ROLE_PLURAL = {"GK": "goalkeepers", "CB": "centre-backs", "FB": "full-backs", "DM": "defensive midfielders",
               "CM": "central midfielders", "AM": "attacking midfielders", "W": "wingers", "ST": "strikers"}


def _r(x: float, n: int = 2) -> float:
    return round(x, n)


class InsightEngine:
    def __init__(self, ctx: SeasonContext, fixture: dict | None = None):
        self.ctx = ctx
        self.fixture = fixture or {}
        self.last_reported: dict | None = None  # probabilities at the last probability card
        self.cooldown: dict[tuple[str, str], int] = {}  # (kind, team) -> minute fired
        self.fired_once: set[tuple[str, str]] = set()
        self._last_minute = -1

    # ---------- helpers ----------
    def _ok(self, kind: str, team: str, gap: int, minute: int) -> bool:
        last = self.cooldown.get((kind, team))
        if last is not None and minute - last < gap:
            return False
        self.cooldown[(kind, team)] = minute
        return True

    def _mk(self, st: MatchState, ev: dict, kind: str, team: str | None, imp: float,
            title: str, facts: dict, why: list[tuple[str, str]]) -> Insight:
        # every insight carries the match context, so narrators never guess who is who
        if st.home:
            facts = {"home_team": self.name(st.home), "away_team": self.name(st.away),
                     "match_state": self.match_state(st), **facts}
        try:
            depth = season_depth(self, st, ev, kind, team, facts)
        except (KeyError, TypeError, ZeroDivisionError):  # context is a bonus; never block an insight
            depth = []
        return Insight(
            id=f"{st.match_id}-{ev['seq']}-{kind}", match_id=st.match_id, seq=ev["seq"],
            minute=ev["minute"], clock=ev.get("clock", ""), kind=kind, team=team,
            importance=round(min(1.0, imp), 2), title=title, facts=facts,
            why=[{"code": c, "text": t} for c, t in why],
            depth=[{"code": c, "text": t if t.startswith("xG") else t[0].upper() + t[1:]} for c, t in depth])

    def name(self, code: str | None) -> str:
        return self.ctx.club_name(code) if code else ""

    def match_state(self, st: MatchState) -> str:
        s = st.score()
        h, a = s.get(st.home, 0), s.get(st.away, 0)
        score = f"{h}-{a}"
        if h == a:
            return f"level at {score}" if not st.finished else f"draw {score}"
        lead = st.home if h > a else st.away
        side = "home" if lead == st.home else "away"
        verb = "won" if st.finished else "lead"
        return f"{self.name(lead)} ({side}) {verb} {score}"

    # ---------- entry ----------
    def on_event(self, st: MatchState, ev: dict, probs: dict | None = None,
                 before: dict | None = None) -> list[Insight]:
        t = ev["type"]
        out: list[Insight] = []
        if t == "match_start":
            out.append(self.preview(st, ev))
            self.last_reported = probs
        elif t == "goal":
            out.append(self.goal(st, ev, probs, before))
            self.last_reported = probs
        elif t == "shot" and ev["outcome"] in ("off_target", "woodwork", "blocked", "saved"):
            ins = self.chance(st, ev)
            if ins:
                out.append(ins)
        elif t == "card" and ev["card"] != "yellow":
            out.append(self.red(st, ev, probs, before))
            self.last_reported = probs
        elif t == "foul":
            ins = self.thin_ice(st, ev)
            if ins:
                out.append(ins)
        elif t == "period_end":
            out.append(self.summary(st, ev, final=ev["period"] == 2))
        if ev["minute"] != self._last_minute:
            self._last_minute = ev["minute"]
            out.extend(self.flow(st, ev))
            drift = self.drift(st, ev, probs)
            if drift:
                out.append(drift)
        return out

    # ---------- probability ----------
    @staticmethod
    def _pp(p: float) -> int:
        return round(100 * p)

    def prob_facts(self, st: MatchState, probs: dict | None, before: dict | None,
                   code: str | None) -> dict:
        """Win-probability facts for the team in focus (before and after the moment)."""
        if not probs or not code:
            return {}
        side = "home" if code == st.home else "away"
        f = {"win_prob_now_pct": self._pp(probs[side]), "draw_prob_now_pct": self._pp(probs["draw"])}
        if before:
            f["win_prob_before_pct"] = self._pp(before[side])
        return f

    def drift(self, st: MatchState, ev: dict, probs: dict | None) -> Insight | None:
        """Probabilities moved a lot without a goal or red card (pressure, the clock)."""
        if not probs or not self.last_reported or st.finished or ev["minute"] < 15:
            return None
        if ev["type"] in ("period_end", "match_end") or ev["minute"] >= 90:
            return None  # in stoppage time the clock alone moves everything; full time says it
        side = max(("home", "away"), key=lambda s: abs(probs[s] - self.last_reported[s]))
        delta = probs[side] - self.last_reported[side]
        if abs(delta) < 0.12 or not self._ok("drift", side, 12, ev["minute"]):
            return None
        code = st.home if side == "home" else st.away
        facts = {"team": self.name(code), "win_prob_before_pct": self._pp(self.last_reported[side]),
                 "win_prob_now_pct": self._pp(probs[side]), "minute": ev["minute"] + 1,
                 "draw_prob_now_pct": self._pp(probs["draw"])}
        why = [("prob_drift", f"{facts['team']}'s chance of winning moved from "
                f"{facts['win_prob_before_pct']}% to {facts['win_prob_now_pct']}% without a goal")]
        why += [("model", w) for w in probs.get("why", [])[:2]]
        if delta < 0 and st.score()[code] == st.score()[st.other(code)]:
            why.append(("clock", "time running out on a level game pulls toward the draw"))
        self.last_reported = probs
        return self._mk(st, ev, "probability", code, 0.5 + min(0.3, abs(delta)),
                        f"{facts['team']}: win chance {facts['win_prob_before_pct']}% to "
                        f"{facts['win_prob_now_pct']}%", facts, why)

    # ---------- detectors ----------
    def preview(self, st: MatchState, ev: dict) -> Insight:
        c = self.ctx
        facts: dict[str, Any] = {"round": st.round, "rounds_played": c.rounds_played}
        why = []
        for side, code in (("home", st.home), ("away", st.away)):
            facts[f"{side}_team"] = self.name(code)
            facts[f"{side}_position"] = c.position(code)
            facts[f"{side}_form"] = "".join(c.form.get(code, [])[-5:])
            run = c.winless_run(code)
            facts[f"{side}_winless_run"] = run
            if run >= max(3, round(c.rounds_played / 5)):
                why.append(("winless_run", f"{self.name(code)} are without a win in {run}"))
            scorers = sorted(((pid, g) for pid, g in c.player_goals.items()
                              if c.players.get(pid, {}).get("club") == code),
                             key=lambda x: -x[1])
            if scorers:
                pid, g = scorers[0]
                facts[f"{side}_top_scorer"] = c.players[pid]["name"]
                facts[f"{side}_top_scorer_goals"] = g
        gap = abs(facts["home_position"] - facts["away_position"])
        why.insert(0, ("table", f"{facts['home_team']} ({_ord(facts['home_position'])}) host "
                       f"{facts['away_team']} ({_ord(facts['away_position'])})"))
        imp = 0.5 + (0.1 if gap <= 2 else 0)
        model, market = self.fixture.get("model"), self.fixture.get("market")
        if model and market:
            for o in ("home", "draw", "away"):
                facts[f"model_{o}_pct"] = self._pp(model[o])
                facts[f"market_{o}_pct"] = self._pp(market[o])
            why.append(("probabilities", f"xV's model: {facts['model_home_pct']}% home, "
                        f"{facts['model_draw_pct']}% draw, {facts['model_away_pct']}% away; "
                        f"the market: {facts['market_home_pct']}/{facts['market_draw_pct']}/"
                        f"{facts['market_away_pct']}"))
            o = max(("home", "draw", "away"), key=lambda k: abs(model[k] - market[k]))
            if abs(model[o] - market[o]) >= 0.05:
                label = {"home": f"a {facts['home_team']} win", "draw": "a draw",
                         "away": f"a {facts['away_team']} win"}[o]
                why.append(("disagree", f"model and market disagree most on {label}: "
                            f"{facts[f'model_{o}_pct']}% v {facts[f'market_{o}_pct']}%"))
                imp += 0.05
        return self._mk(st, ev, "preview", None, imp,
                        f"{facts['home_team']} v {facts['away_team']}", facts, why)

    def goal(self, st: MatchState, ev: dict, probs: dict | None = None,
             before: dict | None = None) -> Insight:
        c, code = self.ctx, ev["team"]
        opp = st.other(code)
        pid = ev["player_id"]
        pl = st.players.get(pid)
        score = st.score()
        mine, theirs = score[code], score[opp]
        xg = ev.get("xg", 0)
        team_xg_before = st.teams[code].xg - xg
        opp_xg = st.teams[opp].xg
        tilt = st.field_tilt(code)
        season_before = c.player_goals.get(pid, 0)
        match_goals = pl.goals if pl else 1
        facts: dict[str, Any] = {
            "scorer": ev["player"], "team": self.name(code), "minute": ev["minute"] + 1,
            "score": f"{score[st.home]}-{score[st.away]}", "shot_xg": _r(xg),
            "team_xg": _r(st.teams[code].xg), "opponent_xg": _r(opp_xg),
            "field_tilt_pct": tilt, "season_goals": season_before + match_goals,
            "match_goals": match_goals,
        }
        if ev.get("assist"):
            facts["assist"] = ev["assist"]
        why: list[tuple[str, str]] = []
        imp = 0.7
        if mine == theirs:
            why.append(("equaliser", f"levels it at {facts['score']}"))
            imp += 0.08
        elif mine == theirs + 1:
            why.append(("go_ahead", f"puts {facts['team']} in front"))
            imp += 0.08
        if mine > theirs and any(t != code for _, t, _ in st.score_history[:1]) \
                and mine - theirs == 1 and len(st.score_history) >= 3:
            why.append(("comeback", f"{facts['team']} were behind earlier"))
            imp += 0.05
        if ev["minute"] >= 80:
            why.append(("late", f"scored in minute {facts['minute']}"))
            imp += 0.08
        if ev.get("situation") == "penalty" or xg == 0.76:
            facts["situation"] = "penalty"
            why.append(("penalty", "from the penalty spot"))
        elif xg < 0.06:
            why.append(("low_xg_finish",
                        f"the chance was worth only {facts['shot_xg']} xG"))
            imp += 0.05
        elif xg >= 0.5:
            why.append(("big_chance", f"a {facts['shot_xg']} xG chance, taken"))
        if team_xg_before + 0.4 < opp_xg or tilt < 38:
            why.append(("against_run", f"against the run of play: {facts['team']} had "
                        f"{_r(team_xg_before)} xG to {facts['opponent_xg']}, "
                        f"{tilt}% field tilt"))
            facts["team_xg_before_goal"] = _r(team_xg_before)
            imp += 0.05
        if match_goals == 2:
            why.append(("brace", f"{ev['player']}'s second of the match"))
        elif match_goals == 3:
            why.append(("hat_trick", f"hat-trick for {ev['player']}"))
            imp += 0.1
        drought = c.goal_drought(pid)
        if season_before > 0 and drought >= c.notable_drought():
            facts["games_since_last_goal"] = drought
            why.append(("drought_over", f"first goal in {drought} league games"))
        elif season_before == 0 and c.player_apps.get(pid, 0) >= c.notable_drought():
            facts["apps_before_first_goal"] = c.player_apps[pid]
            why.append(("first_of_season",
                        f"first league goal of the season, at the {c.player_apps[pid] + 1}th try"))
        top = c.top_scorer_goals()
        if facts["season_goals"] > top:
            why.append(("top_scorer", f"now the league's top scorer on {facts['season_goals']}"))
            imp += 0.05
        elif facts["season_goals"] == top and top > 0:
            why.append(("joint_top", f"level with the league's top scorer on {top}"))
        pf = self.prob_facts(st, probs, before, code)
        if pf.get("win_prob_before_pct") is not None:
            facts.update(pf)
            swing = pf["win_prob_now_pct"] - pf["win_prob_before_pct"]
            why.append(("win_prob", f"{facts['team']}'s chance of winning: "
                        f"{pf['win_prob_before_pct']}% before, {pf['win_prob_now_pct']}% now"))
            imp += min(0.1, abs(swing) / 300)
        prof = self.ctx.profiles.get(pid)
        if prof and prof.get("archetype") and prof.get("eligible"):
            # the stats that define the player's archetype, best percentile first
            keys = [k for k, w in ARCH_WEIGHTS.get(prof["archetype"]["id"], {}).items() if w > 0] \
                or ["npxg", "goals", "shots"]
            best = sorted(((k, v) for k, v in prof["pct"].items() if v is not None and k in keys),
                          key=lambda kv: -kv[1])[:1]
            facts["archetype"] = prof["archetype"]["name"]
            if best:
                facts["season_percentile_stat"] = STAT_LABELS.get(best[0][0], best[0][0]).lower()
                facts["season_percentile"] = best[0][1]
                arch = prof["archetype"]["name"].lower()
                why.append(("profile", f"{_a(arch)} {arch}: {_ord(best[0][1])} "
                            f"percentile for {facts['season_percentile_stat']} among the league's "
                            f"{ROLE_PLURAL.get(prof['role'], 'players')}"))
        if pl and pl.subbed_on_minute is not None:
            facts["came_on_minute"] = pl.subbed_on_minute + 1
            why.append(("super_sub", f"came on in minute {facts['came_on_minute']}"))
        return self._mk(st, ev, "goal", code, imp,
                        f"GOAL {ev['player']} ({facts['team']}) {facts['score']}", facts, why)

    def chance(self, st: MatchState, ev: dict) -> Insight | None:
        xg = ev["xg"]
        code = ev["team"]
        if ev["outcome"] == "saved" and xg >= 0.3:
            keeper = self.ctx.players.get(ev.get("keeper_id") or "", {}).get("name", "the keeper")
            facts = {"shooter": ev["player"], "shooter_team": self.name(code), "shot_xg": _r(xg),
                     "keeper": keeper, "keeper_team": self.name(st.other(code)),
                     "minute": ev["minute"] + 1}
            return self._mk(st, ev, "big_save", st.other(code), 0.5 + xg / 3,
                            f"Big save by {keeper}", facts,
                            [("big_save", f"denies {ev['player']} from a {facts['shot_xg']} "
                              f"xG chance")])
        if ev["outcome"] == "woodwork" or xg >= 0.35:
            facts = {"shooter": ev["player"], "shooter_team": self.name(code), "shot_xg": _r(xg),
                     "outcome": ev["outcome"], "minute": ev["minute"] + 1,
                     "shooter_team_xg": _r(st.teams[code].xg)}
            woodwork = ev["outcome"] == "woodwork"
            title = "Off the woodwork" if woodwork else "Big chance missed"
            what = "hits the woodwork" if woodwork else "misses"
            return self._mk(st, ev, "big_miss", code, 0.4 + xg / 3, title, facts,
                            [("big_miss", f"{ev['player']} {what} from a "
                              f"{facts['shot_xg']} xG chance")])
        return None

    def red(self, st: MatchState, ev: dict, probs: dict | None = None,
            before: dict | None = None) -> Insight:
        code = ev["team"]
        left = 90 - ev["minute"]
        facts = {"player": ev["player"], "team": self.name(code), "card": ev["card"],
                 "minute": ev["minute"] + 1, "minutes_left": max(0, left),
                 "score": f"{st.score()[st.home]}-{st.score()[st.away]}"}
        how = "second yellow" if ev["card"] == "second_yellow" else "straight red"
        why = [("red", f"{how}: {self.name(code)} play the last {facts['minutes_left']} "
                f"minutes with ten")]
        pf = self.prob_facts(st, probs, before, code)
        if pf.get("win_prob_before_pct") is not None:
            facts.update(pf)
            why.append(("win_prob", f"their chance of winning: {pf['win_prob_before_pct']}% before, "
                        f"{pf['win_prob_now_pct']}% now"))
        return self._mk(st, ev, "red_card", code, 0.75 + left / 400,
                        f"Red card: {ev['player']}", facts, why)

    def thin_ice(self, st: MatchState, ev: dict) -> Insight | None:
        pl = st.players.get(ev.get("player_id") or "")
        if not pl or not pl.yellow:
            return None
        if not self._ok("thin_ice", pl.id, 15, ev["minute"]):
            return None
        facts = {"player": pl.name, "team": self.name(ev["team"]), "fouls": pl.fouls,
                 "minute": ev["minute"] + 1}
        return self._mk(st, ev, "thin_ice", ev["team"], 0.45,
                        f"{pl.name} on thin ice", facts,
                        [("booked_and_fouling",
                          f"already booked, now {pl.fouls} fouls in the match")])

    def flow(self, st: MatchState, ev: dict) -> list[Insight]:
        """Momentum and pressure checks, run once per match minute."""
        out = []
        m = ev["minute"]
        if m < 12 or st.finished:
            return out
        avg10 = XG_PER_TEAM_MINUTE * 10
        for code in (st.home, st.away):
            opp = st.other(code)
            w, wo = st.window_xg(code), st.window_xg(opp)
            if w >= max(0.55, 3.5 * avg10) and wo <= avg10 and \
                    self._ok("momentum", code, 15, m):
                facts = {"team": self.name(code), "xg_last10": _r(w), "opp_xg_last10": _r(wo),
                         "field_tilt_pct": st.field_tilt(code), "minute": m + 1,
                         "typical_xg_10min": _r(avg10)}
                out.append(self._mk(
                    st, ev, "momentum", code, 0.5,
                    f"{facts['team']} turning the screw", facts,
                    [("momentum", f"{facts['xg_last10']} xG in 10 minutes, about "
                      f"{round(w / avg10)}x a typical spell; opponents {facts['opp_xg_last10']}")]))
            t, o = st.teams[code], st.teams[opp]
            expected = st.expected_xg_to_now()
            if m >= 25 and t.xg >= max(0.8, 1.8 * expected) and t.goals <= o.goals \
                    and t.xg - o.xg >= 0.6 and self._ok("pressure", code, 30, m):
                facts = {"team": self.name(code), "team_xg": _r(t.xg), "opp_xg": _r(o.xg),
                         "goals": t.goals, "opp_goals": o.goals, "shots": t.shots,
                         "minute": m + 1, "typical_xg_by_now": _r(expected)}
                out.append(self._mk(
                    st, ev, "pressure", code, 0.55,
                    f"{facts['team']}: lots of chances, no lead", facts,
                    [("xg_gap", f"{facts['team_xg']} xG to {facts['opp_xg']} but "
                      f"{facts['goals']}-{facts['opp_goals']} on goals"),
                     ("above_par", f"a typical side has {facts['typical_xg_by_now']} xG "
                      f"by now")]))
        return out

    def summary(self, st: MatchState, ev: dict, final: bool) -> Insight:
        s = st.score()
        h, a = st.teams[st.home], st.teams[st.away]
        best = max(st.players.values(), key=_rating, default=None)
        facts: dict[str, Any] = {
            "home_team": self.name(st.home), "away_team": self.name(st.away),
            "score": f"{s[st.home]}-{s[st.away]}", "home_xg": _r(h.xg), "away_xg": _r(a.xg),
            "home_shots": h.shots, "away_shots": a.shots,
            "home_possession_pct": st.possession(st.home),
            "away_possession_pct": st.possession(st.away),
        }
        why = []
        if best:
            facts["standout"] = best.name
            facts["standout_line"] = _line(best)
            why.append(("standout", f"standout: {best.name} ({facts['standout_line']})"))
        actual = (s[st.home] > s[st.away]) - (s[st.home] < s[st.away])
        by_xg = (h.xg - a.xg > 0.5) - (a.xg - h.xg > 0.5)
        if actual != by_xg:
            facts["xg_verdict"] = "score flatters" if actual else "deserved more"
            why.append(("xg_disagrees",
                        f"xG says {facts['home_xg']}-{facts['away_xg']}, "
                        f"the scoreline says {facts['score']}"))
        else:
            facts["xg_verdict"] = "fair"
            why.append(("xg_agrees", f"xG {facts['home_xg']}-{facts['away_xg']} backs "
                        f"the scoreline"))
        if final:
            facts["match_state"] = self.match_state(st).replace(" lead ", " won ").replace(
                "level at", "draw")
        kind = "full_time" if final else "half_time"
        title = ("Full time" if final else "Half time") + f": {facts['score']}"
        return self._mk(st, ev, kind, None, 0.8 if final else 0.6, title, facts, why)


def _ord(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _rating(p) -> float:
    return (p.goals * 1.0 + p.assists * 0.7 + p.xg * 0.5 + (p.tackles + p.interceptions) * 0.1
            + p.saves * 0.25 + p.passes_ok * 0.01)


def _line(p) -> str:
    bits = []
    if p.goals:
        bits.append(f"{p.goals} goal" + ("s" if p.goals > 1 else ""))
    if p.assists:
        bits.append(f"{p.assists} assist" + ("s" if p.assists > 1 else ""))
    if p.saves:
        bits.append(f"{p.saves} saves")
    if p.tackles + p.interceptions >= 4:
        bits.append(f"{p.tackles + p.interceptions} tackles+interceptions")
    if not bits:
        bits.append(f"{p.passes_ok}/{p.passes} passes")
    return ", ".join(bits)
