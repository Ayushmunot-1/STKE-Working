# """
# STKE Google Calendar Service
# """

# import os
# import json
# import requests
# import urllib.parse
# from typing import List, Optional
# from datetime import datetime, timedelta

# os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# import os

# CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
# CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
# REDIRECT_URI = "http://localhost:8000/api/v1/calendar/callback"
# SCOPES = "https://www.googleapis.com/auth/calendar"
# AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
# TOKEN_URL = "https://oauth2.googleapis.com/token"
# CALENDAR_API = "https://www.googleapis.com/calendar/v3"


# def get_auth_url() -> str:
#     params = {
#         "client_id": CLIENT_ID,
#         "redirect_uri": REDIRECT_URI,
#         "response_type": "code",
#         "scope": SCOPES,
#         "access_type": "offline",
#         "prompt": "consent",
#     }
#     return AUTH_URL + "?" + urllib.parse.urlencode(params)


# def exchange_code(code: str) -> dict:
#     resp = requests.post(TOKEN_URL, data={
#         "code": code,
#         "client_id": CLIENT_ID,
#         "client_secret": CLIENT_SECRET,
#         "redirect_uri": REDIRECT_URI,
#         "grant_type": "authorization_code",
#     })
#     resp.raise_for_status()
#     data = resp.json()
#     return {
#         "token": data["access_token"],
#         "refresh_token": data.get("refresh_token", ""),
#         "token_uri": TOKEN_URL,
#         "client_id": CLIENT_ID,
#         "client_secret": CLIENT_SECRET,
#     }


# def _headers(creds: dict) -> dict:
#     return {"Authorization": f"Bearer {creds['token']}"}


# def _refresh(creds: dict) -> dict:
#     resp = requests.post(TOKEN_URL, data={
#         "refresh_token": creds["refresh_token"],
#         "client_id": CLIENT_ID,
#         "client_secret": CLIENT_SECRET,
#         "grant_type": "refresh_token",
#     })
#     resp.raise_for_status()
#     creds["token"] = resp.json()["access_token"]
#     return creds


# def _get(creds: dict, url: str, params: dict = None):
#     r = requests.get(url, headers=_headers(creds), params=params or {})
#     if r.status_code == 401 and creds.get("refresh_token"):
#         creds = _refresh(creds)
#         r = requests.get(url, headers=_headers(creds), params=params or {})
#     r.raise_for_status()
#     return r.json()


# def _post(creds: dict, url: str, body: dict):
#     r = requests.post(url, headers={**_headers(creds), "Content-Type": "application/json"},
#                       json=body)
#     if r.status_code == 401 and creds.get("refresh_token"):
#         creds = _refresh(creds)
#         r = requests.post(url, headers={**_headers(creds), "Content-Type": "application/json"},
#                           json=body)
#     r.raise_for_status()
#     return r.json()


# def _patch(creds: dict, url: str, body: dict):
#     r = requests.patch(url, headers={**_headers(creds), "Content-Type": "application/json"},
#                        json=body)
#     r.raise_for_status()
#     return r.json()


# def _delete(creds: dict, url: str):
#     r = requests.delete(url, headers=_headers(creds))
#     if r.status_code == 401 and creds.get("refresh_token"):
#         creds = _refresh(creds)
#         r = requests.delete(url, headers=_headers(creds))
#     return r.status_code


# def get_calendars(creds: dict) -> List[dict]:
#     data = _get(creds, f"{CALENDAR_API}/users/me/calendarList")
#     return data.get("items", [])


# def get_upcoming_events(creds: dict, max_results: int = 10) -> List[dict]:
#     now = datetime.utcnow().isoformat() + "Z"
#     data = _get(creds, f"{CALENDAR_API}/calendars/primary/events", {
#         "timeMin": now,
#         "maxResults": max_results,
#         "singleEvents": True,
#         "orderBy": "startTime",
#     })
#     return data.get("items", [])


# def create_event(creds: dict, task: dict) -> dict:
#     """Create a calendar event from a STKE task."""
#     title = task.get("title", "STKE Task")
#     deadline = task.get("deadline")
#     priority = task.get("priority", "medium")

#     priority_emoji = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "🟢"}.get(priority, "📋")

#     # Parse deadline or default to tomorrow at 9am IST
#     tz = "Asia/Kolkata"
#     if deadline:
#         try:
#             # Handle both ISO format with/without timezone
#             deadline_str = str(deadline).replace("Z", "+00:00")
#             if "+" in deadline_str or deadline_str.endswith("00:00"):
#                 dt = datetime.fromisoformat(deadline_str)
#                 # Convert to IST (UTC+5:30)
#                 from datetime import timezone as tz_module
#                 utc_offset = dt.utcoffset()
#                 if utc_offset is not None:
#                     dt = dt.replace(tzinfo=None) + utc_offset
#                 # Set to 9am if time is midnight (no time specified)
#                 if dt.hour == 0 and dt.minute == 0:
#                     dt = dt.replace(hour=9, minute=0, second=0)
#             else:
#                 dt = datetime.fromisoformat(deadline_str)
#                 if dt.hour == 0 and dt.minute == 0:
#                     dt = dt.replace(hour=9, minute=0, second=0)
#         except Exception:
#             dt = datetime.now() + timedelta(days=1)
#             dt = dt.replace(hour=9, minute=0, second=0)
#     else:
#         # No deadline — schedule tomorrow at 9am
#         dt = datetime.now() + timedelta(days=1)
#         dt = dt.replace(hour=9, minute=0, second=0)

