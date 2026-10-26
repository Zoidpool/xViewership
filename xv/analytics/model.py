"""Match probabilities: team ratings, pre-match prices, synthetic market, live updates.

Pre-match: a Poisson team-rating model (attack x defence x home edge) fitted per
league on a blend of goals and xG, with a pull towards average while samples
are small. Scorelines come from the two expected-goal rates (Dixon-Coles
low-score correction), giving home/draw/away, over 2.5 and both teams to score.

Market: the synthetic bookmaker's prices with the margin removed (power method
for 1X2, proportional for two-way markets).

Live: the remaining expected goals are re-estimated after every event from the
pre-match rates, the minutes left, red cards, the game state, and how the match
is actually going (live xG blended with the prior). Outcome probabilities then
combine the current score with the scorelines still possible.

Probability, not betting advice: no stakes, no value calls; the point is to
show how likely each outcome is and how events move it.
"""
from __future__ import annotations

import math
from collections import defaultdict

XG_WEIGHT = 0.5      # blend of goals and xG when rating teams
SHRINK = 4.0         # pseudo-matches of "average" in each rating
RHO = -0.08          # Dixon-Coles low-score correction


def pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def grid(lh: float, la: float, n: int = 10, rho: float = RHO) -> list[list[float]]:
    g = [[pmf(i, lh) * pmf(j, la) for j in range(n)] for i in range(n)]
    if rho:
        g[0][0] *= 1 - lh * la * rho
        g[0][1] *= 1 + lh * rho
        g[1][0] *= 1 + la * rho
        g[1][1] *= 1 - rho
    s = sum(map(sum, g))
    return [[v / s for v in row] for row in g]


def outcome_probs(lh: float, la: float, hg: int = 0, ag: int = 0, rho: float = RHO) -> dict:
    """Final-result probabilities given the current score and remaining goal rates."""
    g = grid(max(lh, 1e-6), max(la, 1e-6), rho=rho if hg == ag == 0 else 0.0)
    n = len(g)
    p = defaultdict(float)
    for i in range(n):
        for j in range(n):
            H, A, v = hg + i, ag + j, g[i][j]
            p["home"] += v * (H > A)
            p["draw"] += v * (H == A)
            p["away"] += v * (H < A)
            p["over25"] += v * (H + A > 2)
            p["btts"] += v * (H > 0 and A > 0)
    return {k: round(v, 4) for k, v in p.items()}


# ---------- market ----------
def devig_power(odds: list[float]) -> list[float]:
    q = [1 / o for o in odds]
    lo, hi = 1.0, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        if sum(x ** k for x in q) > 1:
            lo = k
        else:
            hi = k
    p = [x ** k for x in q]
    s = sum(p)
    return [v / s for v in p]


def devig_two(odds: list[float]) -> float:
    a, b = 1 / odds[0], 1 / odds[1]
    return a / (a + b)


def market_probs(market: dict) -> dict:
    h, d, a = devig_power(market["1x2"])
    return {"home": round(h, 4), "draw": round(d, 4), "away": round(a, 4),
            "over25": round(devig_two(market["ou25"]), 4), "btts": round(devig_two(market["btts"]), 4),
            "margin_1x2": round(sum(1 / o for o in market["1x2"]) - 1, 4)}


# ---------- team ratings ----------
class Ratings:
    def __init__(self, league: str, att: dict, dfn: dict, home: float, base: float):
        self.league, self.att, self.dfn, self.home, self.base = league, att, dfn, home, base

    def rates(self, h: str, a: str) -> tuple[float, float]:
        lh = self.base * self.home * self.att.get(h, 1) * self.dfn.get(a, 1)
        la = self.base / self.home * self.att.get(a, 1) * self.dfn.get(h, 1)
        return lh, la

    def to_dict(self) -> dict:
        return {"home_edge": round(self.home, 3), "base_goals": round(self.base, 3),
                "attack": {k: round(v, 3) for k, v in self.att.items()},
                "defence": {k: round(v, 3) for k, v in self.dfn.items()}}


def fit_ratings(league: str, rows: list[dict], clubs: list[str]) -> Ratings:
    """rows: {home, away, hg, ag, hxg, axg}. Multiplicative Poisson fit by alternating updates."""
    if not rows:
        return Ratings(league, {c: 1.0 for c in clubs}, {c: 1.0 for c in clubs}, 1.15, 1.35)
    sc = lambda g, xg: (1 - XG_WEIGHT) * g + XG_WEIGHT * xg
    obs = [(r["home"], r["away"], sc(r["hg"], r["hxg"]), sc(r["ag"], r["axg"])) for r in rows]
    base = sum(o[2] + o[3] for o in obs) / (2 * len(obs))
    att = {c: 1.0 for c in clubs}
    dfn = {c: 1.0 for c in clubs}
    home = max(1.0, sum(o[2] for o in obs) / max(1e-6, sum(o[3] for o in obs))) ** 0.5
    for _ in range(40):
        for c in clubs:
            num = SHRINK * 1.0
            den = SHRINK * 1.0
            for h, a, gh, ga in obs:
                if h == c:
                    num += gh
                    den += base * home * dfn[a]
                elif a == c:
                    num += ga
                    den += base / home * dfn[h]
            att[c] = num / den
        for c in clubs:
            num = SHRINK * 1.0
            den = SHRINK * 1.0
            for h, a, gh, ga in obs:
                if h == c:
                    num += ga
                    den += base / home * att[a]
                elif a == c:
                    num += gh
                    den += base * home * att[h]
            dfn[c] = num / den
        hs = sum(gh for _, _, gh, _ in obs) / max(1e-6, sum(base * att[h] * dfn[a] for h, a, _, _ in obs))
        as_ = sum(ga for _, _, _, ga in obs) / max(1e-6, sum(base * att[a] * dfn[h] for h, a, _, _ in obs))
        home = max(1.0, (hs / as_) ** 0.5)
    return Ratings(league, att, dfn, home, base)


