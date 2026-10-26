# Submission draft: xV

## Pitch (paste into the form)

**What it is.** xV turns a stream of football match events into
intelligence that says why a moment matters. It has two halves:

- **Live:** stats, a win probability that re-prices the match after every event, and insight cards with their evidence one click away.
- **Context:** a scouting layer (percentiles, player archetypes, radars, scatter maps, rankings, team and league comparisons) that tells you how unusual that striker, that team, or that league really is.

One pipeline serves an analyst and a casual fan, neutral or supporting a side, following a favourite player, in six languages.

**The problem.** Live graphics show numbers casual fans skip, and AI
commentary nobody can check. Studio and streaming need lines that are quick to
read, fit the viewer, and can be trusted on air. And "a goal" means more when
you know the scorer is a 92nd-percentile shooter, the goal took his side's win
chance from 38% to 73%, and his league is the one where comebacks are most
likely.

**How it works.**
1. **Ingest.** Events are validated; duplicates and out-of-order replays are dropped.
2. **Interpret.** Live team and player statistics: xG, possession, field tilt, 10-minute momentum, player lines.
3. **Forecast.** A Poisson team-rating model prices the match before kick-off, then re-estimates the remaining goals after every event from the minutes left, red cards, game state and live xG. A synthetic market, with its margin removed, is the benchmark.
4. **Explain.** Detectors find the moments that matter: goals with their win-probability swing and the scorer's archetype and percentile, momentum, pressure without reward, big saves and misses, red cards, probability drift, and the half-time and full-time xG verdict. Every insight carries its evidence and its reasons.
5. **Personalize.** A narrator agent writes each line for the viewer. A fact-checker rejects any line with a number or scoreline not in the evidence, a repetitive line, or one in the wrong language. It sends rejected lines back once, then falls back to a template. Unverified claims never reach the screen.
6. **Render.** A print-style overlay, ink on paper:
   - a live 2D pitch with all 22 players, from synthetic tracking built by a shape engine;
   - zone overlays: thirds and attacking lanes, half-spaces, and a 12 × 8 grid of territory and occupancy;
   - heatmaps for any player, smooth and by square;
   - the scouting views.

**Synthetic data.**
- **The world:** four fictional leagues, 40 clubs and 960 players, each with a role and a hidden playing style. A possession-chain match engine emits the events of a real feed: passes with length, difficulty and receiver, crosses, dribbles, aerial duels, defensive actions, shots with xG, xGOT and speed, and tracking-style distance and top speed.
- **Realism:** all 19 checked per-match averages sit inside normal top-flight ranges.
- **Hidden styles:** the archetype detector recovers players' hidden styles 60% of the time; guessing would get about 37%.
- **League character:** the leagues differ (open, physical, home-heavy), and the app finds that on its own.
- **No real data** of any kind is used.

**Microsoft technologies.**
- **Microsoft Agent Framework:** the four-stage workflow (WorkflowBuilder + Executors), and the narrator Agent.
- **Microsoft Foundry Local:** the narrator's model runs on-device, at no cloud cost, with no data leaving the machine. The same code targets a cloud Foundry project via one setting.
- **GitHub:** public repo, and GitHub Pages hosting the app with a recorded replay of the pipeline.

**Honest results.**
- On 280 synthetic matches priced walk-forward, the market beats xV's model (log-loss 0.952 v 0.982), just as real closing lines beat public models.
- xV's probability is there to explain how a match moves, not to beat anyone. It is probability, not betting advice.

## Demo video script (under 2:00)

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:10 | Live tab, kick-off, players moving on the 2D pitch | "This is xV. It tells you why a moment matters, for whoever is watching." |
| (optional, cut elsewhere) | Switch the pitch view: thirds & lanes, half-spaces, territory grid; follow a player's heatmap | "Every player is tracked: the thirds, the lanes, the half-spaces, and who owns which square." |
| 0:10–0:35 | 300x speed: goal toast, probability bar jumps, chart line moves | "An Agent Framework workflow ingests synthetic events, keeps the stats, and re-prices the match after every event. This goal took Fenmoor from 38 to 73 percent." |
| 0:35–0:50 | Open "Why?" on the goal card | "Every card shows its evidence: the win-probability swing, the scorer's archetype, his percentile among the league's full-backs." |
| 0:50–1:05 | Switch to Casual fan + Romanian, follow a player | "Same match, different viewer. The narrator runs on Foundry Local, on this PC. A fact-checker rejects any number that isn't in the evidence." |
| 1:05–1:25 | Players tab: radar with chosen stats, percentiles, ranking factors; Compare | "Behind the live layer: 960 players compared within their role, with archetypes, radars and the factors behind every rating." |
| 1:25–1:45 | Scatter, then Leagues: "most likely" observations and model v market | "Scatter maps, team comparisons, and which league is most likely to see what. The market still beats our model, and we say so." |
| 1:45–2:00 | GitHub Pages URL + repo | "Everything is synthetic, and everything runs free. Try it at the link." |

Rules: under 2 minutes, show it running, no copyrighted music, upload to YouTube or Vimeo.
