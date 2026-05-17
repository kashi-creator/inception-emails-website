"""Unit tests for the deterministic Intake Brief + deck-prompt generator."""
from __future__ import annotations

from datetime import datetime, timezone

from brief import (
    DECK_SPINE,
    artifact_basename,
    build_deck_prompt,
    build_intake_brief,
)

NOW = datetime(2026, 5, 16, 14, 30, tzinfo=timezone.utc)

ANSWERS = {
    "name": "Alex Rivera",
    "email": "alex@acmecorp.com",
    "company": "Acme Corp",
    "website": "acmecorp.com",
    "summary": "We install lifecycle messaging for SaaS teams.",
    "offer": "12-week install, $18,000 flat.",
    "doorknob": "A 5-minute churn-leak audit.",
    "buyer": "Head of Growth with a board mandate to fix retention.",
    "voice": "https://example.com/essay",
    "tone": "Direct",
    "proof": "Northbeam 4.1% -> 2.3% churn in 11 weeks.",
    "notes": "Never say 'growth hacking'.",
}


def test_brief_contains_every_answer_and_section():
    md = build_intake_brief(ANSWERS, now=NOW)
    assert "# Intake Brief — Acme Corp" in md
    assert "2026-05-16 14:30 UTC" in md
    for section in ("§1 · Business", "§2 · Offer", "§3 · The Doorknob",
                    "§4 · Buyer", "§5 · Voice", "§6 · Provable",
                    "§7 · Constraints", "§8 · Research seeds"):
        assert section in md, section
    for value in (ANSWERS["summary"], ANSWERS["offer"], ANSWERS["doorknob"],
                  ANSWERS["buyer"], ANSWERS["proof"], ANSWERS["notes"]):
        assert value in md
    assert "ONE-CLICK DECK PROMPT" in md
    assert "DECK GENERATION — Acme Corp" in md


def test_brief_handles_missing_optionals():
    sparse = dict(ANSWERS, proof="", notes="")
    md = build_intake_brief(sparse, now=NOW)
    assert "_(none supplied" in md  # graceful placeholder, not a crash
    assert "ONE-CLICK DECK PROMPT" in md


def test_deck_prompt_is_self_contained():
    p = build_deck_prompt(ANSWERS, now=NOW)
    # Every spine section name appears so the prompt needs no external doc.
    for name, _ in DECK_SPINE:
        assert name in p, name
    assert "Research first" in p
    assert "No hallucinated stats" in p or "source URL" in p
    assert ANSWERS["doorknob"] in p
    assert "2026-05-16-acme-corp-pitch-deck.md" in p


def test_artifact_basename_slugifies():
    assert artifact_basename(ANSWERS, now=NOW) == "2026-05-16-acme-corp"
    assert artifact_basename({"company": "A/B  Test, Inc."}, now=NOW) == "2026-05-16-a-b-test-inc"
    assert artifact_basename({"company": ""}, now=NOW) == "2026-05-16-prospect"
