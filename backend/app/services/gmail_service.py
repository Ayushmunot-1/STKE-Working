# """
# STKE Gmail Service — v2.0

# Changes from v1:
#   - SCOPE upgraded: readonly → gmail.send + gmail.readonly
#     (needed to send notification emails to assignees)
#   - notify_assignee() added — Step 8 of the ownership roadmap
#     Sends a clean task assignment email to the person assigned a task
#   - _send_email() helper added — handles Gmail API send with base64 encoding
#   - CLIENT_ID/SECRET now read from settings (not raw os.getenv)
#   - Duplicate `import os` removed
#   - f-string logging replaced with % formatting (best practice)
# """

# import os
# import base64
# import logging
# import re
# import requests
# from email.mime.text import MIMEText
# from email.mime.multipart import MIMEMultipart
# from typing import List, Optional

# from app.core.config import settings

# logger = logging.getLogger(__name__)

# os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
# os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

# # Read from settings (which reads from .env) — not raw os.getenv
# CLIENT_ID     = settings.google_client_id
# CLIENT_SECRET = settings.google_client_secret

# REDIRECT_URI = "http://localhost:8000/api/v1/gmail/callback"

# # UPGRADED: added gmail.send scope for notification emails
# # Previously only gmail.readonly — couldn't send anything
# SCOPES = " ".join([
#     "https://www.googleapis.com/auth/gmail.readonly",
#     "https://www.googleapis.com/auth/gmail.send",
# ])

# AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
# TOKEN_URL = "https://oauth2.googleapis.com/token"


# # ══════════════════════════════════════════════════════════════
# #  Auth (unchanged from v1)
# # ══════════════════════════════════════════════════════════════

# def get_auth_url() -> str:
#     import urllib.parse
#     params = {
#         "client_id":     CLIENT_ID,
#         "redirect_uri":  REDIRECT_URI,
#         "response_type": "code",
#         "scope":         SCOPES,
#         "access_type":   "offline",
#         "prompt":        "consent",
#     }
#     return AUTH_URL + "?" + urllib.parse.urlencode(params)


# def exchange_code(code: str) -> dict:
#     resp = requests.post(TOKEN_URL, data={
#         "code":          code,
#         "client_id":     CLIENT_ID,
#         "client_secret": CLIENT_SECRET,
#         "redirect_uri":  REDIRECT_URI,
#         "grant_type":    "authorization_code",
#     })
#     resp.raise_for_status()
#     data = resp.json()
#     return {
#         "token":          data["access_token"],
#         "refresh_token":  data.get("refresh_token", ""),
#         "token_uri":      TOKEN_URL,
#         "client_id":      CLIENT_ID,
#         "client_secret":  CLIENT_SECRET,
#     }


# # ══════════════════════════════════════════════════════════════
# #  HTTP helpers (unchanged from v1)
# # ══════════════════════════════════════════════════════════════

# def _get_headers(creds_dict: dict) -> dict:
#     return {
#         "Authorization": f"Bearer {creds_dict['token']}",
#         "Cache-Control": "no-cache, no-store",
#         "Pragma":        "no-cache",
#     }


# def _refresh(creds_dict: dict) -> dict:
#     resp = requests.post(TOKEN_URL, data={
#         "refresh_token": creds_dict["refresh_token"],
#         "client_id":     CLIENT_ID,
#         "client_secret": CLIENT_SECRET,
#         "grant_type":    "refresh_token",
#     })
#     resp.raise_for_status()
#     creds_dict["token"] = resp.json()["access_token"]
#     return creds_dict


# def _gmail_get(creds_dict: dict, url: str, params: dict = None):
#     r = requests.get(url, headers=_get_headers(creds_dict), params=params or {})
#     if r.status_code == 401 and creds_dict.get("refresh_token"):
#         creds_dict = _refresh(creds_dict)
#         r = requests.get(url, headers=_get_headers(creds_dict), params=params or {})
#     r.raise_for_status()
#     return r.json()


# # ══════════════════════════════════════════════════════════════
# #  Email sending (NEW in v2.0)
# # ══════════════════════════════════════════════════════════════

