"""Personalize + narrate: one insight, many audiences and languages.

Two modes:
  template  - deterministic English text built from the insight's own reasons
              (always available, used offline and as the fallback)
  foundry   - a Microsoft Agent Framework agent on a Microsoft Foundry model
              writes the line for the persona and language

Every LLM line passes a grounding check: each number in the output must
appear in the insight's facts or reasons. If not, the template line is used
and the rejection is recorded, so the overlay never shows an invented stat.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from .insights import Insight

LANGUAGES = {"en": "English", "ro": "Romanian", "es": "Spanish", "fr": "French",
             "de": "German", "pt": "Portuguese"}


@dataclass(frozen=True)
class Persona:
    key: str
    label: str
    min_importance: float
    max_words: int
    style: str


PERSONAS = {
    "analyst": Persona(
        "analyst", "Analyst", 0.0, 55,
        "Data-literate analyst. Lead with the numbers (xG, field tilt, shot counts), "
        "explain the tactical meaning in one clause. No hype."),
    "fan": Persona(
        "fan", "Casual fan", 0.55, 28,
        "Casual fan watching on a phone. Plain words, at most one number, explain any "
        "jargon in passing (xG = how likely the chance was to go in). Warm, energetic."),
}


# ---------- grounding ----------
_NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text):
        out.append(float(m.group().replace(",", ".")))
    return out


def allowed_numbers(ins: Insight) -> set[float]:
    pool = json.dumps(ins.facts) + " " + " ".join(w["text"] for w in ins.why + ins.depth) + " " + ins.title
    nums = set(_numbers(pool))
    # percentages may be written as fractions and vice versa; minute may appear as clock
    nums |= {round(n * 100) for n in nums if n < 1} | {ins.minute + 1}
    return nums


def grounding_errors(text: str, ins: Insight) -> list[float]:
    allowed = allowed_numbers(ins)
    bad = []
    for n in _numbers(text):
        if not any(abs(n - a) < 0.006 for a in allowed):
            bad.append(n)
    return bad


_SCORE = re.compile(r"(?<![\d.])(\d+)\s*[-–]\s*(\d+)(?![\d.])")
_EN_WORDS = {"the", "and", "of", "to", "in", "is", "a", "with", "for", "his", "their",
             "from", "now", "after", "has", "have", "this", "that", "on", "at", "by"}
_REPEAT = re.compile(r"(\w{2,8}?)\1{4,}", re.I)


def check_line(text: str, ins: Insight, persona: Persona, lang: str) -> list[str]:
    """Every reason this LLM line should not reach the screen (empty list = OK)."""
    problems = []
    if not text:
        return ["empty"]
    bad = grounding_errors(text, ins)
    if bad:
        problems.append(f"numbers not in facts: {bad}")
    pool = json.dumps(ins.facts) + " " + " ".join(w["text"] for w in ins.why + ins.depth) + " " + ins.title
    scores = {(a, b) for a, b in _SCORE.findall(pool)}
    for a, b in _SCORE.findall(text):
        if (a, b) not in scores:
            problems.append(f"scoreline {a}-{b} not in facts")
    if _REPEAT.search(text):
        problems.append("degenerate repetition")
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) > persona.max_words * 1.8:
        problems.append(f"too long ({len(words)} words)")
    if lang != "en" and words:
        english = sum(w in _EN_WORDS for w in words) / len(words)
        if english > 0.15:
            problems.append("answered in English, not the requested language")
    return problems


# ---------- template narration ----------
def template_line(ins: Insight, persona: Persona) -> str:
    reasons = [w["text"] for w in ins.why]
    if persona.key == "fan":
        lead = ins.title
        return f"{lead}. {reasons[0][0].upper() + reasons[0][1:]}." if reasons else lead
    body = "; ".join(reasons)
    return f"{ins.title}. {body[0].upper() + body[1:]}." if body else ins.title


def relevant(ins: Insight, persona: Persona, favourite: str | None = None) -> bool:
    bump = 0.15 if favourite and ins.team == favourite else 0.0
    return ins.importance + bump >= persona.min_importance


# ---------- LLM narration (Microsoft Agent Framework + Foundry) ----------
INSTRUCTIONS = """You are the on-screen voice of a live football broadcast overlay.
You receive one INSIGHT as JSON: a title, facts (the only numbers you may use) and why
(the reasons it matters). Write ONE line for the given persona and language.
Rules:
- Use only numbers that appear in facts or why. Never add stats, dates or names.
- Explain why the moment matters, not just what happened. If "context" is given, weave in the one\n  season fact that best explains the moment (analysts: one or two).
- If viewer_supports is set, speak to a fan of that club (their joy or worry), still factual.
- Copy numbers exactly as they appear in facts, with digits. Do not round, convert or combine
  them. Write scorelines exactly as given (home team first).
