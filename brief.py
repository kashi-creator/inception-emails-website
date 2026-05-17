"""Deterministic Intake Brief + one-click deck-prompt generator.

Pure stdlib, zero network, zero API cost. Turns the 9-field pre-sales
intake into (a) a structured Intake Brief MD an operator can read in 60s,
and (b) a self-contained deck-generation prompt the operator drops into a
Claude session to produce the pitch-deck MD on demand (cost stays
controlled and visible — no silent paid call is ever fired by the site).

The brief deliberately captures only what the prospect alone knows. The
research-generated pages (ICP scoreboard, dissatisfaction landscape,
sourced stats, peer-quote hooks, partner archetypes, projections) are
listed as seeds + a gap checklist, not asked of the prospect.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# The canonical deck spine, reverse-mapped from serafina-pitch-deck-v2.html.
# The one-click prompt embeds this so it is fully self-contained.
DECK_SPINE: list[tuple[str, str]] = [
    ("Cover", "Company, the two-track thesis in one line, confidential meta."),
    ("Opening line", "The single highest-rated permission-slip line for this buyer."),
    ("The Method", "Find the grief, name it in their words, hand them the doorknob."),
    ("Dissatisfaction Landscape", "Why now — sourced pressure systems landing on the cohort. RESEARCH."),
    ("ICP Scoreboard", "Segments scored across 6 axes /60, top 3 picks. RESEARCH."),
    ("Two Tracks", "B2B direct to the individual + B2B2C to the gatekeeper who holds the cohort."),
    ("Round-1 Pilot", "Six-cell (3 segments x 2 hooks) test plan; one offer, one CTA."),
    ("Sample send + funnel math", "A compliant Day-1 email + projected funnel economics off the real price."),
    ("Compliance Posture", "What we will not do, named upfront; geo posture; the prospect's hard-nos."),
    ("Funnel Handoff", "Cold reply -> the doorknob -> qualified -> call. Routing + capacity."),
    ("Partner Archetypes", "Track-2 gatekeeper archetypes + economics. RESEARCH + client seeds."),
    ("Risk Register", "The 3 failure modes that kill this if hidden."),
    ("Instrumentation", "The single number that decides everything; anti-metrics."),
    ("30/60/90 Projection", "Honest separate B2B and B2B2C revenue lines off the real price/LTV."),
    ("The Inception Bench", "Why not a freelancer — receipts from live campaigns."),
    ("Commercial Structure", "Proposed deal shape — build + retainer + performance, not left open."),
    ("Week 1 Asks", "What we need from them to ship Day 1; decisions due in week 1."),
    ("Next Steps", "From here to first send; the five-day path."),
]

_TONE_GUIDE = {
    "Direct": "short declaratives, no throat-clearing, lead with the claim.",
    "Conversational": "peer-to-peer, contractions, like one operator emailing another.",
    "Challenger": "name the uncomfortable truth first, then the reframe.",
    "Data-driven": "every assertion carries a number; proof before persuasion.",
}


def _slug(text: str, fallback: str = "prospect") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:48] or fallback


def _block(value: str, empty: str = "_(not provided)_") -> str:
    v = (value or "").strip()
    return v if v else empty


def artifact_basename(answers: dict[str, Any], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now:%Y-%m-%d}-{_slug(answers.get('company', ''))}"


def build_intake_brief(answers: dict[str, Any], now: datetime | None = None) -> str:
    """Deterministic Intake Brief MD. Same artifact class as a Phase-1 brief,
    but client-sourced and gap-free for the deck pipeline."""
    now = now or datetime.now(timezone.utc)
    a = answers
    tone = (a.get("tone") or "").strip()
    tone_note = _TONE_GUIDE.get(tone, "")

    return f"""# Intake Brief — {_block(a.get('company'), 'Unknown company')}

**Prepared:** {now:%Y-%m-%d %H:%M UTC} · pre-sales-call intake (inception-emails.com/apply)
**Contact:** {_block(a.get('name'), '—')} · {_block(a.get('email'), '—')}
**Website:** {_block(a.get('website'), '—')}
**Output target:** pitch-deck MD via the one-click prompt at the bottom of this file.

---

## §1 · Business & Mechanism
{_block(a.get('summary'))}

## §2 · Offer & Economics
{_block(a.get('offer'))}

> Every funnel and ROI number in the deck is computed from the price stated above.
> If a range/"depends" is all that was given, flag it as the #1 question for the call.

## §3 · The Doorknob (value-up-front offer)
{_block(a.get('doorknob'))}

> This is the cold CTA — what a stranger gets for replying, with no sales call.
> If the prospect wrote "need help" / left it thin, designing this is the call's
> primary agenda item. The deck's Method + Pilot pages depend on it.

## §4 · Buyer & Grief
{_block(a.get('buyer'))}

> Seeds the research engine: ICP, the pre-purchase grief in their words, the
> trigger window. Research expands/scores this — it is not taken as final.