#     # Format without timezone info — let Google use the specified timeZone
#     start = dt.strftime("%Y-%m-%dT%H:%M:%S")
#     end = (dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

#     event_body = {
#         "summary": f"{priority_emoji} {title}",
#         "description": f"Created by STKE\nPriority: {priority}\nStatus: {task.get('status', 'pending')}",
#         "start": {"dateTime": start, "timeZone": tz},
#         "end": {"dateTime": end, "timeZone": tz},
#         "reminders": {
#             "useDefault": False,
#             "overrides": [
#                 {"method": "popup", "minutes": 60},
#                 {"method": "popup", "minutes": 1440},
#             ],
#         },
#         "colorId": {"critical": "11", "high": "5", "medium": "7", "low": "10"}.get(priority, "7"),
#     }

#     return _post(creds, f"{CALENDAR_API}/calendars/primary/events", event_body)


# def delete_event(creds: dict, event_id: str) -> int:
#     return _delete(creds, f"{CALENDAR_API}/calendars/primary/events/{event_id}")

"""
STKE Google Calendar Service
"""

import os
import json
import requests
import urllib.parse
from typing import List, Optional
from datetime import datetime, timedelta

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

from app.core.config import settings

CLIENT_ID     = settings.google_client_id
CLIENT_SECRET = settings.google_client_secret
REDIRECT_URI  = "http://localhost:8000/api/v1/calendar/callback"
SCOPES        = "https://www.googleapis.com/auth/calendar"
AUTH_URL      = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL     = "https://oauth2.googleapis.com/token"
CALENDAR_API  = "https://www.googleapis.com/calendar/v3"


def get_auth_url() -> str:
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


def _headers(creds: dict) -> dict:
    return {"Authorization": f"Bearer {creds['token']}"}


def _refresh(creds: dict) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "refresh_token": creds["refresh_token"],
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    creds["token"] = resp.json()["access_token"]
    return creds


def _get(creds: dict, url: str, params: dict = None):
    r = requests.get(url, headers=_headers(creds), params=params or {})
    if r.status_code == 401 and creds.get("refresh_token"):
        creds = _refresh(creds)
        r = requests.get(url, headers=_headers(creds), params=params or {})
    r.raise_for_status()
    return r.json()


def _post(creds: dict, url: str, body: dict):
    r = requests.post(url, headers={**_headers(creds), "Content-Type": "application/json"},
                      json=body)
    if r.status_code == 401 and creds.get("refresh_token"):
        creds = _refresh(creds)
        r = requests.post(url, headers={**_headers(creds), "Content-Type": "application/json"},
                          json=body)
    r.raise_for_status()
    return r.json()


def _patch(creds: dict, url: str, body: dict):
    r = requests.patch(url, headers={**_headers(creds), "Content-Type": "application/json"},
                       json=body)
    r.raise_for_status()
    return r.json()


def _delete(creds: dict, url: str):
    r = requests.delete(url, headers=_headers(creds))
    if r.status_code == 401 and creds.get("refresh_token"):
        creds = _refresh(creds)
        r = requests.delete(url, headers=_headers(creds))
    return r.status_code


def get_calendars(creds: dict) -> List[dict]:
    data = _get(creds, f"{CALENDAR_API}/users/me/calendarList")
    return data.get("items", [])


def get_upcoming_events(creds: dict, max_results: int = 10) -> List[dict]:
    now = datetime.utcnow().isoformat() + "Z"
    data = _get(creds, f"{CALENDAR_API}/calendars/primary/events", {
        "timeMin": now,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    })
    return data.get("items", [])


def create_event(creds: dict, task: dict) -> dict:
    """Create a calendar event from a STKE task."""
    title    = task.get("title", "STKE Task")
    deadline = task.get("deadline")
    priority = task.get("priority", "medium")

    priority_emoji = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "🟢"}.get(priority, "📋")

    tz = "Asia/Kolkata"
    if deadline:
        try:
            deadline_str = str(deadline).replace("Z", "+00:00")
            if "+" in deadline_str or deadline_str.endswith("00:00"):
                dt = datetime.fromisoformat(deadline_str)
                from datetime import timezone as tz_module
                utc_offset = dt.utcoffset()
                if utc_offset is not None:
                    dt = dt.replace(tzinfo=None) + utc_offset
                if dt.hour == 0 and dt.minute == 0:
                    dt = dt.replace(hour=9, minute=0, second=0)
            else:
                dt = datetime.fromisoformat(deadline_str)
                if dt.hour == 0 and dt.minute == 0:
                    dt = dt.replace(hour=9, minute=0, second=0)
        except Exception:
            dt = datetime.now() + timedelta(days=1)
            dt = dt.replace(hour=9, minute=0, second=0)
    else:
        dt = datetime.now() + timedelta(days=1)
        dt = dt.replace(hour=9, minute=0, second=0)

    start = dt.strftime("%Y-%m-%dT%H:%M:%S")
    end   = (dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

    event_body = {
        "summary": f"{priority_emoji} {title}",
        "description": f"Created by STKE\nPriority: {priority}\nStatus: {task.get('status', 'pending')}",
        "start": {"dateTime": start, "timeZone": tz},
        "end":   {"dateTime": end,   "timeZone": tz},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 60},
                {"method": "popup", "minutes": 1440},
            ],
        },
        "colorId": {"critical": "11", "high": "5", "medium": "7", "low": "10"}.get(priority, "7"),
    }

    return _post(creds, f"{CALENDAR_API}/calendars/primary/events", event_body)


def delete_event(creds: dict, event_id: str) -> int:
    return _delete(creds, f"{CALENDAR_API}/calendars/primary/events/{event_id}")