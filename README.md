⬡  STKE
Semantic Task & Knowledge Extractor
A Chrome extension + FastAPI backend that automatically extracts tasks, decisions, and dependencies from natural language text — emails, chats, meeting notes, web pages — and syncs them to Google Calendar.
🐍 Python 3.11	⚡ FastAPI	🌐 Chrome Extension	📅 Google Calendar	📧 Gmail API	🗃️ SQLite	🧠 Rule-Based NLP


📌 Project Overview
STKE is a productivity tool that sits in your browser and intelligently reads any text you encounter — emails, Slack messages, meeting notes, project documents — and extracts structured, actionable data from it. No manual task creation. No copy-pasting. Just paste or browse, and STKE does the rest.

The system uses a custom rule-based NLP pipeline (no Ollama or external AI required) built on spaCy, dateparser, and VADER sentiment analysis. Extracted tasks are stored in a local SQLite database, displayed on a rich dashboard, and can be synced directly to Google Calendar.

🏗️ Architecture
System Overview
🌐 Chrome Extension
popup.js · content.js · background.js	⟷	⚡ FastAPI Backend
localhost:8000 · REST API	⟷	🧠 NLP + SQLite
Rule Engine · Database

Backend File Structure
backend/
├── app/
│   ├── api/
│   │   ├── auth.py          # JWT authentication
│   │   ├── extract.py        # Extraction endpoint
│   │   ├── tasks.py          # Task CRUD
│   │   ├── gmail.py          # Gmail OAuth + fetch
│   │   └── calendar.py       # Google Calendar sync
│   ├── core/
│   │   ├── config.py         # App configuration
│   │   ├── database.py       # Async SQLAlchemy
│   │   └── security.py       # JWT helpers
│   ├── models/
│   │   ├── models.py         # SQLAlchemy ORM models
│   │   └── schemas.py        # Pydantic schemas
│   ├── services/
│   │   ├── extraction_service.py  # Core extraction logic
│   │   ├── gmail_service.py        # Gmail API client
│   │   └── calendar_service.py     # Calendar API client
│   ├── nlp/
│   │   └── rule_engine.py     # NLP pipeline
│   └── main.py               # FastAPI app entry
├── dashboard.html            # Web dashboard (served by FastAPI)
└── stke.db                   # SQLite database

Extension File Structure
extension/
├── manifest.json
├── popup/
│   ├── popup.html
│   ├── popup.css
│   └── popup.js
├── content/
│   ├── content.js
│   └── content.css
├── background.js
└── icons/

🧠 NLP Pipeline
STKE uses a fully local, rule-based NLP pipeline. No external AI APIs are called during extraction — everything runs instantly on your machine.

Pipeline Steps
Step	Stage	Description
1	Preprocessing	Strips greetings, signatures, URLs, email footers, junk lines
2	Sentence Split	spaCy en_core_web_sm splits text into individual sentences
3	Classification	Each sentence is classified as TASK / EVENT / DECISION / DEPENDENCY / INFO using keyword patterns and spaCy POS tagging
4	Field Extraction	Extracts: owner (spaCy NER + regex), deadline (dateparser + NER), priority (keyword rules), urgency (VADER), sentiment
5	Deduplication	Token overlap (Jaccard similarity > 85%) filters duplicate tasks against existing DB records and within the same batch
6	Save & Return	Tasks saved to SQLite. Response includes tasks, decisions, dependencies, processing time, and duplicate count

✨ Features
Core Features
	Feature	Description
⚡	Instant Extraction	Rule-based NLP pipeline extracts tasks in milliseconds — no AI API calls, no Ollama required
⚖️	Decision Detection	Identifies decisions made in text (agreed, decided, approved, confirmed) and displays them alongside tasks
🔗	Dependency Mapping	Detects task dependencies (After X → do Y, Once X → start Y) and shows which tasks block others
👤	Owner Assignment	Automatically extracts person names as task owners using spaCy NER and regex patterns
📅	Deadline Extraction	Parses relative and absolute dates (by Friday, next Monday, end of Q2) using dateparser
🎯	Priority Detection	Assigns critical/high/medium/low priority based on urgency keywords and VADER sentiment
🔁	Deduplication	Jaccard token overlap prevents duplicate tasks across extractions and within the same batch
📍	Context Detection	Auto-detects source context: email, chat, meeting, document, or webpage

Dashboard Features
	Feature	Description
