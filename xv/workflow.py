"""The shared live pipeline as a Microsoft Agent Framework workflow.

    ingest -> interpret -> forecast -> explain
    (validate)  (live stats)  (live probabilities)  (insights + reasons)

Outputs per event: a stats snapshot with the current probabilities (when
something countable happened) and zero or more Insights. Narration is per
viewer (persona, language, favourite team, favourite player), so it runs after
the workflow in narrator.Narrator with a cache.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_framework import Executor, WorkflowBuilder, handler

from .agents.context import SeasonContext, load_context
from .agents.insights import Insight, InsightEngine
from .agents.state import REQUIRED_FIELDS, MatchState
from .analytics.model import LiveModel

QUIET_TYPES = {"pass", "tackle", "interception", "dribble", "aerial", "clearance", "block", "physical"}
FORECAST_TRIGGERS = {"goal", "card", "period_start", "period_end", "match_end", "shot"}


@dataclass
class Interpreted:
    event: dict
    snapshot: dict | None
    probs: dict | None = None
    probs_before: dict | None = None


@dataclass
class PipelineOutput:
    event: dict
    snapshot: dict | None
    insights: list[Insight] = field(default_factory=list)
    probs: dict | None = None


class Ingest(Executor):
    """Validates and normalises incoming events (any source: file replay, HTTP, queue)."""

    def __init__(self):
        super().__init__(id="ingest")
        self.last_seq: dict[str, int] = {}
        self.dropped = 0

    @handler(input=dict, output=dict)
    async def on_event(self, ev, ctx):
        if REQUIRED_FIELDS - ev.keys():
            self.dropped += 1
            return
        if ev["seq"] <= self.last_seq.get(ev["match_id"], -1):  # duplicate or out-of-order replay
            self.dropped += 1
            return
        self.last_seq[ev["match_id"]] = ev["seq"]
        await ctx.send_message(ev)


class Interpret(Executor):
    """Keeps the live statistical picture of the match."""

    def __init__(self):
        super().__init__(id="interpret")
        self.state = MatchState()
        self.last_snap_minute = -1

    @handler(input=dict, output=Interpreted)
    async def on_event(self, ev, ctx):
        self.state.apply(ev)
        # a snapshot on every notable event, and at least once per match minute
        quiet = ev["type"] in QUIET_TYPES and ev["minute"] == self.last_snap_minute
        if not quiet:
            self.last_snap_minute = ev["minute"]
        await ctx.send_message(Interpreted(ev, None if quiet else self.state.snapshot()))


class Forecast(Executor):
    """Re-prices the match after every event that can change it."""

    def __init__(self, fixture: dict, interpret: Interpret):
        super().__init__(id="forecast")
        self.model = LiveModel(fixture["rates"]["home"], fixture["rates"]["away"],
                               fixture["home"], fixture["away"], fixture.get("odds"))
        self.interpret = interpret
        self.current = {"minute": 0, **self.model.pre, "why": ["pre-match"]}
        self.last_minute = -1

    @handler(input=Interpreted, output=Interpreted)
    async def on_interpreted(self, msg, ctx):
        st, ev = self.interpret.state, msg.event
        before = self.current
        if st.home and (ev["type"] in FORECAST_TRIGGERS or ev["minute"] != self.last_minute):
            self.last_minute = ev["minute"]
            minute = ev["minute"] + (ev["t"] % 60) / 60
            reds = {c: t.reds for c, t in st.teams.items()}
            xg = {c: t.xg for c, t in st.teams.items()}
            xg10 = {c: st.window_xg(c, 10) for c in st.teams}
            self.current = self.model.update(minute, st.score(), reds, xg,
                                             finished=ev["type"] == "match_end", xg10=xg10)
        msg.probs, msg.probs_before = self.current, before
        if msg.snapshot is not None:
            msg.snapshot["probs"] = self.current
        await ctx.send_message(msg)


class Explain(Executor):
    """Finds the moments that matter and records why."""

    def __init__(self, ctx: SeasonContext, interpret: Interpret, fixture: dict):
        super().__init__(id="explain")
        self.engine = InsightEngine(ctx, fixture)
        self.interpret = interpret

    @handler(input=Interpreted, workflow_output=PipelineOutput)
    async def on_interpreted(self, msg, ctx):
        found = self.engine.on_event(self.interpret.state, msg.event, msg.probs, msg.probs_before)
        await ctx.yield_output(PipelineOutput(msg.event, msg.snapshot, found, msg.probs))


class MatchPipeline:
    def __init__(self, data_dir: Path, fixture: dict, bundle: Path | None = None):
        self.fixture = fixture
        self.ctx = load_context(data_dir, fixture["league"], before_round=fixture["round"],
                                players_json=(bundle / "players.json") if bundle else None)
        self.ingest = Ingest()
        self.interpret = Interpret()
        self.forecast = Forecast(fixture, self.interpret)
        self.explain = Explain(self.ctx, self.interpret, fixture)
        self.workflow = (
            WorkflowBuilder(start_executor=self.ingest, name="xv-match", output_from=[self.explain])
            .add_chain([self.ingest, self.interpret, self.forecast, self.explain])
            .build()
        )

    @property
    def state(self) -> MatchState:
        return self.interpret.state

    async def push(self, ev: dict) -> PipelineOutput | None:
        result = await self.workflow.run(ev)
        outs = result.get_outputs()
        return outs[0] if outs else None
