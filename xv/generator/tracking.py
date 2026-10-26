"""Shape engine: synthetic tracking (player and ball positions) from the event stream.

The match engine only knows where the ball is when something happens. This
turns that into positions for all 22 players and the ball, once per second:

  ball      keyframes at every located event (passes add their end point,
            shots fly to goal), linear in between
  players   formation slot (4-3-3) shifted by where the ball is and who has it:
            the block moves up and squeezes toward the ball side, the team in
            possession pushes up and spreads, the team without it drops and
            narrows; role and style tweak it (attacking full-backs push on,
            inverted full-backs tuck in, inside forwards come inside, pressing
            forwards step up); the player on the ball is put on the ball and the
            nearest opponent closes him down; movement is capped at sprint speed
            and gets a little smooth noise

It is a model of team shape, not a physics simulation of real tactics.

Frame: home always attacks left to right (x 0-100, y 0-100, pitch 105 x 68 m).
"""
from __future__ import annotations

import math
import random

XI_ANCHORS = {  # role order in starting_xi(): GK FB CB CB FB DM CM AM W ST W  (team frame)
    0: (6, 50), 1: (27, 88), 2: (21, 63), 3: (21, 37), 4: (27, 12), 5: (38, 50),
    6: (47, 30), 7: (57, 64), 8: (69, 86), 9: (77, 50), 10: (69, 14),
}
LINE_WEIGHT = {"GK": 0.12, "CB": 0.75, "FB": 0.88, "DM": 0.9, "CM": 1.0, "AM": 1.0, "W": 1.0, "ST": 0.9}
MAX_STEP_X = 8.5 / 1.05  # ~8.5 m per second, in pitch units
MAX_STEP_Y = 8.5 / 0.68
POSSESSION_TYPES = {"pass", "dribble", "shot", "corner", "offside"}
REGAIN_TYPES = {"tackle", "interception", "clearance", "save", "block"}


def _abs(team_is_home: bool, x: float, y: float) -> tuple[float, float]:
    return (x, y) if team_is_home else (100 - x, 100 - y)


def ball_keyframes(events: list[dict], home: str) -> dict[int, list[tuple[float, float, float]]]:
    """period -> [(t, bx, by)] in the home-left-to-right frame."""
    keys: dict[int, list] = {1: [(0.0, 50.0, 50.0)], 2: [(0.0, 50.0, 50.0)]}
    for e in events:
        p, t, ty = e["period"], e["t"], e["type"]
        if p not in keys or not e.get("team"):
            continue
        h = e["team"] == home
        if "x" in e:
            last_by = keys[p][-1][2]  # events without a y take the ball's last y
            y = e.get("y", last_by if h else 100 - last_by)
            bx, by = _abs(h, e["x"], y)
            keys[p].append((t, bx, by))
            if "end_x" in e:
                ex, ey = _abs(h, e["end_x"], e.get("end_y", y))
                keys[p].append((t + min(2.5, 0.6 + e.get("length", 15) / 25), ex, ey))
            if ty == "shot":
                gx = 100.0 if h else 0.0
                keys[p].append((t + 0.8, gx, 50 + (by - 50) * 0.15))
        elif ty == "corner":
            keys[p].append((t, 99.5 if h else 0.5, 1.0 if e["seq"] % 2 else 99.0))
        elif ty == "goal":
            keys[p].append((t + 20, 50.0, 50.0))
    for p in keys:
        keys[p].sort(key=lambda k: k[0])
    return keys


def _interp(keys: list[tuple[float, float, float]], t: float, i: int) -> tuple[float, float, int]:
    while i + 1 < len(keys) and keys[i + 1][0] <= t:
        i += 1
    if i + 1 >= len(keys):
        return keys[i][1], keys[i][2], i
    t0, x0, y0 = keys[i]
    t1, x1, y1 = keys[i + 1]
    f = 0 if t1 <= t0 else (t - t0) / (t1 - t0)
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, i