📊	Stats Bar	Total, Pending, Completed, Overdue, Due Soon — all clickable to filter tasks
🔍	Search & Filter	Real-time search + filter by status and priority
✏️	Task Editing	Edit title, priority, status, deadline, assigned_to via modal
☑️	Bulk Delete	Select multiple tasks with checkboxes and delete in one click
📈	Analytics	Priority bar chart, status donut chart, context bar chart, completion rate — all clickable
🌙	Dark/Light Theme	Toggle between dark and light mode, persisted in localStorage
📅	Calendar Sync	Sync individual tasks or all pending tasks to Google Calendar with color coding
📧	Gmail Integration	Connect Gmail, view inbox, extract tasks from individual emails or bulk extract
🔔	In-page Alerts	Slide-in alert system for real-time feedback without browser notifications
⚡	Quick Extract	Sidebar panel for pasting text — shows grouped session cards with tasks, decisions, dependencies

Extension Features
	Feature	Description
📄	Extract from Page	Extracts tasks from entire current browser page
✂️	Extract Selection	Extracts tasks from highlighted/selected text
📋	Paste & Extract	Paste any text directly into the popup for extraction
⚖️	Decisions in Popup	Shows decisions and dependencies in extraction results
📅	Calendar Sync	Sync individual tasks to Google Calendar from the popup
🖥️	Dashboard Button	Opens the full dashboard in a new tab
📜	History View	Shows stats and recent task activity

🛠️ Tech Stack
Technology	Role	Why
FastAPI	Backend Framework	Async Python framework — fast, auto-generates OpenAPI docs, excellent for REST APIs
SQLAlchemy (Async)	ORM	Async database access with SQLite, easy schema migrations
SQLite	Database	Zero-config local database — no server setup required
spaCy	NLP Engine	Named entity recognition (PERSON, DATE), POS tagging, sentence segmentation
dateparser	Date Extraction	Parses natural language dates: 'by Friday', 'next Monday', 'end of Q2'
VADER Sentiment	Sentiment & Urgency	Lightweight sentiment analysis to detect urgency and task priority
Pydantic v2	Data Validation	Request/response schemas with automatic validation and serialization
JWT (python-jose)	Authentication	Stateless token-based auth for API security
Chrome Extension MV3	Browser Integration	Manifest v3 extension for content script injection and popup UI
Vanilla JS	Frontend	No framework dependency — pure JS for dashboard and extension popup
Google OAuth2	Authentication	Pure requests-based OAuth flow for Gmail and Calendar — no google-auth library
Gmail API v1	Email Integration	Fetch inbox emails, extract body text, trigger NLP extraction
Google Calendar API v3	Calendar Sync	Create events with color coding, reminders, and IST timezone support

🔌 API Endpoints
Authentication
Method	Endpoint	Description
POST	/api/v1/auth/register	Register a new user account
POST	/api/v1/auth/login	Login and receive JWT token
GET	/api/v1/users/me	Get current user profile

Tasks
GET    /api/v1/tasks/?skip=0&limit=200   — List all tasks (with filters)
POST   /api/v1/tasks/                    — Create a task manually
PATCH  /api/v1/tasks/{id}                — Update a task
DELETE /api/v1/tasks/{id}                — Delete a task
POST   /api/v1/tasks/{id}/complete       — Mark task complete

Extraction
POST   /api/v1/extract/                  — Extract tasks/decisions/dependencies from text
GET    /api/v1/extract/health            — Check extraction engine status

Gmail
GET    /api/v1/gmail/auth                — Start Gmail OAuth flow
GET    /api/v1/gmail/callback            — OAuth callback
GET    /api/v1/gmail/status              — Check Gmail connection
GET    /api/v1/gmail/emails              — Fetch inbox emails
POST   /api/v1/gmail/extract/{email_id} — Extract tasks from one email
POST   /api/v1/gmail/extract-all        — Extract from 5 recent emails
DELETE /api/v1/gmail/disconnect         — Disconnect Gmail

Google Calendar
GET    /api/v1/calendar/auth             — Start Calendar OAuth flow
GET    /api/v1/calendar/callback         — OAuth callback
GET    /api/v1/calendar/status           — Check Calendar connection
GET    /api/v1/calendar/events           — List upcoming events
POST   /api/v1/calendar/sync/{task_id}  — Sync one task to Calendar
POST   /api/v1/calendar/sync-all        — Sync all pending tasks
DELETE /api/v1/calendar/unsync/{task_id}— Remove Calendar event
DELETE /api/v1/calendar/disconnect      — Disconnect Calendar

🚀 Setup & Installation
Prerequisites
•	Python 3.11+
•	Node.js (for development)
•	Google Chrome browser
•	Google Cloud project with Gmail API and Calendar API enabled

