"""Unit tests for /api/apply (9-field pre-sales intake). GHL client fully
mocked — no network. Local artifact write is stubbed so tests don't litter."""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

# A PIT must be present for app._ghl() to construct (we still mock the calls).
os.environ.setdefault("GHL_LOCATION_API_KEY", "test-pit-not-real")

import app  # noqa: E402  (import after env setup)
from ghl_client import GhlClientError  # noqa: E402


VALID_PAYLOAD = {
    "name": "Alex Rivera",
    "email": "alex@acmecorp.com",
    "company": "Acme Corp",
    "website": "acmecorp.com",
    "summary": (
        "We help mid-market SaaS teams cut churn by installing a lifecycle "
        "messaging system; customers go from guessing why users leave to a "
        "predictable retention number in 90 days."
    ),
    "offer": "12-week done-with-you retention install, $18,000 flat.",
    "doorknob": "A 5-minute interactive churn-leak audit that scores their lifecycle gaps.",
    "buyer": (
        "Head of Growth at a 50-200 person SaaS who just got a board mandate "
        "to fix net revenue retention and is terrified of the next QBR."
    ),
    "voice": "https://example.com/essay  https://example.com/podcast",
    "tone": "Direct",
    "proof": "Took Northbeam from 4.1% to 2.3% monthly logo churn in 11 weeks.",
    "notes": "Never call it 'growth hacking'.",
}

REQUIRED_FIELDS = [
    "name", "email", "company", "website", "summary",
    "offer", "doorknob", "buyer", "voice", "tone",
]


@pytest.fixture
def client():
    app.app.testing = True
    return app.app.test_client()


@pytest.fixture
def mock_ghl(monkeypatch):
    m = MagicMock()
    m.upsert_contact.return_value = {"contact_id": "C123", "created": True, "dnc": False}
    m.add_tags.return_value = None
    m.add_note.return_value = None
    monkeypatch.setattr(app, "_ghl", lambda: m)
    # Don't touch the filesystem or Telegram in unit tests.
    monkeypatch.setattr(app, "_persist_local", lambda *a, **k: None)
    monkeypatch.setattr(app, "_notify_telegram", lambda *a, **k: None)
    return m


# ── happy path + ordering ──────────────────────────────────────────────────────

def test_happy_path_returns_200_and_calls_in_order(client, mock_ghl):
    resp = client.post("/api/apply", json=VALID_PAYLOAD)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json() == {"ok": True}

    mock_ghl.upsert_contact.assert_called_once_with(
        email="alex@acmecorp.com",
        first_name="Alex",
        last_name="Rivera",
        company_name="Acme Corp",
        source_tag="src:website-form",
    )
    mock_ghl.add_tags.assert_called_once_with("C123", ["stage:lead"])
    mock_ghl.add_note.assert_called_once()

    note_args = mock_ghl.add_note.call_args
    assert note_args.args[0] == "C123"
    body = note_args.args[1]
    assert "Intake Brief — Acme Corp" in body
    assert "churn-leak audit" in body
    assert "ONE-CLICK DECK PROMPT" in body

    # No custom-field write any more; order is upsert → tags → note.
    seen = [c[0] for c in mock_ghl.method_calls]
    assert seen == ["upsert_contact", "add_tags", "add_note"]


def test_single_word_name_has_no_last_name(client, mock_ghl):
    resp = client.post("/api/apply", json=dict(VALID_PAYLOAD, name="Cher"))
    assert resp.status_code == 200
    kwargs = mock_ghl.upsert_contact.call_args.kwargs
    assert kwargs["first_name"] == "Cher"
    assert kwargs["last_name"] == ""


def test_optional_fields_may_be_omitted(client, mock_ghl):
    payload = dict(VALID_PAYLOAD)
    payload.pop("proof")
    payload.pop("notes")
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ── required-field validation ──────────────────────────────────────────────────

