"""Fictional football world: four leagues, their clubs, squads and players.

Everything is invented. Places, clubs and people are built from made-up word
parts so nothing maps to a real club or person. Each league has a personality
(tempo, openness, physicality, home advantage, parity) so league-level
patterns exist for the analysis to find; the app never reads these settings,
it discovers the patterns from the matches.

Each player has a role (GK, CB, FB, DM, CM, AM, W, ST) and a hidden design
style (e.g. a ball-playing or an aerial centre-back). The style shapes the
attributes; the analysis later tries to recover it from the stats alone.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

LEAGUES = [
    # id, name, home advantage, tempo (passes), openness (shots), fouls, cards, strength range
    {"id": "meridian", "name": "Meridian League", "home_adv": 4.0, "tempo": 1.00, "open": 1.00,
     "fouls": 1.00, "cards": 1.00, "strength": (60, 73),
     "clubs": [("Port Aldwyn", "#1f6feb"), ("Fenmoor Town", "#2da44e"),
               ("Caskwell United", "#cf222e"), ("Redhallow", "#a40e26"),
               ("Northmere City", "#58a6ff"), ("Saltgate Albion", "#bf8700"),
               ("Brackenford", "#8250df"), ("Wyvern Park", "#1a7f37"),
               ("Larkmoor Athletic", "#9a6700"), ("Esterby Wanderers", "#0969da")]},
    {"id": "calder", "name": "Calder Coast Premier", "home_adv": 3.0, "tempo": 1.06,
     "open": 1.20, "fouls": 0.88, "cards": 0.85, "strength": (59, 75),
     "clubs": [("Kelmouth", "#d1242f"), ("Gullhaven FC", "#0550ae"),
               ("Marrowick Rovers", "#116329"), ("Sarnfield", "#7d4e00"),
               ("Tolvane City", "#6639ba"), ("Ebbridge United", "#cf222e"),
               ("Quillby Athletic", "#1f6feb"), ("Halvoran", "#953800"),
               ("Drystan Bay", "#0a3069"), ("Corrow Point", "#2da44e")]},
    {"id": "northmarch", "name": "Northmarch Division", "home_adv": 5.0, "tempo": 0.93,
     "open": 0.82, "fouls": 1.22, "cards": 1.45, "strength": (60, 71),
     "clubs": [("Varnholt", "#24292f"), ("Thistlemere", "#8250df"),
               ("Ostrevan FC", "#a40e26"), ("Bramblecote", "#1a7f37"),
               ("Hollowmere Town", "#57606a"), ("Kardrun", "#bc4c00"),
               ("Fellgate United", "#0550ae"), ("Ironvale", "#6e7781"),
               ("Skarn Athletic", "#cf222e"), ("Wrennmoor", "#4d2d00")]},
    {"id": "isles", "name": "Isles Super League", "home_adv": 9.0, "tempo": 0.98,
     "open": 0.95, "fouls": 1.05, "cards": 1.05, "strength": (62, 69),
     "clubs": [("Corvanna", "#bf3989"), ("Oakhaven Rovers", "#116329"),
               ("Seliska", "#0969da"), ("Port Merrow", "#9a6700"),
               ("Tarnby", "#cf222e"), ("Lindqvarr", "#1f6feb"),
               ("Ansel Harbour", "#8250df"), ("Rhosvane", "#2da44e"),
               ("Cairnmouth", "#953800"), ("Elsby Wanderers", "#0a3069")]},
]

_FIRST = ["Aren", "Bastian", "Calder", "Dario", "Elian", "Fennick", "Gavro", "Hollis", "Ilan",
          "Joren", "Kasimir", "Lenno", "Marek", "Nilo", "Orrin", "Pavlo", "Quill", "Rafe",
          "Soren", "Tobin", "Ulric", "Vesko", "Wilder", "Yarin", "Zeno", "Amadi", "Brannoc",
          "Cyrel", "Dmitar", "Emeric", "Faolan", "Gideo", "Hakon", "Ivo", "Jesper", "Kofi",
          "Lucan", "Mateo", "Nikander", "Oskar", "Teo", "Ruan", "Samir", "Idris", "Bram",
          "Kian", "Luka", "Matei", "Noor", "Otto", "Piet", "Remi", "Sven", "Tamas", "Ugo",
          "Vito", "Wim", "Yusuf", "Zoltan", "Anouk"]
_LAST_A = ["Abel", "Bram", "Corr", "Dal", "Ever", "Fal", "Gorm", "Hal", "Ister", "Jann", "Kell",
           "Lorr", "Mard", "Norr", "Ost", "Pell", "Quen", "Rask", "Sav", "Tarr", "Ulv", "Vann",
           "Wess", "Yor", "Zell", "Brisk", "Cald", "Dun", "Esk", "Grav", "Hask", "Morv"]
_LAST_B = ["ane", "ard", "berg", "ec", "enko", "ford", "gaard", "holm", "ich", "ino", "iak",
           "lund", "mann", "oni", "ovic", "ridge", "sen", "son", "ton", "uzzi", "vik", "well",
           "wick", "escu", "ides", "oglu"]

# role -> squad size; the 4-3-3 starting slots
SQUAD = {"GK": 2, "CB": 4, "FB": 4, "DM": 2, "CM": 3, "AM": 2, "W": 4, "ST": 3}
XI_SLOTS = ["GK", "FB", "CB", "CB", "FB", "DM", "CM", "AM", "W", "ST", "W"]
ROLE_LINE = {"GK": "GK", "CB": "DF", "FB": "DF", "DM": "MF", "CM": "MF", "AM": "MF",
             "W": "FW", "ST": "FW"}

# hidden design styles per role: attribute nudges (added to the role baseline)
STYLES = {
    "GK": {"shot_stopper": {"goalkeeping": 6}, "sweeper": {"passing": 12, "goalkeeping": -2}},
    "CB": {"ball_playing": {"passing": 10, "vision": 6, "aerial": -4},
           "stopper": {"tackling": 10, "positioning": 3, "discipline": -10},
           "aerial": {"aerial": 14, "positioning": 4, "passing": -6}},
    "FB": {"attacking": {"crossing": 12, "dribbling": 8, "pace": 6, "tackling": -6},
           "defensive": {"tackling": 9, "positioning": 8, "crossing": -6},
           "inverted": {"passing": 10, "vision": 6, "crossing": -4}},
    "DM": {"anchor": {"positioning": 12, "passing": 4, "finishing": -8},
           "destroyer": {"tackling": 14, "discipline": -12},
           "regista": {"passing": 12, "vision": 8, "tackling": -6}},
    "CM": {"box_to_box": {"stamina": 10, "tackling": 5, "finishing": 6},
           "playmaker": {"vision": 12, "passing": 8, "tackling": -6},
           "carrier": {"dribbling": 14, "pace": 6}},
    "AM": {"playmaker": {"vision": 14, "passing": 6}, "shadow_striker": {"finishing": 12, "dribbling": 4}},
    "W": {"touchline": {"crossing": 14, "pace": 8, "finishing": -6},
          "inside_forward": {"finishing": 10, "dribbling": 10, "crossing": -8}},
    "ST": {"poacher": {"finishing": 12, "passing": -8, "aerial": -2},
           "target": {"aerial": 16, "finishing": 2, "pace": -8},
           "complete": {"finishing": 6, "vision": 8, "dribbling": 6},
           "presser": {"tackling": 14, "stamina": 10, "finishing": -4}},
}

# role baselines relative to the player's quality s (0-100)
_BASE = {
    "GK": dict(finishing=-55, passing=-15, vision=-30, dribbling=-40, crossing=-50, tackling=-40,
               positioning=-20, aerial=-10, pace=-20, goalkeeping=2),
    "CB": dict(finishing=-30, passing=-6, vision=-15, dribbling=-20, crossing=-25, tackling=4,
               positioning=3, aerial=4, pace=-6, goalkeeping=-60),
    "FB": dict(finishing=-25, passing=-4, vision=-8, dribbling=-6, crossing=0, tackling=-2,
               positioning=-3, aerial=-10, pace=4, goalkeeping=-60),
    "DM": dict(finishing=-18, passing=2, vision=-4, dribbling=-10, crossing=-20, tackling=2,
               positioning=4, aerial=-6, pace=-6, goalkeeping=-60),
    "CM": dict(finishing=-12, passing=4, vision=2, dribbling=-4, crossing=-12, tackling=-6,
               positioning=-4, aerial=-10, pace=-2, goalkeeping=-60),
    "AM": dict(finishing=-4, passing=4, vision=8, dribbling=4, crossing=-8, tackling=-20,
               positioning=-14, aerial=-16, pace=0, goalkeeping=-60),
    "W": dict(finishing=-4, passing=-4, vision=0, dribbling=8, crossing=4, tackling=-22,
              positioning=-16, aerial=-18, pace=8, goalkeeping=-60),
    "ST": dict(finishing=6, passing=-8, vision=-4, dribbling=0, crossing=-14, tackling=-26,
               positioning=-20, aerial=0, pace=2, goalkeeping=-60),
}
ATTRS = list(_BASE["CB"].keys())


@dataclass
class Player:
    id: str
    name: str
    club: str
    league: str
    role: str
    style: str  # hidden design style (for validation only)
    shirt: int
    age: int
    height_cm: int
    foot: str
    finishing: int
    passing: int
    vision: int
    dribbling: int
    crossing: int
    tackling: int
    positioning: int
    aerial: int
    pace: int
    goalkeeping: int
    discipline: int
    stamina: int

    @property
    def position(self) -> str:  # line: GK / DF / MF / FW
        return ROLE_LINE[self.role]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Club:
    code: str
    name: str
    colour: str
    strength: int
    league: str
    players: list[Player] = field(default_factory=list)

    def starting_xi(self) -> list[Player]:
        xi: list[Player] = []
        for role in XI_SLOTS:
            pool = [p for p in self.players if p.role == role and p not in xi]
            pool.sort(key=_overall, reverse=True)
            if pool:
                xi.append(pool[0])
        return xi

    def bench(self) -> list[Player]:
        ids = {p.id for p in self.starting_xi()}
        return [p for p in self.players if p.id not in ids]

    def to_dict(self) -> dict:
        return {"code": self.code, "name": self.name, "colour": self.colour,
                "strength": self.strength, "league": self.league,
                "players": [p.to_dict() for p in self.players]}


def _overall(p: Player) -> float:
    key = {"GK": ["goalkeeping"], "CB": ["tackling", "positioning", "aerial", "passing"],
           "FB": ["tackling", "crossing", "pace", "passing"], "DM": ["positioning", "tackling", "passing"],
           "CM": ["passing", "vision", "tackling"], "AM": ["vision", "passing", "finishing", "dribbling"],
           "W": ["dribbling", "pace", "crossing", "finishing"], "ST": ["finishing", "aerial", "dribbling"]}
    return sum(getattr(p, a) for a in key[p.role]) / len(key[p.role])


def _clamp(v: float) -> int:
    return max(15, min(99, round(v)))


def club_code(name: str, used: set[str]) -> str:
    letters = "".join(w[0] for w in name.split()[:3]).upper()
    base = (name.replace(" ", "")[:3]).upper()
    for cand in (base, letters + name[-1].upper(), base[:2] + name[-1].upper()):
        if len(cand) == 3 and cand not in used:
            used.add(cand)
            return cand
    i = 1
    while f"{base[:2]}{i}" in used:
        i += 1
    used.add(f"{base[:2]}{i}")
    return f"{base[:2]}{i}"


def _player(rng: random.Random, club: Club, role: str, shirt: int, quality: float,
            used: set[str]) -> Player:
    while True:
        name = f"{rng.choice(_FIRST)} {rng.choice(_LAST_A)}{rng.choice(_LAST_B)}"
        if name not in used:
            used.add(name)
            break
    style = rng.choice(list(STYLES[role]))
    nudge = STYLES[role][style]
    attrs = {a: _clamp(rng.gauss(quality + _BASE[role][a] + nudge.get(a, 0), 5)) for a in ATTRS}
    height = {"GK": 190, "CB": 188, "ST": 183, "FB": 178, "W": 176, "AM": 176}.get(role, 180)
    height += 6 if style in ("aerial", "target") else 0
    return Player(
        id=f"{club.code}-{shirt:02d}", name=name, club=club.code, league=club.league, role=role,
        style=style, shirt=shirt, age=max(17, min(37, round(rng.gauss(26, 4)))),
        height_cm=round(rng.gauss(height, 4)), foot=rng.choice(["R", "R", "R", "L"]),
        discipline=_clamp(rng.gauss(65 + nudge.get("discipline", 0), 12)),
        stamina=_clamp(rng.gauss(72 + nudge.get("stamina", 0), 9)),
        **{a: v for a, v in attrs.items()},
    )


def build_world(seed: int = 2026) -> dict[str, dict]:
    """{league id: {"league": settings, "clubs": {code: Club}}}. Same seed, same world."""
    rng = random.Random(seed)
    used_names: set[str] = set()
    used_codes: set[str] = set()
    world = {}
    for lg in LEAGUES:
        lo, hi = lg["strength"]
        n = len(lg["clubs"])
        clubs = {}
        for i, (name, colour) in enumerate(lg["clubs"]):
            strength = round(hi - (hi - lo) * i / (n - 1) + rng.uniform(-1.5, 1.5))
            club = Club(code=club_code(name, used_codes), name=name, colour=colour,
                        strength=strength, league=lg["id"])
            shirt = 1
            for role, k in SQUAD.items():
                for j in range(k):
                    q = strength + (2 if j < 2 else -4) + rng.uniform(-4, 3)
                    club.players.append(_player(rng, club, role, shirt, q, used_names))
                    shirt += 1
            clubs[club.code] = club
        world[lg["id"]] = {"league": {k: v for k, v in lg.items() if k != "clubs"},
                           "clubs": clubs}
    return world


def round_robin(codes: list[str], seed: int = 2026) -> list[list[tuple[str, str]]]:
    """Double round robin (circle method). Returns rounds of (home, away)."""
    rng = random.Random(seed)
    teams = codes[:]
    rng.shuffle(teams)
    n = len(teams)
    half = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = teams[i], teams[n - 1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        half.append(pairs)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return half + [[(b, a) for a, b in rnd] for rnd in half]
