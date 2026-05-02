"""Unit tests for /api/apply. The GHL client is fully mocked — no network."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, call

import pytest

# A PIT must be present for app._ghl() to construct (we still mock the calls).
os.environ.setdefault("GHL_LOCATION_API_KEY", "test-pit-not-real")

import app  # noqa: E402  (import after env setup)
from ghl_client import GhlClientError  # noqa: E402


VALID_PAYLOAD = {
    "firstName": "Alex",
    "email": "alex@acmecorp.com",
    "companyName": "Acme Corp",
    "vertical": "MSP",
    "monthlyVolumeTarget": "2,000-5,000",
    "challenge": "Our outbound is plateauing — we keep landing in spam folders despite warming for weeks.",
}


@pytest.fixture
def client():
    app.app.testing = True
    return app.app.test_client()


@pytest.fixture
def mock_ghl(monkeypatch):
    m = MagicMock()
    m.upsert_contact.return_value = {"contact_id": "C123", "created": True, "dnc": False}
    m.add_tags.return_value = None
    m.set_custom_fields.return_value = None
    m.add_note.return_value = None
    monkeypatch.setattr(app, "_ghl", lambda: m)
    return m


# ── happy path + ordering ──────────────────────────────────────────────────────

def test_happy_path_returns_200_and_calls_in_order(client, mock_ghl):
    resp = client.post("/api/apply", json=VALID_PAYLOAD)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json() == {"ok": True}

    # Right calls in the right order.
    mock_ghl.upsert_contact.assert_called_once_with(
        email="alex@acmecorp.com",
        first_name="Alex",
        company_name="Acme Corp",
        source_tag="src:website-form",
    )
    mock_ghl.add_tags.assert_called_once_with("C123", ["stage:lead"])
    mock_ghl.set_custom_fields.assert_called_once_with(
        "C123",
        [
            {"id": app.CF_VERTICAL, "value": "MSP"},
            {"id": app.CF_MONTHLY_VOLUME_TARGET, "value": 3500},  # bucket → number
        ],
    )
    mock_ghl.add_note.assert_called_once()
    note_args = mock_ghl.add_note.call_args
    assert note_args.args[0] == "C123"
    assert "biggest lead-gen challenge" in note_args.args[1]
    assert "spam folders" in note_args.args[1]

    # Order: upsert before tags before fields before note.
    seen = [c[0] for c in mock_ghl.method_calls]
    assert seen == ["upsert_contact", "add_tags", "set_custom_fields", "add_note"]


def test_vertical_canonicalization_mortgage(client, mock_ghl):
    payload = dict(VALID_PAYLOAD, vertical="Mortgage Loan Officer")
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 200
    args = mock_ghl.set_custom_fields.call_args
    assert args.args[1][0] == {"id": app.CF_VERTICAL, "value": "Mortgage"}


# ── required-field validation ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "missing_field",
    ["firstName", "email", "companyName", "vertical", "monthlyVolumeTarget", "challenge"],
)
def test_missing_field_rejected_400(client, mock_ghl, missing_field):
    payload = dict(VALID_PAYLOAD)
    payload.pop(missing_field)
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert body["field"] == missing_field
    mock_ghl.upsert_contact.assert_not_called()


def test_empty_string_field_rejected(client, mock_ghl):
    payload = dict(VALID_PAYLOAD, firstName="   ")
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["field"] == "firstName"


def test_non_json_body_rejected(client, mock_ghl):
    resp = client.post("/api/apply", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    mock_ghl.upsert_contact.assert_not_called()


# ── email validation ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_email", ["not-an-email", "no@dot", "@nope.com", "spaces in@x.com"])
def test_bad_email_format_rejected(client, mock_ghl, bad_email):
    payload = dict(VALID_PAYLOAD, email=bad_email)
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["field"] == "email"
    mock_ghl.upsert_contact.assert_not_called()


@pytest.mark.parametrize(
    "free_domain",
    [
        "gmail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "icloud.com",
        "aol.com",
        "proton.me",
        "pm.me",
        "msn.com",
        "live.com",
    ],
)
def test_free_email_domain_rejected(client, mock_ghl, free_domain):
    payload = dict(VALID_PAYLOAD, email=f"someone@{free_domain}")
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["field"] == "email"
    assert "work email" in body["error"].lower()
    mock_ghl.upsert_contact.assert_not_called()


def test_email_normalized_lowercase(client, mock_ghl):
    payload = dict(VALID_PAYLOAD, email="MIXED.Case@Acme.COM")
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 200
    assert mock_ghl.upsert_contact.call_args.kwargs["email"] == "mixed.case@acme.com"


# ── enum validation ────────────────────────────────────────────────────────────

def test_unknown_vertical_rejected(client, mock_ghl):
    payload = dict(VALID_PAYLOAD, vertical="Crypto")
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["field"] == "vertical"


def test_unknown_volume_bucket_rejected(client, mock_ghl):
    payload = dict(VALID_PAYLOAD, monthlyVolumeTarget="42")
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["field"] == "monthlyVolumeTarget"


def test_challenge_too_short_rejected(client, mock_ghl):
    payload = dict(VALID_PAYLOAD, challenge="short")
    resp = client.post("/api/apply", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["field"] == "challenge"


# ── upstream errors ────────────────────────────────────────────────────────────

def test_ghl_error_returns_500_generic(client, mock_ghl):
    mock_ghl.upsert_contact.side_effect = GhlClientError(
        "boom", status=502, endpoint="/contacts/upsert", method="POST"
    )
    resp = client.post("/api/apply", json=VALID_PAYLOAD)
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    # Generic message — never leaks GHL internals.
    assert "boom" not in body["error"]
    assert "GHL" not in body["error"]


def test_dnc_contact_still_returns_200(client, mock_ghl):
    """DNC short-circuit lives inside the GHL helper. The endpoint should still
    return 200 because no error was raised — the helper just no-oped silently."""
    mock_ghl.upsert_contact.return_value = {"contact_id": "C-DNC", "created": False, "dnc": True}
    # add_tags / set_custom_fields / add_note silently no-op for DNC contacts.
    mock_ghl.add_tags.return_value = None
    mock_ghl.set_custom_fields.return_value = None
    mock_ghl.add_note.return_value = None

    resp = client.post("/api/apply", json=VALID_PAYLOAD)
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ── config guardrail ───────────────────────────────────────────────────────────

def test_missing_pit_returns_500(monkeypatch, client):
    """If the singleton can't construct (PIT missing), endpoint returns a 500
    rather than crashing — so the rest of the static site stays up."""
    def boom():
        raise RuntimeError("GHL_LOCATION_API_KEY env var is not set")
    monkeypatch.setattr(app, "_ghl", boom)
    resp = client.post("/api/apply", json=VALID_PAYLOAD)
    assert resp.status_code == 500