# def _build_notification_email(
#     to_name: str,
#     to_email: str,
#     sender_name: str,
#     task_title: str,
#     deadline_raw: Optional[str],
#     source_context: Optional[str],
# ) -> MIMEMultipart:
#     """
#     Build a clean, professional task assignment notification email.

#     Returns a MIMEMultipart object ready to be base64-encoded and sent.
#     """
#     msg = MIMEMultipart("alternative")
#     msg["Subject"] = f"📋 Task assigned to you: {task_title}"
#     msg["To"]      = to_email

#     # Deadline line — only shown if a deadline was detected
#     deadline_line = ""
#     if deadline_raw:
#         deadline_line = f"\n⏰  Due: {deadline_raw}\n"

#     # Context line — where the task came from
#     context_map = {
#         "email":    "an email",
#         "chat":     "a chat message",
#         "meeting":  "meeting notes",
#         "document": "a document",
#         "webpage":  "a web page",
#     }
#     source_label = context_map.get(source_context or "", "a message")

#     # ── Plain text version ─────────────────────────────────────
#     plain = f"""Hi {to_name},

# {sender_name} has assigned you a task via STKE:

#   📌  {task_title}{deadline_line}
# This task was automatically extracted from {source_label}.

# Please log in to your STKE dashboard to view, edit, or complete this task:
#   http://localhost:8000/dashboard

# If you believe this was assigned to you by mistake, you can ignore this email.

# —
# STKE · Semantic Task & Knowledge Extractor
# This is an automated notification. Please do not reply to this email.
# """

#     # ── HTML version ───────────────────────────────────────────
#     deadline_html = ""
#     if deadline_raw:
#         deadline_html = f"""
#         <tr>
#           <td style="padding:4px 0;color:#94a3b8;font-size:13px;">
#             ⏰ &nbsp;<strong>Due:</strong> {deadline_raw}
#           </td>
#         </tr>"""

#     html = f"""<!DOCTYPE html>
# <html>
# <head><meta charset="UTF-8"></head>
# <body style="margin:0;padding:0;background:#0f172a;font-family:Arial,sans-serif;">
#   <table width="100%" cellpadding="0" cellspacing="0">
#     <tr>
#       <td align="center" style="padding:40px 20px;">
#         <table width="560" cellpadding="0" cellspacing="0"
#                style="background:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #334155;">

#           <!-- Header -->
#           <tr>
#             <td style="background:linear-gradient(135deg,#1e3a5f,#1e40af);
#                         padding:24px 32px;">
#               <span style="font-size:22px;font-weight:800;color:#ffffff;
#                            letter-spacing:-0.5px;">⬡ STKE</span>
#               <span style="font-size:13px;color:#93c5fd;margin-left:10px;">
#                 Task Assignment
#               </span>
#             </td>
#           </tr>

#           <!-- Body -->
#           <tr>
#             <td style="padding:32px;">
#               <p style="color:#94a3b8;font-size:14px;margin:0 0 20px;">
#                 Hi <strong style="color:#e2e8f0;">{to_name}</strong>,
#               </p>
#               <p style="color:#cbd5e1;font-size:14px;margin:0 0 24px;line-height:1.6;">
#                 <strong style="color:#e2e8f0;">{sender_name}</strong>
#                 has assigned you a task via STKE:
#               </p>

#               <!-- Task card -->
#               <table width="100%" cellpadding="0" cellspacing="0"
#                      style="background:#0f172a;border-radius:8px;
#                             border-left:4px solid #3b82f6;margin-bottom:24px;">
#                 <tr>
#                   <td style="padding:20px 24px;">
#                     <table cellpadding="0" cellspacing="0">
#                       <tr>
#                         <td style="padding:0 0 8px;">
#                           <span style="font-size:16px;font-weight:700;
#                                        color:#f1f5f9;">
#                             📌 &nbsp;{task_title}
#                           </span>
#                         </td>
#                       </tr>
#                       {deadline_html}
#                       <tr>
#                         <td style="padding:4px 0;color:#64748b;font-size:12px;">
#                           Extracted from {source_label}
#                         </td>
#                       </tr>
#                     </table>
#                   </td>
#                 </tr>
#               </table>

