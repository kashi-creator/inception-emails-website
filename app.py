from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, request, send_from_directory

from brief import artifact_basename, build_deck_prompt, build_intake_brief
from ghl_client import GhlClient, GhlClientError

app = Flask(__name__, static_folder=".", static_url_path="")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("inception-emails-site")

GHL_LOCATION_ID = "oPTc9Dv3gSsB3uQmYdBd"

# Where the deterministic Intake Brief + one-click deck prompt are written for
# local runs. On ephemeral hosts this is best-effort; GHL note is the durable
# store. Never let a read-only FS break a submission.
BRIEFS_DIR = Path(os.environ.get("BRIEFS_DIR", "briefs"))

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

TONE_OPTIONS: frozenset[str] = frozenset(
    {"Direct", "Conversational", "Challenger", "Data-driven"}
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# field -> (label, required, min_len, max_len)
FORM_SCHEMA: dict[str, tuple[str, bool, int, int]] = {
    "name": ("Your name", True, 1, 100),
    "email": ("Work email", True, 3, 254),
    "company": ("Company / brand", True, 1, 200),
    "website": ("Website", True, 3, 300),
    "summary": ("What you do & the transformation", True, 20, 2000),
    "offer": ("Offer & price", True, 10, 1500),
    "doorknob": ("Your doorknob", True, 5, 1500),
    "buyer": ("Best customer & their frustration", True, 20, 2000),
    "voice": ("Voice samples", True, 5, 1500),
    "tone": ("Desired tone", True, 1, 40),
    "proof": ("Best provable result", False, 0, 1500),
    "notes": ("Constraints / hard-nos", False, 0, 1500),
}

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


@app.route("/about")
@app.route("/about.html")
def about():
    return send_from_directory(".", "about.html")


@app.route("/pricing")
@app.route("/pricing.html")
def pricing():
    return send_from_directory(".", "pricing.html")


@app.route("/contact")
@app.route("/contact.html")
def contact():
    return send_from_directory(".", "contact.html")


@app.route("/sitemap.xml")
def sitemap_xml():
    return send_from_directory(".", "sitemap.xml", mimetype="application/xml")


@app.route("/llms.txt")
def llms_txt():
    return send_from_directory(".", "llms.txt", mimetype="text/plain")


@app.route("/robots.txt")
def robots_txt():
    return send_from_directory(".", "robots.txt", mimetype="text/plain")


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

    clean: dict[str, Any] = {}
    for field, (label, required, min_len, max_len) in FORM_SCHEMA.items():
        value = _norm(payload.get(field))
        if not value:
            if required:
                return None, _err(field, f"{label} is required.")
            clean[field] = ""
            continue
        if len(value) > max_len:
            return None, _err(field, f"{label} is too long (max {max_len} chars).")
        if len(value) < min_len:
            return None, _err(
                field, f"{label} needs a little more detail (min {min_len} chars)."
            )
        clean[field] = value

    email = clean["email"].lower()
    if not EMAIL_RE.match(email):
        return None, _err("email", "A valid work email is required.")
    domain = email.rsplit("@", 1)[-1]
    if domain in FREE_EMAIL_DOMAINS:
        return None, _err(
            "email",
            "Please use your work email — we work with businesses, not individuals.",
        )
    clean["email"] = email

    if clean["tone"] not in TONE_OPTIONS:
        return None, _err("tone", "Please pick a tone from the list.")

    return clean, None


def _split_name(full: str) -> tuple[str, str]:
    parts = full.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _persist_local(basename: str, brief_md: str, deck_prompt: str) -> None:
    """Best-effort local artifact write. GHL note is the durable store —
    a read-only / ephemeral FS must never break a submission."""
    try:
        BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
        (BRIEFS_DIR / f"{basename}-intake-brief.md").write_text(
            brief_md, encoding="utf-8"
        )
        (BRIEFS_DIR / f"{basename}-deck-prompt.md").write_text(
            deck_prompt, encoding="utf-8"
        )
    except OSError as exc:
        log.info("brief local persist skipped: %s", exc.__class__.__name__)


def _notify_telegram(text: str) -> None:
    """Best-effort 'boom' ping to the operator. Fully optional — disabled if
    env not set, and any failure is swallowed so it can never break submit."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID_KASHI")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": True},
            timeout=5.0,
        )
    except requests.RequestException as exc:
        log.info("telegram notify failed: %s", exc.__class__.__name__)


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
    first_name, last_name = _split_name(clean["name"])

    brief_md = build_intake_brief(clean)
    deck_prompt = build_deck_prompt(clean)
    basename = artifact_basename(clean)
    _persist_local(basename, brief_md, deck_prompt)

    try:
        ghl = _ghl()
    except RuntimeError:
        log.error("apply_submit blocked: GHL_LOCATION_API_KEY missing")
        return jsonify({"ok": False, "error": "Server misconfigured."}), 500

    try:
        result = ghl.upsert_contact(
            email=clean["email"],
            first_name=first_name,
            last_name=last_name,
            company_name=clean["company"],
            source_tag="src:website-form",
        )
        contact_id = result["contact_id"]
        ghl.add_tags(contact_id, ["stage:lead"])
        # The full Intake Brief (incl. the one-click deck prompt) lands on the
        # contact as a note — durable, and where the operator already lives.
        ghl.add_note(contact_id, brief_md)
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

    _notify_telegram(
        f"🎯 New /apply intake — {clean['company']}\n"
        f"{clean['name']} · {clean['email']}\n"
        f"Offer: {clean['offer'][:120]}\n"
        f"Intake Brief + one-click deck prompt are on the GHL contact note."
    )

    latency_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "apply_submit ok domain=%s company=%s dnc=%s latency_ms=%s",
        domain,
        clean["company"][:40],
        result.get("dnc"),
        latency_ms,
    )
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