@pytest.mark.parametrize("missing_field", REQUIRED_FIELDS)
def test_missing_required_field_rejected_400(client, mock_ghl, missing_field):
    payload = dict(VALID_PAYLOAD)
    payload.pop(missing_field)
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert body["field"] == missing_field
    mock_ghl.upsert_contact.assert_not_called()


def test_empty_string_field_rejected(client, mock_ghl):
    resp = client.post("/api/apply", json=dict(VALID_PAYLOAD, name="   "))
    assert resp.status_code == 400
    assert resp.get_json()["field"] == "name"


def test_non_json_body_rejected(client, mock_ghl):
    resp = client.post("/api/apply", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    mock_ghl.upsert_contact.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("summary", "too short"),
        ("offer", "cheap"),
        ("doorknob", "no"),
        ("buyer", "everyone"),
        ("voice", "x"),
    ],
)
def test_too_short_rejected(client, mock_ghl, field, value):
    resp = client.post("/api/apply", json=dict(VALID_PAYLOAD, **{field: value}))
    assert resp.status_code == 400
    assert resp.get_json()["field"] == field
    mock_ghl.upsert_contact.assert_not_called()


def test_overlong_field_rejected(client, mock_ghl):
    resp = client.post("/api/apply", json=dict(VALID_PAYLOAD, offer="x" * 1501))
    assert resp.status_code == 400
    assert resp.get_json()["field"] == "offer"


# ── email validation ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_email", ["not-an-email", "no@dot", "@nope.com", "spaces in@x.com"])
def test_bad_email_format_rejected(client, mock_ghl, bad_email):
    resp = client.post("/api/apply", json=dict(VALID_PAYLOAD, email=bad_email))
    assert resp.status_code == 400
    assert resp.get_json()["field"] == "email"
    mock_ghl.upsert_contact.assert_not_called()


@pytest.mark.parametrize(
    "free_domain",
    ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
     "aol.com", "proton.me", "pm.me", "msn.com", "live.com"],
)
def test_free_email_domain_rejected(client, mock_ghl, free_domain):
    resp = client.post("/api/apply", json=dict(VALID_PAYLOAD, email=f"someone@{free_domain}"))
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["field"] == "email"
    assert "work email" in body["error"].lower()
    mock_ghl.upsert_contact.assert_not_called()


def test_email_normalized_lowercase(client, mock_ghl):
    resp = client.post("/api/apply", json=dict(VALID_PAYLOAD, email="MIXED.Case@Acme.COM"))
    assert resp.status_code == 200
    assert mock_ghl.upsert_contact.call_args.kwargs["email"] == "mixed.case@acme.com"


# ── enum validation ────────────────────────────────────────────────────────────

def test_unknown_tone_rejected(client, mock_ghl):
    resp = client.post("/api/apply", json=dict(VALID_PAYLOAD, tone="Prophetic"))
    assert resp.status_code == 400
    assert resp.get_json()["field"] == "tone"
    mock_ghl.upsert_contact.assert_not_called()


# ── upstream errors ────────────────────────────────────────────────────────────

def test_ghl_error_returns_500_generic(client, mock_ghl):
    mock_ghl.upsert_contact.side_effect = GhlClientError(
        "boom", status=502, endpoint="/contacts/upsert", method="POST"
    )
    resp = client.post("/api/apply", json=VALID_PAYLOAD)
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "boom" not in body["error"]
    assert "GHL" not in body["error"]


def test_dnc_contact_still_returns_200(client, mock_ghl):
    mock_ghl.upsert_contact.return_value = {"contact_id": "C-DNC", "created": False, "dnc": True}
    resp = client.post("/api/apply", json=VALID_PAYLOAD)
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_missing_pit_returns_500(monkeypatch, client):
    def boom():
        raise RuntimeError("GHL_LOCATION_API_KEY env var is not set")
    monkeypatch.setattr(app, "_ghl", boom)
    monkeypatch.setattr(app, "_persist_local", lambda *a, **k: None)
    resp = client.post("/api/apply", json=VALID_PAYLOAD)
    assert resp.status_code == 500