#               <!-- CTA button -->
#               <table cellpadding="0" cellspacing="0">
#                 <tr>
#                   <td style="border-radius:8px;background:#3b82f6;">
#                     <a href="http://localhost:8000/dashboard"
#                        style="display:inline-block;padding:12px 28px;
#                               color:#ffffff;font-size:14px;font-weight:700;
#                               text-decoration:none;">
#                       View in Dashboard →
#                     </a>
#                   </td>
#                 </tr>
#               </table>

#               <p style="color:#475569;font-size:12px;margin:24px 0 0;
#                          line-height:1.6;">
#                 If this task was assigned to you by mistake, you can ignore
#                 this email.
#               </p>
#             </td>
#           </tr>

#           <!-- Footer -->
#           <tr>
#             <td style="padding:16px 32px;border-top:1px solid #334155;">
#               <p style="color:#475569;font-size:11px;margin:0;text-align:center;">
#                 STKE · Semantic Task &amp; Knowledge Extractor
#                 &nbsp;·&nbsp; Automated notification · Do not reply
#               </p>
#             </td>
#           </tr>

#         </table>
#       </td>
#     </tr>
#   </table>
# </body>
# </html>"""

#     msg.attach(MIMEText(plain, "plain"))
#     msg.attach(MIMEText(html,  "html"))
#     return msg


# def _send_email(creds_dict: dict, msg: MIMEMultipart) -> dict:
#     """
#     Send a pre-built MIMEMultipart email via the Gmail API.
#     Handles token refresh automatically.

#     Returns the Gmail API response dict on success.
#     Raises requests.HTTPError on failure.
#     """
#     raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
#     body = {"raw": raw}

#     send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

#     r = requests.post(send_url, headers=_get_headers(creds_dict), json=body)

#     # Auto-refresh on 401 and retry once
#     if r.status_code == 401 and creds_dict.get("refresh_token"):
#         creds_dict = _refresh(creds_dict)
#         r = requests.post(send_url, headers=_get_headers(creds_dict), json=body)

#     r.raise_for_status()
#     return r.json()


# # ══════════════════════════════════════════════════════════════
# #  STEP 8: notify_assignee()
# #  The main new function — called from extraction_service.py
# #  when a task is assigned to someone other than the current user
# # ══════════════════════════════════════════════════════════════

# def notify_assignee(
#     creds_dict: dict,
#     assignee_email: str,
#     assignee_name: str,
#     sender_name: str,
#     task_title: str,
#     deadline_raw: Optional[str] = None,
#     source_context: Optional[str] = None,
# ) -> bool:
#     """
#     Send a task assignment notification email to the assignee.

#     Called by extraction_service.py after a delegated task is saved.
#     Uses the current user's Gmail credentials to send on their behalf.

#     Args:
#         creds_dict      : Gmail OAuth token dict for the current user (sender)
#         assignee_email  : Email address of the person being notified
#         assignee_name   : Display name of the assignee (for email greeting)
#         sender_name     : Name of the person who extracted/assigned the task
#         task_title      : The task that was assigned
#         deadline_raw    : Human-readable deadline string e.g. "by Friday"
#         source_context  : Where the task came from e.g. "email", "meeting"

#     Returns:
#         True  → email sent successfully
#         False → sending failed (logged, but extraction is NOT blocked)

#     Design note:
#         This function deliberately catches all exceptions and returns False
#         rather than raising. A notification failure should NEVER block or
#         roll back the task extraction — it's a best-effort side effect.
#     """
#     try:
#         msg = _build_notification_email(
#             to_name=assignee_name,
#             to_email=assignee_email,
#             sender_name=sender_name,
#             task_title=task_title,
#             deadline_raw=deadline_raw,
#             source_context=source_context,
#         )
#         result = _send_email(creds_dict, msg)
#         logger.info(
#             "Notification sent to %s for task '%s' (Gmail message id: %s)",
#             assignee_email, task_title, result.get("id", "unknown")
#         )
#         return True

