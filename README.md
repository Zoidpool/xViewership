# xV: expected Viewership

*The game beyond the scoreline.*

Entry for the Microsoft x Premier League **Inside the Game** hackathon
(challenge: *The Synthetic Match Insights Engine*).

xV turns a stream of synthetic match events into explainable match
intelligence: live stats, insight cards that say *why* a moment matters, a win
probability that re-prices the match after every event, and a scouting layer
(percentiles, archetypes, radars, scatter maps, rankings, team comparisons,
league observations) that gives those moments their context. Each line is
rewritten for the viewer: an analyst or a casual fan, neutral or supporting a
side, following a favourite player, in English, Romanian, Spanish, French,
German or Portuguese.

**Everything is synthetic.** Four fictional leagues, 40 clubs, 960 players,
340 played matches and their market prices are generated. There are no real
clubs, players, logos or scraped data.

## What's in it

| View | What it shows |
|---|---|
| **Live match** | Score bug and live win probability (home/draw/away) re-priced after every event; a chart of how the match moved against the pre-match market; match stats; insight cards with "Why?" (evidence + reasons); toasts for big moments; follow-a-player panel (this match + season percentiles) |
| **Players** | Per-90 values for 55+ stats, percentiles against the same role (in the league or across all four), group averages, archetype scores, xV rating with its ranking factors, rating by round, strengths and weaknesses, and a radar with stats you choose |
| **Compare** | Player v player (overlaid radar, every stat with percentiles), team v team (every measure with league ranks) |
| **Scatter** | Any stat against any stat, for players by role or for teams, with averages and labelled outliers |
| **Rankings** | Leaderboards by role, sortable by any stat, coloured by percentile |
| **Teams** | Tables with expected points, form, team profile with ranks, xG match by match |
| **Leagues & probabilities** | Which league is most likely to see what (with 90% ranges, clear v lean), where results ran away from the market's prices, model v market evaluation, next round priced by both |

### Positions, zones and heatmaps
A **shape engine** (`generator/tracking.py`) turns each match's events into synthetic tracking: every player and the ball, once per second.
- **How players move:**
  - Each player starts from a 4-3-3 slot.
  - The block shifts and squeezes toward the ball. The team in possession pushes up and spreads; the team without it drops and narrows.
  - Role and style adjust this: attacking full-backs push on, inverted full-backs tuck in, inside forwards come inside, pressing forwards step up.
  - The player on the ball is on the ball, and the nearest opponent closes him down.
- **Realism checks:** movement is capped at sprint speed, players average about 2.2 m/s (about 11.8 km a match), and roles sit in sensible bands.
- It's a model of team shape, not a physics simulation.

On top of it (`analytics/zones.py`):
- **Live 2D pitch:** 22 numbered players and the ball, with overlays for:
  - thirds and the left/centre/right attacking lanes, labelled with the share of final-third entries,
  - half-spaces (five lanes),
  - possession territory by square (12 × 8),
  - all players' occupancy by square,
  - the followed player's heatmap.
- **Live zone panel:** where passes are played (six bands), entries by lane and half-space, possession by third, and territory. It can be filtered to the whole match, either half, or the last 15 minutes.
- **Players:**
  - season heatmaps, both a smooth heatmap and the squares occupied, with the average position,
  - for the followed player, the same two views for this match.
- **Teams (season):**
  - pass bands against the league average,
  - entries by lane and half-space,
  - possession by third and territory,
  - assist areas and assist types, scoring and conceding.

### Roles and archetypes
Defenders split into **centre-backs and full-backs**, midfield into **defensive, central and attacking**, attack into **wingers and strikers**:

| Role | Archetypes |
|---|---|
| Goalkeeper | shot-stopper, sweeper-keeper |
| Centre-back | ball-playing, stopper, aerial |
| Full-back | attacking, defensive, inverted |
| Defensive midfielder | anchor, ball-winner, deep-lying playmaker |
| Central midfielder | box-to-box, playmaker, ball-carrier |
| Attacking midfielder | creative No.10, shadow striker |
| Winger | touchline, inside forward |
| Striker | poacher, target, complete, pressing forward |

An archetype score is a weighted mean of the player's percentiles. Each generated player has a hidden design style, and the detector recovers it for **60%** of regular players. Guessing would get about 37%.

