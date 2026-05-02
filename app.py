from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from ghl_client import GhlClient, GhlClientError

app = Flask(__name__, static_folder=".", static_url_path="")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("inception-emails-site")

GHL_LOCATION_ID = "oPTc9Dv3gSsB3uQmYdBd"

CF_VERTICAL = "2PvVC82Z2zCscfwBabiV"
CF_MONTHLY_VOLUME_TARGET = "1Fy2glO1vMD6yhhFp21R"

VERTICAL_OPTIONS: dict[str, str] = {
    "MSP": "MSP",
    "Functional Medicine": "Functional Medicine",
    "Property Maintenance": "Property Maintenance",
    "Dental": "Dental",
    "Life Insurance": "Life Insurance",
    "Mortgage Loan Officer": "Mortgage",
    "Other": "Other",
}

VOLUME_BUCKETS: dict[str, int] = {
    "Under 500": 250,
    "500-2,000": 1250,
    "2,000-5,000": 3500,
    "5,000-10,000": 7500,
    "10,000+": 15000,
}

FREE_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
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
    }
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_ghl_singleton: GhlClient | None = None


def _ghl() -> GhlClient:
    global _ghl_singleton
    if _ghl_singleton is None:
        pit = os.environ.get("GHL_LOCATION_API_KEY")
        if not pit:
            raise RuntimeError("GHL_LOCATION_API_KEY env var is not set")
        _ghl_singleton = GhlClient(pit=pit, location_id=GHL_LOCATION_ID)
    return _ghl_singleton


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/msp.html")
@app.route("/msp")
def msp():
    return send_from_directory(".", "msp.html")


@app.route("/functional-medicine.html")
@app.route("/functional-medicine")
def functional_medicine():
    return send_from_directory(".", "functional-medicine.html")


@app.route("/property-maintenance.html")
@app.route("/property-maintenance")
def property_maintenance():
    return send_from_directory(".", "property-maintenance.html")


@app.route("/dental.html")
@app.route("/dental")
def dental():
    return send_from_directory(".", "dental.html")


@app.route("/life-insurance.html")
@app.route("/life-insurance")
def life_insurance():
    return send_from_directory(".", "life-insurance.html")


@app.route("/mortgage.html")
@app.route("/mortgage")
def mortgage():
    return send_from_directory(".", "mortgage.html")


@app.route("/apply")
@app.route("/apply.html")
def apply_form():
    return send_from_directory(".", "apply.html")


@app.route("/healthz")
def healthz():
    return ("ok", 200, {"Content-Type": "text/plain"})


def _err(field: str, message: str, status: int = 400):
    return jsonify({"ok": False, "field": field, "error": message}), status


def _norm(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _validate(payload: Any) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    if not isinstance(payload, dict):
        return None, _err("_root", "Request body must be JSON object.")

    first_name = _norm(payload.get("firstName"))
    email = _norm(payload.get("email")).lower()
    company_name = _norm(payload.get("companyName"))
    vertical_raw = _norm(payload.get("vertical"))
    volume_raw = _norm(payload.get("monthlyVolumeTarget"))
    challenge = _norm(payload.get("challenge"))

    if not first_name or len(first_name) > 100:
        return None, _err("firstName", "First name is required.")
    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        return None, _err("email", "A valid email is required.")
    domain = email.rsplit("@", 1)[-1]
    if domain in FREE_EMAIL_DOMAINS:
        return None, _err(
            "email",
            "Please use your work email — we work with businesses, not individuals.",
        )
    if not company_name or len(company_name) > 200:
        return None, _err("companyName", "Company name is required.")
    if vertical_raw not in VERTICAL_OPTIONS:
        return None, _err("vertical", "Please pick a vertical from the list.")
    if volume_raw not in VOLUME_BUCKETS:
        return None, _err("monthlyVolumeTarget", "Please pick a monthly volume from the list.")
    if not challenge or not (10 <= len(challenge) <= 2000):
        return None, _err("challenge", "Please share a few sentences (10–2000 chars).")

    return (
        {
            "firstName": first_name,
            "email": email,
            "companyName": company_name,
            "vertical": VERTICAL_OPTIONS[vertical_raw],
            "monthlyVolumeTarget": VOLUME_BUCKETS[volume_raw],
            "verticalRaw": vertical_raw,
            "volumeRaw": volume_raw,
            "challenge": challenge,
        },
        None,
    )


@app.route("/api/apply", methods=["POST"])
def api_apply():
    started = time.monotonic()
    payload = request.get_json(silent=True)
    clean, err = _validate(payload)
    if err is not None:
        body, status = err
        log.info(
            "apply_submit rejected status=%s field=%s",
            status,
            body.get_json().get("field"),
        )
        return body, status

    domain = clean["email"].rsplit("@", 1)[-1]

    try:
        ghl = _ghl()
    except RuntimeError:
        log.error("apply_submit blocked: GHL_LOCATION_API_KEY missing")
        return jsonify({"ok": False, "error": "Server misconfigured."}), 500

    try:
        result = ghl.upsert_contact(
            email=clean["email"],
            first_name=clean["firstName"],
            company_name=clean["companyName"],
            source_tag="src:website-form",
        )
        contact_id = result["contact_id"]
        ghl.add_tags(contact_id, ["stage:lead"])
        ghl.set_custom_fields(
            contact_id,
            [
                {"id": CF_VERTICAL, "value": clean["vertical"]},
                {"id": CF_MONTHLY_VOLUME_TARGET, "value": clean["monthlyVolumeTarget"]},
            ],
        )
        ghl.add_note(
            contact_id,
            f"Apply form — biggest lead-gen challenge:\n\n{clean['challenge']}",
        )
    except GhlClientError as exc:
        log.error(
            "apply_submit ghl_error domain=%s fields=%s",
            domain,
            exc.to_log_fields(),
        )
        return jsonify({"ok": False, "error": "Could not submit. Try again shortly."}), 500
    except Exception:
        log.exception("apply_submit unexpected error domain=%s", domain)
        return jsonify({"ok": False, "error": "Could not submit. Try again shortly."}), 500

    latency_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "apply_submit ok domain=%s vertical=%s volume=%s dnc=%s latency_ms=%s",
        domain,
        clean["vertical"],
        clean["monthlyVolumeTarget"],
        result.get("dnc"),
        latency_ms,
    )
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