#     except requests.HTTPError as e:
#         logger.error(
#             "Gmail API error sending notification to %s: %s — %s",
#             assignee_email, e, e.response.text if e.response else "no body"
#         )
#         return False
#     except Exception as e:
#         logger.error(
#             "Unexpected error sending notification to %s: %s",
#             assignee_email, e
#         )
#         return False


# # ══════════════════════════════════════════════════════════════
# #  Email fetching (unchanged from v1)
# # ══════════════════════════════════════════════════════════════

# def fetch_emails(creds_dict: dict, max_results: int = 10) -> List[dict]:
#     data = _gmail_get(
#         creds_dict,
#         "https://gmail.googleapis.com/gmail/v1/users/me/messages",
#         {"maxResults": max_results, "labelIds": "INBOX", "q": "-in:trash -in:spam"},
#     )
#     emails = []
#     for msg in data.get("messages", []):
#         try:
#             md = _gmail_get(
#                 creds_dict,
#                 f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
#                 {"format": "full"},
#             )
#             headers = {h["name"]: h["value"] for h in md["payload"].get("headers", [])}
#             emails.append({
#                 "id":      msg["id"],
#                 "subject": headers.get("Subject", "(No Subject)"),
#                 "from":    headers.get("From", "Unknown"),
#                 "date":    headers.get("Date", ""),
#                 "body":    _extract_body(md["payload"])[:3000],
#                 "snippet": md.get("snippet", ""),
#             })
#         except Exception as e:
#             logger.warning("Email %s failed: %s", msg["id"], e)
#     return emails


# def _extract_body(payload: dict) -> str:
#     body = ""
#     if "parts" in payload:
#         for part in payload["parts"]:
#             if part.get("mimeType") == "text/plain":
#                 data = part.get("body", {}).get("data", "")
#                 if data:
#                     body = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
#                     break
#             elif "parts" in part:
#                 body = _extract_body(part)
#                 if body:
#                     break
#     else:
#         data = payload.get("body", {}).get("data", "")
#         if data:
#             body = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

#     # Strip HTML tags
#     body = re.sub(r"<[^>]+>", " ", body)
#     # Decode HTML entities
#     import html as html_lib
#     body = html_lib.unescape(body)
#     # Remove URLs
#     body = re.sub(r"https?://\S+", "", body)

#     # Remove junk lines
#     lines = body.split("\n")
#     clean_lines = []
#     junk_keywords = [
#         "unsubscribe", "privacy policy", "terms of service", "view in browser",
#         "click here", "opt out", "mailing list", "email preferences", "©", "copyright",
#         "all rights reserved", "sent to", "you received", "notification settings",
#         "do not reply", "don't reply", "cannot reply", "no-reply", "noreply",
#         "google play", "help centre", "help center", "support center",
#         "manage preferences", "email settings", "this is an automated",
#         "automated message", "please do not", "unable to respond",
#         "visit our website", "download the app", "get the app",
#         "follow us", "connect with us", "view online", "view this email",
#         "having trouble", "display correctly", "images are blocked",
#     ]
#     for line in lines:
#         low = line.lower().strip()
#         if not low or len(low) < 5:
#             continue
#         if any(kw in low for kw in junk_keywords):
#             continue
#         if len(low) < 15:
#             continue
#         if re.match(r'^[\d\s\-_=*#.,:;|/\\]+$', low):
#             continue
#         if re.match(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$', low):
#             continue
#         clean_lines.append(line.strip())

#     body = " ".join(clean_lines)
#     return re.sub(r"\s+", " ", body).strip()[:3000]

"""
STKE Gmail Service — v2.0

Changes from v1:
  - SCOPE upgraded: readonly → gmail.send + gmail.readonly
    (needed to send notification emails to assignees)
  - notify_assignee() added — Step 8 of the ownership roadmap
    Sends a clean task assignment email to the person assigned a task
  - _send_email() helper added — handles Gmail API send with base64 encoding
  - CLIENT_ID/SECRET now read from settings (not raw os.getenv)
  - Duplicate `import os` removed
  - f-string logging replaced with % formatting (best practice)
"""

import os
import base64
import logging
import re
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

# Read from settings (which reads from .env) — not raw os.getenv
CLIENT_ID     = settings.google_client_id
CLIENT_SECRET = settings.google_client_secret