- Write the whole line in the requested language.
- Stay within the word limit. No hashtags, no emojis.
- Output the line only, no quotes or preamble.
All teams and players are fictional."""


def load_env(path: str = ".env") -> None:
    """Minimal .env reader (KEY=value lines); real environment variables win."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def build_credential():
    """FOUNDRY_AUTH=browser: one interactive sign-in, token cached on disk.
    Anything else: DefaultAzureCredential (az login, managed identity on Azure, env vars)."""
    if os.getenv("FOUNDRY_AUTH", "").lower() == "browser":
        from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
        return InteractiveBrowserCredential(
            tenant_id=os.getenv("AZURE_TENANT_ID") or None,
            cache_persistence_options=TokenCachePersistenceOptions(name="xv"))
    from azure.identity import DefaultAzureCredential
    return DefaultAzureCredential()


def build_client():
    """Pick the narration backend from the environment (or .env):

      FOUNDRY_LOCAL_MODEL=phi-4-mini         Foundry Local, on-device, free
      FOUNDRY_PROJECT_ENDPOINT + FOUNDRY_MODEL  Microsoft Foundry in Azure
      neither                                 None -> template narration
    """
    load_env()
    local_model = os.getenv("FOUNDRY_LOCAL_MODEL")
    if local_model:
        from .foundry_local import build_local_client
        return build_local_client(local_model)  # starts the daemon, loads the model
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    model = os.getenv("FOUNDRY_MODEL")
    if not (endpoint and model):
        return None
    from agent_framework.foundry import FoundryChatClient
    client = FoundryChatClient(project_endpoint=endpoint, model=model,
                               credential=build_credential())
    client.backend = f"foundry:{model}"
    return client


_THINK = re.compile(r"<think>.*?</think>", re.S)


def clean_output(text: str) -> str:
    """Drop reasoning blocks, quotes and label prefixes small models sometimes add."""
    text = _THINK.sub("", text or "").strip()
    text = re.sub(r"^(line|output|answer)\s*:\s*", "", text, flags=re.I)
    return text.strip().strip('"“”').strip()


class Narrator:
    def __init__(self, client=None, club_names: dict[str, str] | None = None):
        self.agent = None
        self.backend = "template"
        if client is not None:
            from agent_framework import Agent
            self.agent = Agent(client, INSTRUCTIONS, name="narrator",
                               description="Writes grounded overlay lines per persona and language")
            self.backend = getattr(client, "backend", "foundry")
        self.club_names = club_names or {}
        self.cache: dict[tuple, dict] = {}
        self.rejections = 0
        self.retries = 1

    @property
    def mode(self) -> str:
        return self.backend

    async def narrate(self, ins: Insight, persona: Persona, lang: str = "en",
                      favourite: str | None = None) -> dict:
        key = (ins.id, persona.key, lang, favourite)
        if key in self.cache:
            return self.cache[key]
        fallback = template_line(ins, persona)
        result = {"insight_id": ins.id, "persona": persona.key, "lang": lang,
                  "text": fallback, "source": "template", "grounded": True}
        if self.agent is not None:
            prompt = json.dumps({
                "persona": persona.style, "language": LANGUAGES.get(lang, "English"),
                "max_words": persona.max_words,
                "viewer_supports": self.club_names.get(favourite, favourite) if favourite else None,
                "insight": {"title": ins.title, "facts": ins.facts, "why": ins.why,
                            "context": [d["text"] for d in ins.depth]},
            }, ensure_ascii=False)
            options = {"temperature": 0.3, "max_tokens": 160}
            try:
                # one retry: the checker's objections go back to the writer
                ask, problems, text = prompt, [], ""
                for attempt in range(1 + self.retries):
                    resp = await self.agent.run(ask, options=options)
                    text = clean_output(resp.text)
                    problems = check_line(text, ins, persona, lang)
                    if not problems:
                        result.update(text=text, source=self.backend, attempts=attempt + 1)
                        break
                    ask = (prompt + "\nYour previous line was rejected by the fact checker: "
                           + "; ".join(problems) + ". Write a corrected line.")
                else:
                    self.rejections += 1
                    result.update(grounded=False, rejected_reasons=problems,
                                  rejected_numbers=grounding_errors(text, ins),
                                  rejected_text=text[:400])
            except Exception as exc:  # network, auth, quota: keep the overlay alive
                result.update(error=type(exc).__name__, error_detail=str(exc)[:300])
        elif lang != "en":
            result["note"] = "translation needs the Foundry model; showing English"
        self.cache[key] = result
        return result