### Fair comparison rules
- Players are compared within their role.
- There are two scopes: their own league, and all four leagues.
- The pool is players above a minutes bar of 60% of the minutes their team could have played. The bar grows with the season and is never a fixed count.
- Percentages need a minimum number of attempts.
- **Percentiles** are inclusive percentile ranks: the best in the group is 100, the worst 0, and "92%" reads as "better than 92% of the group". The top 1% (99th percentile and up) is marked in gold.

## How it works

```
synthetic events --> Ingest --> Interpret --> Forecast --> Explain --> narrator agent --> fact-checker --> overlay
                     (validate)  (live stats)   (live         (insights        (persona, team,     (numbers, score,
                                                probability)   + reasons)       language)           language, length)
```

- **Microsoft Agent Framework:**
  - Ingest, Interpret, Forecast and Explain are `Executor`s in one `WorkflowBuilder` workflow.
  - The narrator is an Agent Framework `Agent`.
- **Microsoft Foundry Local:**
  - The narrator's model, Qwen2.5-7B, runs on-device: free, private, and about 1 second per line on a consumer GPU.
  - The same code runs on cloud **Microsoft Foundry** if you set a project endpoint instead.
- **Fact-checker** (`check_line`): a model-written line is rejected if:
  - it contains a number or scoreline not in the evidence,
  - it repeats itself or runs over length,
  - it answers in English when another language was asked for.

  A rejected line is sent back once with the objections. If the rewrite also fails, the deterministic template line is shown.
- **Live probability** (`analytics/model.py`):
  - **Before kick-off:** a Poisson team-rating model (attack × defence × home edge, fitted on goals blended with xG) with a Dixon-Coles low-score correction.
  - **After every event:** the remaining goals are re-estimated from the minutes left, red cards, the game state, and live xG blended with the prior. The result is combined with the current score.
- **Synthetic market:** a sharp bookmaker that knows the true strengths, adds noise and a margin; xV removes the margin with the power method.
  - Walk-forward over 280 matches, the market prices better than the model: log-loss **0.952 v 0.982**.
  - That is what happens with real closing lines too. xV uses its model to *explain* how a match moves, not to beat anyone.
  - This is probability, not betting advice.

### Synthetic data quality
`python -m xv.generator.validate` simulates matches in all four leagues and checks 19 per-match averages against broad top-flight ranges, including goals, xG, shots, passes, crosses, dribbles, aerial duels, cards, home wins and draws. All 19 are in range.

The leagues have their own character, which the app finds on its own:

| League | Character |
|---|---|
| Calder Coast Premier | open and high scoring |
| Northmarch Division | tight and physical |
| Isles Super League | big home edge |
| Meridian League | balanced |

Players get the events of a real data feed:
- passes with length, difficulty and receiver,
- crosses, long balls, key passes and xA,
- dribbles, aerial duels, tackles, interceptions, clearances and blocks,
- shots with xG, xG on target and shot speed,
- saves, cards and offsides,
- distance covered, top speed and sprints.

## Run it (Windows, free)

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m xv.generator.season      # synthetic world -> data/
.venv\Scripts\python -m xv.build                 # analysis bundle -> docs/data/
.venv\Scripts\python -m xv.server                # http://127.0.0.1:5065 (live pipeline)
.venv\Scripts\python -m xv.demo --why --seed auto  # the same match in the terminal
.venv\Scripts\python -m pytest -q
```

To turn on the narrator agent:

```
winget install Microsoft.FoundryLocal
foundry model download qwen2.5-7b
copy .env.example .env                              # FOUNDRY_LOCAL_MODEL=qwen2.5-7b
.venv\Scripts\python -m xv.check_foundry         # sample lines, latency, rejections
```

`agents/foundry_local.py` starts Foundry Local and loads the model with the
`foundry` CLI, then points Agent Framework's OpenAI-compatible client at it.
The `foundry-local-sdk` 0.5 that `agent-framework-foundry-local` pins still
calls `foundry service`, which Foundry Local 0.12 renamed to `foundry server`.

### GitHub Pages
`docs/` is the whole app. With no server behind it, the page plays
`docs/replay.json`, a recorded run of the live pipeline with every line
pre-narrated by the agent. Rebuild it with:

```
.venv\Scripts\python -m xv.export_replay
```

Avoid port 5060: Chrome blocks it (it's the SIP port).