REDIRECT_URI = "http://localhost:8000/api/v1/gmail/callback"

# UPGRADED: added gmail.send scope for notification emails
# Previously only gmail.readonly — couldn't send anything
SCOPES = " ".join([
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
])

AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


# ══════════════════════════════════════════════════════════════
#  Auth (unchanged from v1)
# ══════════════════════════════════════════════════════════════

def get_auth_url() -> str:
    import urllib.parse
    params = {
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         SCOPES,
        "access_type":   "offline",
        "prompt":        "consent",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "code":          code,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    })
    resp.raise_for_status()
    data = resp.json()
    return {
        "token":          data["access_token"],
        "refresh_token":  data.get("refresh_token", ""),
        "token_uri":      TOKEN_URL,
        "client_id":      CLIENT_ID,
        "client_secret":  CLIENT_SECRET,
    }


# ══════════════════════════════════════════════════════════════
#  HTTP helpers (unchanged from v1)
# ══════════════════════════════════════════════════════════════

def _get_headers(creds_dict: dict) -> dict:
    return {
        "Authorization": f"Bearer {creds_dict['token']}",
        "Cache-Control": "no-cache, no-store",
        "Pragma":        "no-cache",
    }


def _refresh(creds_dict: dict) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "refresh_token": creds_dict["refresh_token"],
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type":    "refresh_token",
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


# ══════════════════════════════════════════════════════════════
#  Email sending (NEW in v2.0)
# ══════════════════════════════════════════════════════════════

def _build_notification_email(
    to_name: str,
    to_email: str,
    sender_name: str,
    task_title: str,
    deadline_raw: Optional[str],
    source_context: Optional[str],
) -> MIMEMultipart:
    """
    Build a clean, professional task assignment notification email.

    Returns a MIMEMultipart object ready to be base64-encoded and sent.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📋 Task assigned to you: {task_title}"
    msg["To"]      = to_email

    # Deadline line — only shown if a deadline was detected
    deadline_line = ""
    if deadline_raw:
        deadline_line = f"\n⏰  Due: {deadline_raw}\n"

    # Context line — where the task came from
    context_map = {
        "email":    "an email",
        "chat":     "a chat message",
        "meeting":  "meeting notes",
        "document": "a document",
        "webpage":  "a web page",
    }
    source_label = context_map.get(source_context or "", "a message")

    # ── Plain text version ─────────────────────────────────────
    plain = f"""Hi {to_name},

{sender_name} has assigned you a task via STKE:

  📌  {task_title}{deadline_line}
This task was automatically extracted from {source_label}.

Please log in to your STKE dashboard to view, edit, or complete this task:
  http://localhost:8000/dashboard

If you believe this was assigned to you by mistake, you can ignore this email.

—
STKE · Semantic Task & Knowledge Extractor
This is an automated notification. Please do not reply to this email.
"""

    # ── HTML version ───────────────────────────────────────────
    deadline_html = ""
    if deadline_raw:
        deadline_html = f"""
        <tr>
          <td style="padding:4px 0;color:#94a3b8;font-size:13px;">
            ⏰ &nbsp;<strong>Due:</strong> {deadline_raw}
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f172a;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #334155;">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1e3a5f,#1e40af);
                        padding:24px 32px;">
              <span style="font-size:22px;font-weight:800;color:#ffffff;
                           letter-spacing:-0.5px;">⬡ STKE</span>
              <span style="font-size:13px;color:#93c5fd;margin-left:10px;">
                Task Assignment
              </span>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px;">
              <p style="color:#94a3b8;font-size:14px;margin:0 0 20px;">
                Hi <strong style="color:#e2e8f0;">{to_name}</strong>,
              </p>
              <p style="color:#cbd5e1;font-size:14px;margin:0 0 24px;line-height:1.6;">
                <strong style="color:#e2e8f0;">{sender_name}</strong>
                has assigned you a task via STKE:
              </p>

              <!-- Task card -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#0f172a;border-radius:8px;
                            border-left:4px solid #3b82f6;margin-bottom:24px;">
                <tr>
                  <td style="padding:20px 24px;">
                    <table cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding:0 0 8px;">
                          <span style="font-size:16px;font-weight:700;
                                       color:#f1f5f9;">
                            📌 &nbsp;{task_title}
                          </span>
                        </td>
                      </tr>
                      {deadline_html}
                      <tr>
                        <td style="padding:4px 0;color:#64748b;font-size:12px;">
                          Extracted from {source_label}
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- CTA button -->
              <table cellpadding="0" cellspacing="0">
                <tr>
                  <td style="border-radius:8px;background:#3b82f6;">
                    <a href="http://localhost:8000/dashboard"
                       style="display:inline-block;padding:12px 28px;
                              color:#ffffff;font-size:14px;font-weight:700;
                              text-decoration:none;">
                      View in Dashboard →
                    </a>
                  </td>
                </tr>
              </table>

              <p style="color:#475569;font-size:12px;margin:24px 0 0;
                         line-height:1.6;">
                If this task was assigned to you by mistake, you can ignore
                this email.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px;border-top:1px solid #334155;">
              <p style="color:#475569;font-size:11px;margin:0;text-align:center;">
                STKE · Semantic Task &amp; Knowledge Extractor
                &nbsp;·&nbsp; Automated notification · Do not reply
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))
    return msg


