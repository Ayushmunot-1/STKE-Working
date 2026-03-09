# ⬡ STKE

## Semantic Task & Knowledge Extractor

A **Chrome extension + FastAPI backend** that automatically extracts **tasks, decisions, and dependencies** from natural language text — emails, chats, meeting notes, web pages — and syncs them to **Google Calendar**.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![Chrome Extension](https://img.shields.io/badge/Chrome-Extension-yellow)
![Google Calendar](https://img.shields.io/badge/Google-Calendar-red)
![SQLite](https://img.shields.io/badge/Database-SQLite-lightgrey)
![NLP](https://img.shields.io/badge/NLP-Rule--Based-purple)

---

# 📌 Project Overview

STKE is a productivity tool that sits in your browser and intelligently reads any text you encounter — **emails, Slack messages, meeting notes, project documents, and web pages** — and extracts **structured, actionable data** from it.

No manual task creation.
No copy-pasting.

Just paste or browse, and **STKE extracts tasks automatically**.

The system uses a **custom rule-based NLP pipeline** built with:

* **spaCy**
* **dateparser**
* **VADER sentiment**

Extracted tasks are:

• Stored in **SQLite**
• Displayed on a **dashboard**
• Synced to **Google Calendar**

---

# 🏗️ Architecture

## System Overview

```
🌐 Chrome Extension
popup.js · content.js · background.js
        ↓
⚡ FastAPI Backend
REST API (localhost:8000)
        ↓
🧠 NLP + SQLite
Rule Engine · Database
```

---

# Backend Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── auth.py
│   │   ├── extract.py
│   │   ├── tasks.py
│   │   ├── gmail.py
│   │   └── calendar.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   └── security.py
│   │
│   ├── models/
│   │   ├── models.py
│   │   └── schemas.py
│   │
│   ├── services/
│   │   ├── extraction_service.py
│   │   ├── gmail_service.py
│   │   └── calendar_service.py
│   │
│   ├── nlp/
│   │   └── rule_engine.py
│   │
│   └── main.py
│
├── dashboard.html
└── stke.db
```

---

# Extension Structure

```
extension/
├── manifest.json
├── popup/
│   ├── popup.html
│   ├── popup.css
│   └── popup.js
│
├── content/
│   ├── content.js
│   └── content.css
│
├── background.js
└── icons/
```

---

# 🧠 NLP Pipeline

STKE uses a **fully local rule-based NLP pipeline**.
No external AI APIs are required.

### Pipeline Steps

| Step | Stage            | Description                                                  |
| ---- | ---------------- | ------------------------------------------------------------ |
| 1    | Preprocessing    | Removes greetings, signatures, URLs                          |
| 2    | Sentence Split   | spaCy splits text into sentences                             |
| 3    | Classification   | Classifies sentences as TASK / EVENT / DECISION / DEPENDENCY |
| 4    | Field Extraction | Extracts owner, deadline, priority                           |
| 5    | Deduplication    | Jaccard similarity removes duplicates                        |
| 6    | Save & Return    | Tasks saved to SQLite and returned via API                   |

---

# ✨ Features

## Core Features

| Feature                | Description                                  |
| ---------------------- | -------------------------------------------- |
| ⚡ Instant Extraction   | Rule-based NLP extracts tasks instantly      |
| ⚖️ Decision Detection  | Detects decisions in text                    |
| 🔗 Dependency Mapping  | Detects task dependencies                    |
| 👤 Owner Assignment    | spaCy NER extracts names                     |
| 📅 Deadline Extraction | dateparser parses natural language dates     |
| 🎯 Priority Detection  | Priority detected using keywords + sentiment |
| 🔁 Deduplication       | Prevents duplicate tasks                     |
| 📍 Context Detection   | Detects email/chat/meeting/document context  |

---

# Dashboard Features

* 📊 Task statistics
* 🔍 Search and filter
* ✏️ Task editing
* ☑️ Bulk delete
* 📈 Analytics charts
* 🌙 Dark/light theme
* 📅 Calendar sync
* 📧 Gmail integration
* ⚡ Quick text extraction

---

# Extension Features

* 📄 Extract tasks from entire page
* ✂️ Extract from selected text
* 📋 Paste and extract
* 📅 Sync tasks to Google Calendar
* 🖥️ Open dashboard
* 📜 View extraction history

---

# 🛠️ Tech Stack

| Technology           | Role                |
| -------------------- | ------------------- |
| FastAPI              | Backend framework   |
| SQLAlchemy           | ORM                 |
| SQLite               | Database            |
| spaCy                | NLP engine          |
| dateparser           | Date extraction     |
| VADER                | Sentiment analysis  |
| Pydantic             | Data validation     |
| JWT                  | Authentication      |
| Chrome Extension MV3 | Browser integration |
| Vanilla JS           | Frontend            |
| Google OAuth2        | Authentication      |
| Gmail API            | Email integration   |
| Google Calendar API  | Calendar sync       |

---

# 🔌 API Endpoints

## Authentication

```
POST /api/v1/auth/register
POST /api/v1/auth/login
GET /api/v1/users/me
```

## Tasks

```
GET    /api/v1/tasks/
POST   /api/v1/tasks/
PATCH  /api/v1/tasks/{id}
DELETE /api/v1/tasks/{id}
POST   /api/v1/tasks/{id}/complete
```

## Extraction

```
POST /api/v1/extract/
GET  /api/v1/extract/health
```

## Gmail

```
GET    /api/v1/gmail/auth
GET    /api/v1/gmail/callback
GET    /api/v1/gmail/status
GET    /api/v1/gmail/emails
POST   /api/v1/gmail/extract/{email_id}
POST   /api/v1/gmail/extract-all
DELETE /api/v1/gmail/disconnect
```

## Calendar

```
GET    /api/v1/calendar/auth
GET    /api/v1/calendar/callback
GET    /api/v1/calendar/status
GET    /api/v1/calendar/events
POST   /api/v1/calendar/sync/{task_id}
POST   /api/v1/calendar/sync-all
DELETE /api/v1/calendar/unsync/{task_id}
```

---

# 🚀 Setup

## Backend

```
cd backend

python -m venv venv
venv\Scripts\activate

pip install fastapi uvicorn sqlalchemy aiosqlite pydantic[email]
pip install python-jose passlib bcrypt==4.0.1
pip install spacy dateparser vaderSentiment
pip install requests python-dotenv

python -m spacy download en_core_web_sm

uvicorn app.main:app --reload --port 8000
```

---

# Chrome Extension Setup

1. Open Chrome → `chrome://extensions`
2. Enable **Developer Mode**
3. Click **Load unpacked**
4. Select the `extension/` folder
5. Pin the STKE extension

---

# Google OAuth Setup

1. Go to **Google Cloud Console**
2. Enable **Gmail API** and **Calendar API**
3. Create OAuth credentials
4. Add redirect URIs:

```
http://localhost:8000/api/v1/gmail/callback
http://localhost:8000/api/v1/calendar/callback
```

---

# 🔄 Workflow

### Extraction Workflow

1. User selects text or page
2. Text sent to `/api/v1/extract`
3. NLP pipeline processes text
4. Tasks saved to SQLite
5. Dashboard displays results

---

### Calendar Sync Workflow

Priority → Calendar color mapping:

| Priority | Color  |
| -------- | ------ |
| Critical | Red    |
| High     | Yellow |
| Medium   | Blue   |
| Low      | Green  |

Events include reminders and **IST timezone support**.

---

# 🗃️ Data Model

### Task

| Field             | Description        |
| ----------------- | ------------------ |
| id                | Primary key        |
| title             | Task title         |
| description       | Original sentence  |
| source_context    | email/chat/meeting |
| assigned_to       | Owner name         |
| deadline          | Parsed deadline    |
| priority          | Task priority      |
| status            | Task status        |
| calendar_event_id | Calendar event ID  |
| created_at        | Timestamp          |

---

# ⚠️ Known Limitations

* Rule-based NLP may miss ambiguous sentences
* Gmail API caching delays
* Dashboard is not SPA
* Backend must run locally

---

# 🗺️ Roadmap

## Completed

* Task extraction
* JWT authentication
* Dashboard analytics
* Gmail integration
* Google Calendar sync
* Chrome extension

## Planned

* CSV/PDF export
* Mobile dashboard
* Email reminders
* Task tagging
* Slack integration
* Advanced analytics

---

# 👤 Author

**Ayush Munot**

Project: **STKE — Semantic Task & Knowledge Extractor**

Built with:

Python • FastAPI • spaCy • Chrome Extension • Google APIs

---

⭐ If you find this project useful, consider **starring the repository**.
