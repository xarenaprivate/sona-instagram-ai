"""sona-instagram-ai - Instagram DM auto-reply webhook (Flask).

All secrets come from environment variables. Nothing secret lives in this repo.

Env vars:
  VERIFY_TOKEN        token you also enter in the Meta webhook setup (GET verification)
  PAGE_ACCESS_TOKEN   Instagram / Page access token used to send replies
  APP_SECRET          (optional) Meta app secret, enables X-Hub-Signature-256 check
  DONATE_URL          (optional) support link, only shared when the sender asks about donating
  AI_BASE_URL         (optional) OpenAI-compatible endpoint of a FREE-tier provider
  AI_API_KEY          (optional) key for that provider
  AI_MODEL            (optional) model name on that provider
If AI_* are not set, the bot uses the fixed replies below (no paid API is ever called).
"""
import hashlib
import hmac
import os
import re

import requests
from flask import Flask, abort, request

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
APP_SECRET = os.environ.get("APP_SECRET", "")
DONATE_URL = os.environ.get("DONATE_URL", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "").rstrip("/")
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "")

SITE = "https://xarenaprivate.github.io/xarena"
FACTS = (
    "XARENA ESPORTS runs free Free Fire tournaments. Entry is free. "
    "Points and badges are cosmetic only. The next one is the Ignition Cup on Saturday 24 Oct, 8 PM IST. "
    f"Register at {SITE}"
)

# Words a reply must never contain (XARENA is free entry, no cash prize, no UPI, no invented numbers).
BLOCKED = re.compile(r"entry\s*fee|cash\s*prize|prize\s*money|\bupi\b|paytm|phonepe|gpay|\bpay\b|\bbet\b|\d+\s*(players|squads|teams)\s*(joined|registered)", re.I)
DONATE_ASK = re.compile(r"donat|support|contribut|help\s*(the\s*)?(channel|team)", re.I)

SAFE_FALLBACK = f"Hi! XARENA runs free Free Fire tournaments. Details and registration: {SITE}"


def rule_reply(text: str) -> str:
    t = text.lower()
    if DONATE_ASK.search(t):
        if DONATE_URL:
            return f"Thanks for wanting to support XARENA! Support link: {DONATE_URL}. It is optional, the tournaments stay free."
        return "Thanks for wanting to support XARENA! Tournaments are free and always will be."
    if re.search(r"ignition|when|time|date|schedule|kab", t):
        return f"The Ignition Cup is on Saturday 24 Oct at 8 PM IST. Register free: {SITE}"
    if re.search(r"regist|join|slot|kaise|how", t):
        return f"Registration is free. Open {SITE}, tap Register, add your squad. You can also use the XARENA app."
    if re.search(r"fee|price|cost|free|paid|prize", t):
        return f"Joining is completely free. Points and badges are cosmetic only. Details: {SITE}"
    return SAFE_FALLBACK


def ai_reply(text: str) -> str:
    """Optional. Only runs when AI_* env vars point at a free-tier provider."""
    if not (AI_BASE_URL and AI_API_KEY and AI_MODEL):
        return ""
    system = (
        "You are the XARENA ESPORTS Instagram assistant. Reply in 1-3 short friendly sentences, in the user's language. "
        "Facts: " + FACTS + " Never mention entry fees, cash prizes, UPI or payments, and never invent player or squad counts. "
        "Only share a donation link if the user asks about donating. If unsure, point to the website."
    )
    try:
        r = requests.post(
            AI_BASE_URL + "/chat/completions",
            headers={"Authorization": "Bearer " + AI_API_KEY},
            json={"model": AI_MODEL, "max_tokens": 160,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": text[:500]}]},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


def build_reply(text: str) -> str:
    if DONATE_ASK.search(text):
        return rule_reply(text)  # donation questions always get the fixed, approved answer
    reply = ai_reply(text) or rule_reply(text)
    if BLOCKED.search(reply):
        return rule_reply(text) if not BLOCKED.search(rule_reply(text)) else SAFE_FALLBACK
    return reply


def send_dm(recipient_id: str, text: str) -> None:
    if not PAGE_ACCESS_TOKEN:
        return
    requests.post(
        "https://graph.facebook.com/v19.0/me/messages",
        params={"access_token": PAGE_ACCESS_TOKEN},
        json={"recipient": {"id": recipient_id}, "message": {"text": text[:900]}},
        timeout=15,
    )


def signature_ok() -> bool:
    if not APP_SECRET:
        return True
    sig = request.headers.get("X-Hub-Signature-256", "")
    want = "sha256=" + hmac.new(APP_SECRET.encode(), request.get_data(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, want)


@app.get("/")
def health():
    return "sona-instagram-ai ok"


@app.get("/webhook")
def verify():
    if request.args.get("hub.mode") == "subscribe" and VERIFY_TOKEN and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge", ""), 200
    abort(403)


@app.post("/webhook")
def receive():
    if not signature_ok():
        abort(403)
    data = request.get_json(silent=True) or {}
    for entry in data.get("entry", []):
        for ev in entry.get("messaging", []):
            msg = ev.get("message") or {}
            if msg.get("is_echo") or not msg.get("text"):
                continue
            sender = (ev.get("sender") or {}).get("id")
            if sender:
                send_dm(sender, build_reply(msg["text"]))
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