Backend Setup
# 1. Clone and navigate
cd E:\working\stke\backend

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install fastapi uvicorn sqlalchemy aiosqlite pydantic[email]
pip install python-jose passlib bcrypt==4.0.1
pip install spacy dateparser vaderSentiment
pip install requests python-dotenv
python -m spacy download en_core_web_sm

# 4. Create .env file
SECRET_KEY=your_secret_key
DATABASE_URL=sqlite+aiosqlite:///./stke.db

# 5. Start server (development)
uvicorn app.main:app --reload --port 8000

# 5. Start server (production / normal use)
uvicorn app.main:app --port 8000

Extension Setup
•	Open Chrome → chrome://extensions/
•	Enable Developer Mode (top right toggle)
•	Click Load unpacked
•	Select the extension/ folder
•	Pin STKE from the extensions toolbar

Google OAuth Setup
•	Go to console.cloud.google.com
•	Create a new project
•	Enable Gmail API and Google Calendar API
•	Create OAuth 2.0 Client ID credentials
•	Add authorized redirect URIs:
◦	http://localhost:8000/api/v1/gmail/callback
◦	http://localhost:8000/api/v1/calendar/callback
•	Add your Gmail as a test user
•	Set CLIENT_ID and CLIENT_SECRET in your calendar_service.py and gmail_service.py

🔄 Workflow
Extraction Workflow
1	User pastes text or browses to a page → triggers extraction via popup or dashboard
2	POST /api/v1/extract/ → text sent to FastAPI backend
3	rule_extract() runs: preprocess → sentence split → classify → extract fields
4	Deduplication against existing DB tasks (Jaccard similarity)
5	Tasks saved to SQLite with reminders created for tasks with deadlines
6	Response returned: tasks + decisions + dependencies + processing time
7	Dashboard displays session card grouped by source, with decisions/dependencies tied to related tasks

Calendar Sync Workflow
•	User clicks 📅 on a task OR clicks Sync All Tasks
•	POST /api/v1/calendar/sync/{task_id} called
•	Event created with priority color coding:
◦	🔴 Critical → Red (colorId: 11)
◦	🟡 High → Yellow (colorId: 5)
◦	🔵 Medium → Blue (colorId: 7)
◦	🟢 Low → Green (colorId: 10)
•	1-hour and 1-day popup reminders added to each event
•	Tasks without deadlines → scheduled tomorrow at 9:00 AM IST
•	calendar_event_id stored on task for tracking

🗃️ Data Models
Task
Field	Type	Description
id	Integer	Primary key
title	String(500)	Task title
description	Text	Original sentence
raw_text	Text	Source text
source_context	String	email/chat/meeting/document/webpage
assigned_to	String	Owner name (extracted)
deadline	DateTime	Parsed deadline
deadline_raw	String	Raw deadline text (e.g. 'by Friday')
priority	Enum	low/medium/high/critical
status	Enum	pending/in_progress/completed/cancelled
confidence_score	Float	NLP confidence (0.0–1.0)
calendar_event_id	String	Google Calendar event ID
calendar_synced	Boolean	Whether synced to Calendar
owner_id	FK → User	Who extracted this task
created_at	DateTime	Creation timestamp
updated_at	DateTime	Last update timestamp

⚠️ Known Limitations
•	Extraction is rule-based — complex or ambiguous sentences may not be detected
•	Gmail API has a short server-side cache — deletions may take 2-3 minutes to reflect
•	Calendar events created without deadlines default to tomorrow 9:00 AM IST
•	The dashboard is served as a static file from FastAPI — not a SPA framework
•	Extension only works when backend is running locally on port 8000
•	Google OAuth requires adding test users manually in Google Cloud Console

🗺️ Roadmap
Completed
•	✅ Core rule-based extraction (tasks, decisions, dependencies)
•	✅ JWT authentication
•	✅ Dashboard with stats, filters, analytics
•	✅ Dark/light theme
•	✅ Gmail OAuth integration
•	✅ Google Calendar sync
•	✅ Chrome extension with popup
•	✅ Bulk delete
•	✅ Click-to-expand task cards
•	✅ Session-grouped extraction results

Planned
•	📤 Export tasks to CSV / PDF
•	📱 Mobile-responsive dashboard
•	🔔 Email reminders for upcoming deadlines
•	🏷️ Task tagging and custom labels
•	👥 Multi-user / team workspace support
•	🔗 Slack integration
•	📊 Advanced analytics with date range filters

👤 Author
Built by Ayush Munot
Project: STKE — Semantic Task & Knowledge Extractor
Stack: Python · FastAPI · spaCy · Chrome Extension · Google APIs

STKE — Built with ❤️ using Python, FastAPI, spaCy, and Vanilla JS