def log_loss(p: dict, outcome: str) -> float:
    return -math.log(max(1e-9, p[outcome]))


def walk_forward(index: list[dict], team_xg: dict, clubs_by_league: dict, start_round: int = 4) -> list[dict]:
    """Model probabilities for each played match using only earlier rounds."""
    out = []
    by_league = defaultdict(list)
    for m in index:
        by_league[m["league"]].append(m)
    for lg, ms in by_league.items():
        rounds = sorted({m["round"] for m in ms})
        for r in rounds:
            past = [m for m in ms if m["round"] < r and "home_goals" in m]
            if r < start_round:
                continue
            rows = [{"home": m["home"], "away": m["away"], "hg": m["home_goals"], "ag": m["away_goals"],
                     "hxg": team_xg[m["match_id"]][m["home"]], "axg": team_xg[m["match_id"]][m["away"]]}
                    for m in past]
            rt = fit_ratings(lg, rows, clubs_by_league[lg])
            for m in ms:
                if m["round"] == r and "home_goals" in m:
                    lh, la = rt.rates(m["home"], m["away"])
                    out.append({"match_id": m["match_id"], "league": lg, "round": r,
                                "model": outcome_probs(lh, la), "market": market_probs(m["market"]),
                                "result": "home" if m["home_goals"] > m["away_goals"] else
                                "draw" if m["home_goals"] == m["away_goals"] else "away",
                                "goals": m["home_goals"] + m["away_goals"],
                                "btts": m["home_goals"] > 0 and m["away_goals"] > 0})
    return out


# ---------- live ----------
class LiveModel:
    """Re-estimates the remaining goals after every event and returns probabilities."""

    def __init__(self, lh: float, la: float, home: str, away: str, market: dict | None = None):
        self.lh, self.la, self.home, self.away = lh, la, home, away
        self.pre = outcome_probs(lh, la)
        self.market = market_probs(market) if market else None
        self.history: list[dict] = []

    def update(self, minute: float, score: dict, reds: dict, xg: dict, finished: bool = False,
               xg10: dict | None = None) -> dict:
        hg, ag = score[self.home], score[self.away]
        if finished:
            res = "home" if hg > ag else "draw" if hg == ag else "away"
            p = {"home": float(res == "home"), "draw": float(res == "draw"), "away": float(res == "away"),
                 "over25": float(hg + ag > 2), "btts": float(hg > 0 and ag > 0)}
            snap = {"minute": minute, **p, "rem_home": 0.0, "rem_away": 0.0, "why": ["full time"]}
            self.history.append(snap)
            return snap
        played = max(0.0, min(minute, 93.0))
        left = max(0.0, 93.0 - played) / 93.0  # ~3 minutes of stoppage on average
        why = []
        mult = {}
        for side, lam, own, opp in ((self.home, self.lh, "home", "away"), (self.away, self.la, "away", "home")):
            m = 1.0
            # live intensity: observed xG versus what the prior expected so far, shrunk to 1
            exp_so_far = lam * played / 93.0
            if exp_so_far > 0.05:
                k = 0.6  # prior weight in "expected so far" units
                ratio = (xg[side] + k * exp_so_far) / ((1 + k) * exp_so_far)
                ratio = max(0.6, min(1.7, ratio))
                if abs(ratio - 1) >= 0.15:
                    why.append(f"{'home' if side == self.home else 'away'} chances running at "
                               f"{ratio:.2f}x the pre-match rate")
                m *= ratio
            m *= 0.72 ** reds[side] * 1.18 ** reds[self.away if side == self.home else self.home]
            diff = (hg - ag) if side == self.home else (ag - hg)
            if played >= 60 and diff < 0:
                m *= 1.12
            elif played >= 60 and diff > 0:
                m *= 0.9
            mult[side] = m
        if reds[self.home] or reds[self.away]:
            why.append("red card changes the remaining rates")
        # momentum: the last 10 minutes' chances raise or lower the rate for the next 10
        near = min(left, 10 / 93)
        mom = {}
        for side, lam in ((self.home, self.lh), (self.away, self.la)):
            exp10 = lam * 10 / 93
            recent = (xg10 or {}).get(side)
            if recent is None or played < 5:
                mom[side] = 1.0
                continue
            mom[side] = max(0.8, min(1.45, 1 + 0.6 * (recent - exp10) / (exp10 + 0.15)))
            if abs(mom[side] - 1) >= 0.12:
                why.append(f"{'home' if side == self.home else 'away'} pressure: {recent:.2f} xG in "
                           f"the last 10 minutes")
        rh = self.lh * mult[self.home] * ((left - near) + near * mom[self.home])
        ra = self.la * mult[self.away] * ((left - near) + near * mom[self.away])
        p = outcome_probs(rh, ra, hg, ag)
        snap = {"minute": round(minute, 1), **p, "rem_home": round(rh, 3), "rem_away": round(ra, 3),
                "why": why}
        self.history.append(snap)
        return snap