def _send_email(creds_dict: dict, msg: MIMEMultipart) -> dict:
    """
    Send a pre-built MIMEMultipart email via the Gmail API.
    Handles token refresh automatically.

    Returns the Gmail API response dict on success.
    Raises requests.HTTPError on failure.
    """
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    body = {"raw": raw}

    send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

    r = requests.post(send_url, headers=_get_headers(creds_dict), json=body)

    # Auto-refresh on 401 and retry once
    if r.status_code == 401 and creds_dict.get("refresh_token"):
        creds_dict = _refresh(creds_dict)
        r = requests.post(send_url, headers=_get_headers(creds_dict), json=body)

    r.raise_for_status()
    return r.json()


# ══════════════════════════════════════════════════════════════
#  STEP 8: notify_assignee()
#  The main new function — called from extraction_service.py
#  when a task is assigned to someone other than the current user
# ══════════════════════════════════════════════════════════════

def notify_assignee(
    creds_dict: dict,
    assignee_email: str,
    assignee_name: str,
    sender_name: str,
    task_title: str,
    deadline_raw: Optional[str] = None,
    source_context: Optional[str] = None,
) -> bool:
    """
    Send a task assignment notification email to the assignee.

    Called by extraction_service.py after a delegated task is saved.
    Uses the current user's Gmail credentials to send on their behalf.

    Args:
        creds_dict      : Gmail OAuth token dict for the current user (sender)
        assignee_email  : Email address of the person being notified
        assignee_name   : Display name of the assignee (for email greeting)
        sender_name     : Name of the person who extracted/assigned the task
        task_title      : The task that was assigned
        deadline_raw    : Human-readable deadline string e.g. "by Friday"
        source_context  : Where the task came from e.g. "email", "meeting"

    Returns:
        True  → email sent successfully
        False → sending failed (logged, but extraction is NOT blocked)

    Design note:
        This function deliberately catches all exceptions and returns False
        rather than raising. A notification failure should NEVER block or
        roll back the task extraction — it's a best-effort side effect.
    """
    try:
        msg = _build_notification_email(
            to_name=assignee_name,
            to_email=assignee_email,
            sender_name=sender_name,
            task_title=task_title,
            deadline_raw=deadline_raw,
            source_context=source_context,
        )
        result = _send_email(creds_dict, msg)
        logger.info(
            "Notification sent to %s for task '%s' (Gmail message id: %s)",
            assignee_email, task_title, result.get("id", "unknown")
        )
        return True

    except requests.HTTPError as e:
        logger.error(
            "Gmail API error sending notification to %s: %s — %s",
            assignee_email, e, e.response.text if e.response else "no body"
        )
        return False
    except Exception as e:
        logger.error(
            "Unexpected error sending notification to %s: %s",
            assignee_email, e
        )
        return False


# ══════════════════════════════════════════════════════════════
#  Email fetching — v2.1: sender-level junk filtering
# ══════════════════════════════════════════════════════════════

