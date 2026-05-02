"""Tiny GHL client mirroring @inception-emails/ghl-client (Phase 2) for the
marketing site's /api/apply endpoint. Python port covers only the calls
Phase 3 needs: upsert_contact, add_tags, set_custom_fields, add_note,
find_contact_by_email — with the same DNC short-circuit semantics and the
same "PIT never appears in errors or logs" guarantee.
"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Iterable

import requests

API_BASE = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"
DNC_TAG = "compliance:dnc"

log = logging.getLogger(__name__)


class GhlClientError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int,
        endpoint: str,
        method: str,
        request_id: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.endpoint = endpoint
        self.method = method
        self.request_id = request_id
        self.body = body

    def to_log_fields(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "endpoint": self.endpoint,
            "method": self.method,
            "request_id": self.request_id,
        }


@dataclass
class GhlClient:
    pit: str
    location_id: str
    base_url: str = API_BASE
    api_version: str = API_VERSION
    max_retries: int = 3
    base_backoff_ms: int = 250
    timeout_s: float = 15.0

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.pit}",
            "Version": self.api_version,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> tuple[int, Any, str | None]:
        url = f"{self.base_url}{path}"
        payload = json.dumps(body) if body is not None else None
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    data=payload,
                    timeout=self.timeout_s,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    raise GhlClientError(
                        f"network error on GHL {method} {path}: {exc.__class__.__name__}",
                        status=0,
                        endpoint=path,
                        method=method,
                    ) from exc
                self._sleep_backoff(attempt, retry_after=None)
                continue

            req_id = resp.headers.get("x-request-id") or resp.headers.get("traceid")
            text = resp.text or ""
            parsed: Any
            if not text:
                parsed = None
            else:
                try:
                    parsed = resp.json()
                except ValueError:
                    parsed = text

            if 200 <= resp.status_code < 300:
                return resp.status_code, parsed, req_id

            retriable = resp.status_code == 429 or 500 <= resp.status_code < 600
            if retriable and attempt < self.max_retries:
                self._sleep_backoff(attempt, retry_after=resp.headers.get("retry-after"))
                continue

            msg_extra = ""
            if isinstance(parsed, dict) and parsed.get("message"):
                msg_extra = f" — {parsed['message']}"
            raise GhlClientError(
                f"GHL {method} {path} failed: HTTP {resp.status_code}{msg_extra}",
                status=resp.status_code,
                endpoint=path,
                method=method,
                request_id=req_id,
                body=parsed,
            )
        # Unreachable — loop returns or raises.
        raise GhlClientError(
            f"GHL {method} {path} exhausted retries without response",
            status=0,
            endpoint=path,
            method=method,
        ) from last_exc

    @staticmethod
    def _parse_retry_after(header: str | None) -> float | None:
        if not header:
            return None
        try:
            return max(0.0, float(int(header)))
        except (TypeError, ValueError):
            return None

    def _sleep_backoff(self, attempt: int, *, retry_after: str | None) -> None:
        ra = self._parse_retry_after(retry_after)
        if ra is not None:
            time.sleep(min(ra, 30.0))
            return
        base = self.base_backoff_ms / 1000.0
        delay = min(8.0, base * (2 ** attempt) + random.random() * base)
        time.sleep(delay)

    @staticmethod
    def _unwrap_contact(body: Any) -> dict[str, Any] | None:
        if not isinstance(body, dict):
            return None
        c = body.get("contact") if isinstance(body.get("contact"), dict) else body
        if not isinstance(c, dict) or not c.get("id"):
            return None
        tags_raw = c.get("tags") or []
        c = dict(c)
        c["tags"] = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []
        return c

    @staticmethod
    def _is_dnc(tags: Iterable[str]) -> bool:
        return any(t == DNC_TAG for t in tags)

    def find_contact_by_email(self, email: str) -> dict[str, Any] | None:
        try:
            _, body, _ = self._request(
                "GET",
                "/contacts/search/duplicate",
                params={"locationId": self.location_id, "email": email},
            )
        except GhlClientError as exc:
            if exc.status == 404:
                return None
            raise
        return self._unwrap_contact(body)

    def get_contact(self, contact_id: str) -> dict[str, Any]:
        _, body, req_id = self._request("GET", f"/contacts/{contact_id}")
        c = self._unwrap_contact(body)
        if c is None:
            raise GhlClientError(
                f"GHL contact {contact_id} response missing contact body",
                status=0,
                endpoint=f"/contacts/{contact_id}",
                method="GET",
                request_id=req_id,
                body=body,
            )
        return c

    def upsert_contact(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        company_name: str | None = None,
        source_tag: str | None = None,
    ) -> dict[str, Any]:
        if not email and not phone:
            raise ValueError("upsert_contact requires email or phone")

        existing = self.find_contact_by_email(email) if email else None
        if existing and self._is_dnc(existing["tags"]):
            return {"contact_id": existing["id"], "created": False, "dnc": True}

        payload: dict[str, Any] = {"locationId": self.location_id}
        if email:
            payload["email"] = email
        if phone:
            payload["phone"] = phone
        if first_name is not None:
            payload["firstName"] = first_name
        if last_name is not None:
            payload["lastName"] = last_name
        if company_name is not None:
            payload["companyName"] = company_name
        if source_tag:
            payload["tags"] = [source_tag]

        _, body, req_id = self._request("POST", "/contacts/upsert", body=payload)
        contact = self._unwrap_contact(body)
        if contact is None:
            raise GhlClientError(
                "GHL upsert response missing contact body",
                status=0,
                endpoint="/contacts/upsert",
                method="POST",
                request_id=req_id,
                body=body,
            )
        new_flag = body.get("new") if isinstance(body, dict) else None
        created = bool(new_flag) if isinstance(new_flag, bool) else (existing is None)
        return {"contact_id": contact["id"], "created": created, "dnc": False}

    def add_tags(self, contact_id: str, tags: list[str]) -> None:
        if not tags:
            return
        current = self.get_contact(contact_id)
        if self._is_dnc(current["tags"]):
            return
        self._request(
            "POST",
            f"/contacts/{contact_id}/tags",
            body={"tags": list(tags)},
        )

    def set_custom_fields(self, contact_id: str, values: list[dict[str, Any]]) -> None:
        """`values` is the wire shape: [{"id": "...", "value": ...}, ...]."""
        if not values:
            return
        current = self.get_contact(contact_id)
        if self._is_dnc(current["tags"]):
            return
        self._request(
            "PUT",
            f"/contacts/{contact_id}",
            body={"customFields": values},
        )

    def add_note(self, contact_id: str, body_text: str) -> None:
        if not body_text:
            return
        current = self.get_contact(contact_id)
        if self._is_dnc(current["tags"]):
            return
        self._request(
            "POST",
            f"/contacts/{contact_id}/notes",
            body={"body": body_text},
        )

    def delete_contact(self, contact_id: str) -> None:
        """Best-effort delete for test cleanup. May 401/403 if PIT lacks scope."""
        self._request("DELETE", f"/contacts/{contact_id}")