def build_tracking(events: list[dict], players: dict[str, dict], seed: int = 0, hz: int = 1) -> dict:
    """players: id -> {"role", "style", "shirt", "club"}. Returns a compact tracking document."""
    rng = random.Random(seed)
    start = events[0]
    home, away = start["home"], start["away"]
    order: list[str] = list(start["lineups"]["home"]) + list(start["lineups"]["away"])
    order += [e["player_id"] for e in events if e["type"] == "substitution"]  # fixed width frames
    slot: dict[str, int] = {pid: i for i, pid in enumerate(start["lineups"]["home"])}
    slot.update({pid: i for i, pid in enumerate(start["lineups"]["away"])})
    on = set(start["lineups"]["home"]) | set(start["lineups"]["away"])
    phase = {pid: (rng.uniform(0, 6.28), rng.uniform(0, 6.28)) for pid in players}
    keys = ball_keyframes(events, home)
    by_period: dict[int, list[dict]] = {1: [], 2: []}
    for e in events:
        if e["period"] in by_period:
            by_period[e["period"]].append(e)

    frames = []
    pos: dict[str, tuple[float, float]] = {}
    for period in (1, 2):
        evs = by_period[period]
        end = max((e["t"] for e in evs), default=0)
        ki, ei = 0, 0
        poss: str | None = home if period == 1 else away
        actor: tuple[str, float] | None = None
        t = 0.0
        while t <= end:
            # apply events up to t: possession, actor, substitutions, red cards
            while ei < len(evs) and evs[ei]["t"] <= t:
                e = evs[ei]
                ty, team = e["type"], e.get("team")
                if ty in POSSESSION_TYPES and team:
                    poss = team
                elif ty in REGAIN_TYPES and team:
                    poss = team
                elif ty == "foul" and team:
                    poss = away if team == home else home
                if e.get("player_id") and ty in POSSESSION_TYPES | REGAIN_TYPES | {"foul", "aerial"}:
                    actor = (e["player_id"], e["t"])
                if ty == "pass" and e.get("receiver_id") and e["outcome"] == "complete":
                    actor = (e["receiver_id"], e["t"] + 1.5)
                if ty == "substitution":
                    off = e["player_off_id"]
                    on.discard(off)
                    on.add(e["player_id"])
                    slot[e["player_id"]] = slot.get(off, 6)
                    pos[e["player_id"]] = pos.get(off, (50.0, 0.0))
                elif ty == "card" and e.get("card") != "yellow":
                    on.discard(e["player_id"])
                ei += 1
            bx, by, ki = _interp(keys[period], t, ki)
            new: dict[str, tuple[float, float]] = {}
            for pid in on:
                pl = players.get(pid)
                if not pl:
                    continue
                is_home = pl["club"] == home
                # ball in this team's attacking frame
                tbx, tby = (bx, by) if is_home else (100 - bx, 100 - by)
                ax, ay = XI_ANCHORS.get(slot.get(pid, 6), (45, 50))
                role, style = pl["role"], pl["style"]
                in_poss = poss == pl["club"]
                w = LINE_WEIGHT.get(role, 1.0)
                shift = ((tbx - 50) * 0.55 + 7) if in_poss else ((tbx - 50) * 0.5 - 7)
                x = 45 + (ax - 45) * (1.0 if in_poss else 0.82) + shift * w
                spread = 1.12 if in_poss else 0.72
                y = 50 + (ay - 50) * spread + (tby - 50) * (0.18 if in_poss else 0.38)
                if role == "FB" and in_poss:
                    if style == "attacking":
                        x += 9
                    elif style == "inverted":
                        y = 50 + (y - 50) * 0.55
                if role == "W" and style == "inside_forward" and in_poss and tbx > 60:
                    y = 50 + (y - 50) * 0.6
                if role == "ST" and not in_poss and style == "presser":
                    x += 6
                a1, a2 = phase[pid]
                if role == "GK":
                    # on his line while the ball is near his goal; steps up slowly as play moves away
                    x = 2.5 + 0.11 * max(0.0, tbx - 25) + (4 if style == "sweeper" and tbx > 55 else 0)
                    x = min(x, 15.0) + 0.3 * math.sin(t / 11 + a1)
                    y = 50 + max(-9.0, min(9.0, (tby - 50) * 0.22)) + 0.4 * math.sin(t / 13 + a2)
                else:
                    x += 1.6 * math.sin(t / 7 + a1)
                    y += 2.2 * math.sin(t / 9 + a2)
                gx, gy = (x, y) if is_home else (100 - x, 100 - y)
                new[pid] = (gx, gy)
            # the player on the ball is on the ball; the nearest opponent closes him down
            if actor and actor[0] in new and abs(actor[1] - t) <= 2.0 and players[actor[0]]["role"] == "GK":
                # a keeper only goes to the ball inside his own box (saves elsewhere happen on his line)
                own_x = bx if players[actor[0]]["club"] == home else 100 - bx
                if own_x > 16 or not 20 < by < 80:
                    actor = None
            if actor and actor[0] in new and abs(actor[1] - t) <= 2.0:
                new[actor[0]] = (bx, by)
                act_club = players[actor[0]]["club"]
                opp = [p for p in new if players[p]["club"] != act_club and players[p]["role"] != "GK"]
                if opp:
                    near = min(opp, key=lambda p: (new[p][0] - bx) ** 2 + (new[p][1] - by) ** 2)
                    nx, ny = new[near]
                    new[near] = (nx + (bx - nx) * 0.7, ny + (by - ny) * 0.7)
            for pid, (x, y) in new.items():
                on_ball = actor and pid == actor[0] and abs(actor[1] - t) <= 2.0
                if pid in pos and (not on_ball or players[pid]["role"] == "GK"):  # sprint cap (keepers ~6 m/s)
                    px, py = pos[pid]
                    k = 0.7 if players[pid]["role"] == "GK" else 1.0
                    x = px + max(-MAX_STEP_X * k, min(MAX_STEP_X * k, x - px))
                    y = py + max(-MAX_STEP_Y * k, min(MAX_STEP_Y * k, y - py))
                pos[pid] = (max(0.5, min(99.5, x)), max(0.5, min(99.5, y)))
            frame_pos = []
            for pid in order:
                if pid in on and pid in pos:
                    frame_pos += [round(pos[pid][0] * 10), round(pos[pid][1] * 10)]
                else:
                    frame_pos += [-1, -1]
            frames.append([period, round(t, 1), round(bx * 10), round(by * 10),
                           0 if poss == home else 1, frame_pos])
            t += 1.0 / hz
    meta = [{"id": pid, "club": players[pid]["club"], "shirt": players[pid]["shirt"],
             "role": players[pid]["role"], "name": players[pid].get("name", pid)} for pid in order]
    return {"hz": hz, "home": home, "away": away, "players": meta, "frames": frames}


def actions(events: list[dict], home: str) -> list[list]:
    """Compact on-ball actions in the home-left-to-right frame, for the zone views.
    [period, t, side(0 home/1 away), kind, x, y, end_x, end_y, ok, player_id]"""
    out = []
    for e in events:
        ty = e["type"]
        if ty not in ("pass", "shot", "dribble") or "x" not in e:
            continue
        h = e["team"] == home
        x, y = _abs(h, e["x"], e.get("y", 50))
        kind = "cross" if e.get("cross") else "long" if e.get("long") else ty
        if ty == "pass":
            ex, ey = _abs(h, e.get("end_x", e["x"]), e.get("end_y", e.get("y", 50)))
            ok = e["outcome"] == "complete"
        elif ty == "shot":
            ex, ey = (100.0 if h else 0.0), 50.0
            ok = e["outcome"] == "goal"
        else:
            ex, ey, ok = x, y, e["outcome"] == "success"
        out.append([e["period"], e["t"], 0 if h else 1, kind, round(x, 1), round(y, 1),
                    round(ex, 1), round(ey, 1), int(ok), e.get("player_id")])
    return out
