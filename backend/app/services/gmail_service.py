"""
STKE Gmail Service - Simple OAuth2 without PKCE
"""

import os
import base64
import logging
import re
import requests
from typing import List

logger = logging.getLogger(__name__)

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

import os

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8000/api/v1/gmail/callback"
SCOPES = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_auth_url() -> str:
    import urllib.parse
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    data = resp.json()
    return {
        "token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "token_uri": TOKEN_URL,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }


def _get_headers(creds_dict: dict) -> dict:
    return {
        "Authorization": f"Bearer {creds_dict['token']}",
        "Cache-Control": "no-cache, no-store",
        "Pragma": "no-cache",
    }


def _refresh(creds_dict: dict) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "refresh_token": creds_dict["refresh_token"],
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    creds_dict["token"] = resp.json()["access_token"]
    return creds_dict


def _gmail_get(creds_dict: dict, url: str, params: dict = None):
    r = requests.get(url, headers=_get_headers(creds_dict), params=params or {})
    if r.status_code == 401 and creds_dict.get("refresh_token"):
        creds_dict = _refresh(creds_dict)
        r = requests.get(url, headers=_get_headers(creds_dict), params=params or {})
    r.raise_for_status()
    return r.json()


def fetch_emails(creds_dict: dict, max_results: int = 10) -> List[dict]:
    data = _gmail_get(creds_dict,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        {"maxResults": max_results, "labelIds": "INBOX", "q": "-in:trash -in:spam"},
    )
    emails = []
    for msg in data.get("messages", []):
        try:
            md = _gmail_get(creds_dict,
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                {"format": "full"},
            )
            headers = {h["name"]: h["value"] for h in md["payload"].get("headers", [])}
            emails.append({
                "id": msg["id"],
                "subject": headers.get("Subject", "(No Subject)"),
                "from": headers.get("From", "Unknown"),
                "date": headers.get("Date", ""),
                "body": _extract_body(md["payload"])[:3000],
                "snippet": md.get("snippet", ""),
            })
        except Exception as e:
            logger.warning(f"Email {msg['id']} failed: {e}")
    return emails


def _extract_body(payload: dict) -> str:
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
                    break
            elif "parts" in part:
                body = _extract_body(part)
                if body:
                    break
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    # Strip HTML tags
    body = re.sub(r"<[^>]+>", " ", body)
    # Decode HTML entities
    import html as html_lib
    body = html_lib.unescape(body)
    # Remove URLs
    body = re.sub(r"https?://\S+", "", body)
    # Remove lines with unsubscribe/privacy/footer junk
    lines = body.split("\n")
    clean_lines = []
    junk_keywords = [
        "unsubscribe", "privacy policy", "terms of service", "view in browser",
        "click here", "opt out", "mailing list", "email preferences", "©", "copyright",
        "all rights reserved", "sent to", "you received", "notification settings",
        "do not reply", "don't reply", "cannot reply", "no-reply", "noreply",
        "google play", "help centre", "help center", "support center",
        "manage preferences", "email settings", "this is an automated",
        "automated message", "please do not", "unable to respond",
        "visit our website", "download the app", "get the app",
        "follow us", "connect with us", "view online", "view this email",
        "having trouble", "display correctly", "images are blocked",
    ]
    for line in lines:
        low = line.lower().strip()
        if not low or len(low) < 5:
            continue
        if any(kw in low for kw in junk_keywords):
            continue
        # Skip lines that are too short to be meaningful tasks
        if len(low) < 15:
            continue
        # Skip lines that are just punctuation, numbers, or emails
        if re.match(r'^[\d\s\-_=*#.,:;|/\\]+$', low):
            continue
        if re.match(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$', low):
            continue
        clean_lines.append(line.strip())
    body = " ".join(clean_lines)
    return re.sub(r"\s+", " ", body).strip()[:3000]