## §5 · Voice & Tone
**Tone:** {_block(tone, '—')}{f' — {tone_note}' if tone_note else ''}

**Voice samples:**
{_block(a.get('voice'))}

## §6 · Provable Proof
{_block(a.get('proof'), '_(none supplied — deck uses no proof claims unless named + exact)_')}

## §7 · Constraints & Hard-Nos
{_block(a.get('notes'), '_(none supplied)_')}

---

## §8 · Research seeds & gap checklist (what the prospect was deliberately NOT asked)

The deck is research-driven. Before/while writing it, the deck pipeline must
generate the following from the seeds above — none of it is owed by the prospect:

- [ ] ICP scoreboard — segments scored /60 across the 6 axes, top-3 Round-1 picks
- [ ] Dissatisfaction landscape — sourced pressure systems, dated, with URLs
- [ ] Peer-quote hooks — verbatim lines from the buyer's own ranks (Reddit/Glassdoor/Blind/forums)
- [ ] Partner / gatekeeper archetypes for Track 2 + economics
- [ ] Funnel math + 30/60/90 projection computed off §2 price and stated LTV
- [ ] Compliance posture for the geos implied by §4 (and the §7 hard-nos)
- [ ] Risk register — the 3 failure modes specific to this offer/cohort

Open questions to resolve on the call (do NOT email the prospect a form again):
- [ ] Exact price if §2 gave a range
- [ ] Doorknob spec if §3 was thin / "need help"
- [ ] Geos they will sell into (for compliance posture)
- [ ] Calendar capacity / who owns discovery calls (caps the ramp)

---

## ── ONE-CLICK DECK PROMPT ──

Copy everything between the lines below into a fresh Claude Code session to
generate the pitch-deck MD. It is self-contained. No paid call is fired by
the website — running this is a deliberate, visible operator action.

================================================================================
{build_deck_prompt(a, now=now)}
================================================================================
"""


def build_deck_prompt(answers: dict[str, Any], now: datetime | None = None) -> str:
    """Self-contained deck-generation prompt. Drop into a Claude session ->
    pitch-deck MD in the established Inception structure."""
    now = now or datetime.now(timezone.utc)
    a = answers
    company = _block(a.get("company"), "the prospect")
    spine = "\n".join(
        f"{i+1:>2}. **{name}** — {desc}" for i, (name, desc) in enumerate(DECK_SPINE)
    )
    return f"""# DECK GENERATION — {company}

You are writing a cold-outreach pitch deck for **{company}** in the Inception
Emails house style. Output a single Markdown file: `{artifact_basename(a, now)}-pitch-deck.md`.

## Inputs (the complete client intake — do not ask for more)

- **Company:** {company}
- **Website:** {_block(a.get('website'), '—')} — read it before writing a word.
- **What they do + transformation:** {_block(a.get('summary'))}
- **Offer + price:** {_block(a.get('offer'))}
- **Doorknob (cold CTA value-product):** {_block(a.get('doorknob'))}
- **Buyer + grief + trigger:** {_block(a.get('buyer'))}
- **Voice samples:** {_block(a.get('voice'))}
- **Tone:** {_block(a.get('tone'), 'Conversational')} — {_TONE_GUIDE.get((a.get('tone') or '').strip(), 'peer-level operator voice.')}
- **Provable proof:** {_block(a.get('proof'), 'none — use NO proof claims unless named + exact')}
- **Hard-nos / constraints:** {_block(a.get('notes'), 'none stated')}

## Method

1. **Research first.** Using the buyer + transformation above as seeds, run
   deep research to produce: an ICP scoreboard (segments scored /60 across
   dissatisfaction acuity, displacement anxiety, cold-email reachability,
   spend power, framing affinity, word-of-mouth), a dated + sourced
   dissatisfaction landscape, and verbatim peer-quote hooks lifted from the
   buyer's own communities. No hallucinated stats — every number gets a
   source URL with date or it is cut. Mirror the rigor of a Master Research
   Prompt: write findings down, cite inline, do not invent.
2. **Then write the deck** in this exact spine (one `##` section each):

{spine}

3. Funnel math and the 30/60/90 projection are computed off the real price
   in the offer line — show the arithmetic, keep ranges conservative.
4. Compliance Posture names what we will NOT do, plus the client's hard-nos
   verbatim. Week 1 Asks lists what we need from them to ship Day 1.

## Rules

- Write in the client's voice/tone above. Honor every hard-no.
- Proof only when named and exact. Vague proof is cut.
- Plain, dense, scannable. No throat-clearing. This persuades a skeptical
  operator who will interrogate every page.
- If the price was a range or the doorknob was thin, write the deck against
  the most defensible assumption and add a one-line "confirm on call" flag
  on that page — never stall, never email the prospect another form.
- End with a short "what I'd add in a next revision" note, like the
  canonical serafina-pitch-deck-v2 reference.
"""
