# sms.py
"""
Simple SMS helper module.
Provides the Zlibrary class used by routes/library/library.py.
Sends SMS via a generic HTTP gateway (or logs them in dev).
"""

import os
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime

logger = logging.getLogger(__name__)


class Zlibrary:
    """Lightweight SMS sender.

    Config via environment variables (all optional):
        SMS_API_URL    – full endpoint of your SMS gateway
        SMS_API_KEY    – bearer token / api key
        SMS_SENDER_ID  – sender name (e.g. "LUNSERK")
        SMS_ENABLED    – "1" to enable real sending, anything else = log only
    """

    def __init__(self, api_url: str = None, api_key: str = None,
                 sender_id: str = None, enabled: bool = None):
        self.api_url = api_url or os.getenv("SMS_API_URL", "")
        self.api_key = api_key or os.getenv("SMS_API_KEY", "")
        self.sender_id = sender_id or os.getenv("SMS_SENDER_ID", "LUNSERK")
        env_enabled = os.getenv("SMS_ENABLED", "0")
        self.enabled = enabled if enabled is not None else env_enabled in ("1", "true", "True", "yes")

    # ---------- Core send ----------
    def send(self, phone: str, message: str, **extra) -> dict:
        """Send one SMS. Always returns a dict — never raises."""
        phone = self._normalize_phone(phone)
        if not phone:
            return {"success": False, "error": "invalid phone number"}

        payload = {
            "to": phone,
            "message": message,
            "sender": self.sender_id,
            **extra,
        }

        # Dev / disabled: log only
        if not self.enabled or not self.api_url:
            logger.info(f"[SMS-LOG] to={phone} msg={message!r}")
            return {
                "success": True,
                "simulated": True,
                "to": phone,
                "message": message,
                "at": datetime.utcnow().isoformat(),
            }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.api_url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return {"success": True, "status": resp.status, "body": body}
        except Exception as e:
            logger.warning(f"[SMS-ERROR] to={phone}: {e}")
            return {"success": False, "error": str(e)}

    # ---------- Bulk send ----------
    def send_bulk(self, recipients: list, message: str, **extra) -> list:
        """recipients: list of phone strings or dicts with 'phone'. Returns results list."""
        results = []
        for r in recipients:
            phone = r.get("phone") if isinstance(r, dict) else r
            if not phone:
                results.append({"success": False, "error": "missing phone", "input": r})
                continue
            results.append(self.send(phone, message, **extra))
        return results

    # ---------- Helper ----------
    @staticmethod
    def _normalize_phone(phone: str) -> str:
        if not phone:
            return ""
        p = str(phone).strip().replace(" ", "").replace("-", "")
        if p.startswith("+"):
            p = p[1:]
        # Uganda: 07xxxxxxx -> 2567xxxxxxx
        if p.startswith("0") and len(p) == 10:
            p = "256" + p[1:]
        if not p.isdigit():
            return ""
        return p


# ---------- Convenience module-level helpers ----------
_default_client = None


def get_client() -> Zlibrary:
    global _default_client
    if _default_client is None:
        _default_client = Zlibrary()
    return _default_client


def send_sms(phone: str, message: str, **extra) -> dict:
    """Quick single-SMS helper for import anywhere."""
    return get_client().send(phone, message, **extra)


def send_bulk_sms(recipients: list, message: str, **extra) -> list:
    return get_client().send_bulk(recipients, message, **extra)