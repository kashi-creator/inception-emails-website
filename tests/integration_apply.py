"""Gated integration test — hits live GHL via /api/apply on a locally-running
Flask server. Run with INTEGRATION=1 and GHL_LOCATION_API_KEY exported.
Usage: python tests/integration_apply.py http://localhost:5005
"""
from __future__ import annotations

import os
import sys
import time

import requests

from ghl_client import GhlClient, GhlClientError


def main() -> int:
    if os.environ.get("INTEGRATION") != "1":
        print("INTEGRATION=1 not set — skipping.", file=sys.stderr)
        return 0
    pit = os.environ.get("GHL_LOCATION_API_KEY")
    if not pit:
        print("GHL_LOCATION_API_KEY not set", file=sys.stderr)
        return 2

    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5005"
    ts = int(time.time())
    email = f"phase3-test+{ts}@inception-emails.com"

    payload = {
        "firstName": "Phase3",
        "email": email,
        "companyName": f"Phase3 Test Co {ts}",
        "vertical": "MSP",
        "monthlyVolumeTarget": "2,000-5,000",
        "challenge": (
            "Integration test: validating apply form end-to-end submits a contact "
            "with src:website-form and stage:lead plus the two custom fields."
        ),
    }

    print(f"→ POST {base}/api/apply (email={email})")
    r1 = requests.post(f"{base}/api/apply", json=payload, timeout=30)
    print(f"  HTTP {r1.status_code} {r1.text[:200]}")
    assert r1.status_code == 200, "first submit failed"
    assert r1.json() == {"ok": True}

    # Verify against live GHL.
    ghl = GhlClient(pit=pit, location_id="oPTc9Dv3gSsB3uQmYdBd")
    contact = None
    for attempt in range(5):
        contact = ghl.find_contact_by_email(email)
        if contact:
            break
        print(f"  …waiting for GHL to index (attempt {attempt + 1}/5)")
        time.sleep(2)

    assert contact is not None, "contact not found in GHL after 5 polls"
    contact_id = contact["id"]
    tags = set(contact.get("tags") or [])
    print(f"  contact_id={contact_id} tags={sorted(tags)}")

    # Tag assertions.
    expected_tags = {"src:website-form", "stage:lead"}
    missing = expected_tags - tags
    assert not missing, f"missing tags: {missing}"

    # Custom field assertions — fetch full contact (find/duplicate doesn't return cf).
    full = ghl.get_contact(contact_id)
    cf_list = full.get("customFields") or full.get("customField") or []
    cf_by_id = {c.get("id"): c.get("value") if "value" in c else c.get("field_value") for c in cf_list}
    print(f"  custom fields received: {cf_by_id}")
    assert cf_by_id.get("2PvVC82Z2zCscfwBabiV") == "MSP", "vertical not set"
    assert int(cf_by_id.get("1Fy2glO1vMD6yhhFp21R") or 0) == 3500, "monthly_volume_target not 3500"

    # Idempotency: submit again with same email, expect no duplicate.
    print("→ second submit (idempotency check)")
    r2 = requests.post(f"{base}/api/apply", json=payload, timeout=30)
    assert r2.status_code == 200
    contact2 = ghl.find_contact_by_email(email)
    assert contact2 and contact2["id"] == contact_id, "duplicate created!"
    print(f"  same contact_id={contact2['id']} ✓")

    # Cleanup.
    print(f"→ cleanup: DELETE /contacts/{contact_id}")
    try:
        ghl.delete_contact(contact_id)
        print("  deleted via API ✓")
    except GhlClientError as exc:
        print(f"  DELETE failed (status={exc.status}) — manually delete contact_id={contact_id} in GHL UI")

    print("\nINTEGRATION OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