# Sender domains that are always automated/marketing — never actionable
_JUNK_SENDER_DOMAINS = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "notifications", "newsletter", "mailer", "updates",
    "alerts", "info", "support", "hello", "team",
    "mail", "news", "digest", "promo", "offers",
    "marketing", "deals", "shop", "store", "billing",
    "bounce", "autoresponder", "automated", "system",
}

# Subject line patterns that indicate automated/marketing mail
_JUNK_SUBJECT_PATTERNS = [
    "unsubscribe", "newsletter", "% off", "% discount",
    "special offer", "limited time", "act now", "deal of",
    "your receipt", "your order", "order confirmation",
    "payment received", "invoice #", "subscription renewal",
    "account statement", "verify your email", "confirm your",
    "you have been selected", "congratulations you",
    "weekly digest", "monthly digest", "daily digest",
    "new follower", "liked your", "commented on",
    "your google", "google play", "apple id",
    "security alert", "sign-in attempt", "unusual activity",
    "password reset", "reset your password",
    "you're invited", "invitation to join",
]


def _is_junk_email(sender: str, subject: str) -> bool:
    """
    Return True if the email is almost certainly automated/marketing
    and not worth extracting tasks from.

    Checks:
      1. Sender local-part (before @) matches known junk patterns
      2. Subject contains marketing/automated phrases
    """
    sender_lower  = sender.lower()
    subject_lower = subject.lower()

    # Extract local part from "Name <local@domain.com>" or "local@domain.com"
    import re
    match = re.search(r'[\w.+-]+@', sender_lower)
    if match:
        local_part = match.group(0).rstrip("@")
        for junk in _JUNK_SENDER_DOMAINS:
            if junk in local_part:
                return True

    # Subject pattern check
    for pat in _JUNK_SUBJECT_PATTERNS:
        if pat in subject_lower:
            return True

    return False


def fetch_emails(creds_dict: dict, max_results: int = 10) -> List[dict]:
    """
    Fetch inbox emails, skipping obvious automated/marketing senders.

    Strategy: fetch 2× the requested count from Gmail (cheap — metadata only),
    filter out junk at the header level (no body fetch needed for junk),
    then fetch full bodies only for the emails that pass the filter.
    This keeps API calls low and avoids sending newsletter noise to the NLP pipeline.
    """
    fetch_count = max_results * 2  # over-fetch to account for junk filtering
    data = _gmail_get(
        creds_dict,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        {
            "maxResults": fetch_count,
            "labelIds": "INBOX",
            # exclude trash, spam, promotions, social, updates tabs
            "q": "-in:trash -in:spam -category:promotions -category:social -category:updates",
        },
    )
    emails = []
    for msg in data.get("messages", []):
        if len(emails) >= max_results:
            break
        try:
            # Fetch metadata only first (cheap) to check sender/subject
            md_meta = _gmail_get(
                creds_dict,
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                {"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            headers  = {h["name"]: h["value"] for h in md_meta.get("payload", {}).get("headers", [])}
            sender   = headers.get("From", "")
            subject  = headers.get("Subject", "(No Subject)")
            date     = headers.get("Date", "")

            if _is_junk_email(sender, subject):
                logger.debug("Skipping junk email: from=%s subject=%s", sender, subject[:60])
                continue

            # Passed filter — fetch full body
            md_full = _gmail_get(
                creds_dict,
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                {"format": "full"},
            )
            emails.append({
                "id":      msg["id"],
                "subject": subject,
                "from":    sender,
                "date":    date,
                "body":    _extract_body(md_full["payload"])[:3000],
                "snippet": md_full.get("snippet", ""),
            })
        except Exception as e:
            logger.warning("Email %s failed: %s", msg["id"], e)
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

    # Remove junk lines
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
        if len(low) < 15:
            continue
        if re.match(r'^[\d\s\-_=*#.,:;|/\\]+$', low):
            continue
        if re.match(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$', low):
            continue
        clean_lines.append(line.strip())

    body = " ".join(clean_lines)
    return re.sub(r"\s+", " ", body).strip()[:3000]