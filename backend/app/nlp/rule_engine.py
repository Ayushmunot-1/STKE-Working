"""
STKE Rule-Based Engine
Hybrid pipeline: Rules first → Ollama fills gaps
Taken and adapted from friend's nlp_engine.py with improvements
"""

import re
import logging
from datetime import datetime
from typing import Optional

import spacy
import dateparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

# ── Load models ────────────────────────────────────────────────
nlp = spacy.load("en_core_web_sm")
sentiment_analyzer = SentimentIntensityAnalyzer()

# ── Keyword lists ──────────────────────────────────────────────

URGENT_KEYWORDS = [
    "asap", "urgent", "urgently", "immediately", "right now",
    "critical", "emergency", "right away", "as soon as possible",
]

PRIORITY_HIGH_KEYWORDS = [
    "important", "must", "required", "high priority",
    "need to", "needs to", "have to", "has to",
]

TASK_VERBS = {
    "prepare", "send", "review", "complete", "finish", "submit",
    "deploy", "create", "update", "fix", "build", "write", "design",
    "implement", "test", "check", "schedule", "organize", "plan",
    "assign", "notify", "contact", "call", "email", "report",
    "analyze", "setup", "configure", "install", "develop", "draft",
    "approve", "publish", "upload", "download", "migrate", "debug",
    "document", "deliver", "present", "train", "coordinate",
    "investigate", "resolve", "handle", "ensure", "verify",
    "monitor", "launch", "release", "clean", "share", "book",
    "arrange", "confirm", "follow", "provide", "collect",
}

TASK_PATTERNS = [
    r"(?:need|needs)\s+to\s+",
    r"(?:has|have)\s+to\s+",
    r"(?:should|must|shall)\s+",
    r"(?:please|kindly)\s+",
    r"(?:make\s+sure|ensure)\s+",
    r"(?:don'?t\s+forget|remember)\s+to\s+",
    r"(?:assigned\s+to|responsible\s+for)\s+",
]

DECISION_KEYWORDS = [
    "decided", "agreed", "finalized", "approved", "confirmed",
    "we decided", "we agreed", "we finalized", "we approved",
    "decision was", "team decided", "management approved",
    "it was decided", "consensus", "concluded", "resolved to",
    "we will go with", "we chose", "we selected", "we picked",
]

EVENT_KEYWORDS = [
    "meeting", "standup", "call at", "conference",
    "scheduled for", "scheduled on", "scheduled at",
    "workshop", "webinar", "presentation at",
    "demo at", "sync at", "session at",
    "interview", "appointment",
]

DEPENDENCY_STARTERS = ["after ", "once ", "when "]

STOPWORDS = {
    "the", "a", "an", "and", "or", "but",
    "in", "on", "at", "to", "for", "of", "with", "by"
}

TIME_TOKENS = {
    "tomorrow", "today", "yesterday", "pm", "am",
    "morning", "afternoon", "evening", "night",
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
    "week", "month", "year", "day", "hour", "minute",
    "days", "weeks", "months", "years", "hours", "minutes",
    "by", "before", "after", "until",
}

SKIP_PATTERNS = [
    r"(?i)^(dear|hi|hello|hey|good\s+(morning|afternoon|evening))",
    r"(?i)^(do not reply|don't reply|please do not reply)",
    r"(?i)^(if you need (support|help))",
    r"(?i)^(you (received|are receiving) this)",
    r"(?i)^(this is an? (automated|automatic))",
    r"(?i)^(to unsubscribe|to opt.out|to stop)",
    r"(?i)^(thanks|thank\s+you|regards|sincerely|best|cheers)",
    r"(?i)^(mr\.|mrs\.|ms\.|dr\.|prof\.)",
    r"(?i)^https?://",
    r"(?i)^--+$",
]

# ── Auto-detect context from text ─────────────────────────────

EMAIL_SIGNALS = [
    "dear", "hi ", "hello", "regards", "sincerely",
    "subject:", "from:", "to:", "cc:", "forwarded",
]

CHAT_SIGNALS = [
    "lol", "btw", "fyi", "asap", "haha", "ok ", "okay",
    "👍", "✅", "hey!", "sure,", "sounds good",
]

MEETING_SIGNALS = [
    "standup", "meeting", "agenda", "action item",
    "minutes", "attendees", "discussed", "decided",
]

DOCUMENT_SIGNALS = [
    "section", "chapter", "figure", "table", "appendix",
    "introduction", "conclusion", "abstract", "reference",
]


def detect_context_from_text(text: str) -> str:
    """
    Auto-detect the context type from text content.
    Returns: email | chat | meeting | document | webpage
    """
    lower = text.lower()

    scores = {
        "email": sum(1 for s in EMAIL_SIGNALS if s in lower),
        "chat": sum(1 for s in CHAT_SIGNALS if s in lower),
        "meeting": sum(1 for s in MEETING_SIGNALS if s in lower),
        "document": sum(1 for s in DOCUMENT_SIGNALS if s in lower),
    }

    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best
    return "webpage"


# ── Text helpers ───────────────────────────────────────────────

def normalize_task_title(title: str) -> str:
    """Lowercase → lemmatize → remove stopwords/time words."""
    if not title:
        return ""
    doc = nlp(title.lower())
    tokens = []
    for tok in doc:
        if tok.is_punct or tok.is_space:
            continue
        if tok.text in STOPWORDS or tok.text in TIME_TOKENS:
            continue
        if re.match(r"^\d{1,2}(:\d{2})?(am|pm)?$", tok.text):
            continue
        tokens.append(tok.lemma_)
    return " ".join(tokens).strip()


def extract_deadline(text: str) -> Optional[datetime]:
    """Extract deadline using spaCy NER + dateparser."""
    doc = nlp(text)

    # Try named DATE/TIME entities first
    for ent in doc.ents:
        if ent.label_ in ("DATE", "TIME"):
            parsed = dateparser.parse(ent.text)
            if parsed:
                return parsed

    # Try full text with future preference
    deadline = dateparser.parse(
        text, settings={"PREFER_DATES_FROM": "future"}
    )
    return deadline


def extract_deadline_raw(text: str) -> Optional[str]:
    """Extract raw deadline expression (e.g. 'next Friday', 'by tomorrow')."""
    patterns = [
        r"\b(by|before|until|due|on)\s+"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(by|before|until|due)\s+(today|tomorrow)\b",
        r"\b(next|this)\s+(week|monday|tuesday|wednesday|thursday|friday)\b",
        r"\bend\s+of\s+(day|week|month)\b",
        r"\bin\s+\d+\s+(hour|day|week|month)s?\b",
        r"\b(today|tomorrow|tonight)\b",
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b",
    ]
    lower = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return match.group(0).strip()
    return None


def extract_owner(text: str) -> Optional[str]:
    """Extract person name via spaCy NER with regex fallback."""
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            parts = ent.text.split()
            if parts:
                return parts[0]

    # Regex fallback: "John will/needs to/should..."
    match = re.search(
        r"([A-Z][a-zA-Z]+)\s+(?:will|should|needs?\s+to|has\s+to|must)\s+",
        text
    )
    if match:
        name = match.group(1)
        skip = {
            "The", "This", "That", "They", "We", "You", "It",
            "After", "Once", "When", "Please", "Also", "Then",
        }
        if name not in skip:
            return name
    return None


def detect_urgency(text: str) -> str:
    lower = text.lower()
    for kw in URGENT_KEYWORDS:
        if kw in lower:
            return "urgent"
    return "normal"


def detect_priority(text: str) -> str:
    lower = text.lower()
    for kw in URGENT_KEYWORDS:
        if kw in lower:
            return "critical"
    for kw in PRIORITY_HIGH_KEYWORDS:
        if kw in lower:
            return "high"
    return "medium"


def detect_sentiment(text: str) -> str:
    score = sentiment_analyzer.polarity_scores(text)["compound"]
    if score >= 0.05:
        return "positive"
    elif score <= -0.05:
        return "negative"
    return "neutral"


def _is_passive_voice(sentence: str) -> bool:
    doc = nlp(sentence)
    for i, token in enumerate(doc):
        if token.dep_ in ("auxpass", "nsubjpass"):
            return True
        if (token.lemma_ == "be" and
                i + 1 < len(doc) and doc[i + 1].tag_ == "VBN"):
            return True
    return False


def _is_skip_line(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 3:
        return True
    for pat in SKIP_PATTERNS:
        if re.match(pat, stripped):
            return True
    if stripped.startswith("http"):
        return True
    if "@" in stripped and "." in stripped and " " not in stripped.strip():
        return True
    return False


def _is_dependency_sentence(text: str) -> bool:
    low = text.lower().strip()
    return any(low.startswith(s) for s in DEPENDENCY_STARTERS)


def _extract_clean_title(sentence: str) -> str:
    """Extract a clean concise title from a sentence."""
    cleaned = sentence.strip()

    # Remove greeting prefixes
    cleaned = re.sub(
        r"^(?:Dear\s+\w+[,.]?\s*)", "", cleaned, flags=re.IGNORECASE
    ).strip()

    # Remove date/time phrases
    cleaned = re.sub(
        r"\s*(?:on|for|by|before|until|at)\s+"
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
        r"(?:[,]?\s*\d{1,2}\s+\w+\s+\d{4})?"
        r"(?:\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?",
        "", cleaned, flags=re.IGNORECASE
    ).strip()

    # Remove relative date phrases
    cleaned = re.sub(
        r"\s*(?:by|before|until|on|at)\s+"
        r"(?:tomorrow|today|next\s+\w+)"
        r"(?:\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?",
        "", cleaned, flags=re.IGNORECASE
    ).strip()

    # Remove trailing punctuation
    cleaned = re.sub(r"[.,;!?]+$", "", cleaned).strip()

    # Remove leading filler words
    cleaned = re.sub(
        r"^(?:please|kindly|also|then|and|so|your|the)\s+",
        "", cleaned, flags=re.IGNORECASE
    ).strip()

    # Capitalize and truncate
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    if len(cleaned) > 80:
        cleaned = cleaned[:77] + "..."

    return cleaned


# ── Rule-based sentence classifier ───────────────────────────

def rule_classify(sentence: str) -> dict:
    """
    Classify a sentence using keyword/pattern matching.
    Returns {"type": "TASK"|"EVENT"|"DECISION"|"INFO", "title": "..."}
    """
    sent_lower = sentence.lower().strip()

    if _is_skip_line(sentence):
        return {"type": "INFO", "title": ""}

    if _is_passive_voice(sentence):
        if re.search(r"(?i)scheduled\s+(?:for|on|at)", sent_lower):
            title = _extract_clean_title(sentence)
            return {"type": "EVENT", "title": title or sentence.strip()[:80]}
        return {"type": "INFO", "title": ""}

    # Check DECISION
    for kw in DECISION_KEYWORDS:
        if kw in sent_lower:
            return {"type": "DECISION", "title": sentence.strip()}

    # Check EVENT
    for kw in EVENT_KEYWORDS:
        if kw in sent_lower:
            title = _extract_clean_title(sentence)
            return {"type": "EVENT", "title": title or sentence.strip()[:80]}

    # Check TASK via patterns
    for pattern in TASK_PATTERNS:
        if re.search(pattern, sent_lower):
            title = _extract_clean_title(sentence)
            return {"type": "TASK", "title": title or sentence.strip()[:80]}

    # Check TASK via action verbs
    doc = nlp(sentence)
    for token in doc:
        if (token.pos_ == "VERB" and
                token.lemma_.lower() in TASK_VERBS and
                token.dep_ not in ("auxpass", "agent")):
            title = _extract_clean_title(sentence)
            return {"type": "TASK", "title": title or sentence.strip()[:80]}

    # "will + verb" pattern
    will_match = re.search(r"(?:will|going\s+to)\s+(\w+)", sent_lower)
    if will_match:
        verb = will_match.group(1)
        if verb not in {"be", "have", "get", "do"} and not _is_passive_voice(sentence):
            title = _extract_clean_title(sentence)
            return {"type": "TASK", "title": title or sentence.strip()[:80]}

    return {"type": "INFO", "title": ""}


# ── Dependency extraction ──────────────────────────────────────

def rule_extract_dependency(sentence: str) -> dict:
    """
    Parse dependency from 'After X, do Y' / 'Once X, Y' / 'When X, Y'.
    Returns {"task_a": "prerequisite", "task_b": "dependent"} or empty.
    """
    patterns = [
        r"(?i)^after\s+(.+?),\s*(.+)$",
        r"(?i)^once\s+(.+?),\s*(.+)$",
        r"(?i)^when\s+(.+?),\s*(.+)$",
    ]
    for pat in patterns:
        m = re.match(pat, sentence.strip())
        if m:
            return {
                "task_a": _extract_clean_title(m.group(1).strip()),
                "task_b": _extract_clean_title(m.group(2).strip()),
            }
    return {"task_a": "", "task_b": ""}


# ── Text preprocessor ──────────────────────────────────────────

def preprocess_text(text: str) -> str:
    """Strip signatures, greetings, blank lines."""
    lines = text.split("\n")
    cleaned = []
    in_signature = False

    for line in lines:
        stripped = line.strip()

        if stripped == "--" or re.match(r"^-{2,}$", stripped):
            in_signature = True
            continue
        if in_signature:
            continue

        if re.match(
            r"(?i)^(thanks|thank\s+you|regards|sincerely|best|cheers)",
            stripped
        ):
            in_signature = True
            continue

        if re.match(r"(?i)^(mr\.|mrs\.|ms\.|dr\.|prof\.)", stripped):
            continue
        if stripped.startswith("http"):
            continue

        stripped = re.sub(
            r"^(?:Dear\s+\w+[,.]?\s*)", "", stripped, flags=re.IGNORECASE
        ).strip()
        stripped = re.sub(
            r"^(?:Hi|Hello|Hey)\s+\w*[,.]?\s*",
            "", stripped, flags=re.IGNORECASE
        ).strip()

        if stripped:
            cleaned.append(stripped)

    return " ".join(cleaned)


# ── Main rule-based extraction ─────────────────────────────────

def rule_extract(text: str) -> dict:
    """
    Full rule-based extraction pipeline.
    Returns structured dict with tasks, decisions, dependencies.
    This runs BEFORE Ollama and pre-fills all fields it can detect.
    """
    cleaned = preprocess_text(text)
    doc = nlp(cleaned)

    tasks = []
    decisions = []
    dependencies = []
    processed_deps = set()

    for sent in doc.sents:
        sent_text = sent.text.strip()
        if not sent_text or len(sent_text) < 5:
            continue

        # ── Dependency sentences ──
        if _is_dependency_sentence(sent_text):
            if sent_text in processed_deps:
                continue
            processed_deps.add(sent_text)
            dep = rule_extract_dependency(sent_text)
            if dep["task_a"] and dep["task_b"]:
                dependencies.append({
                    "prerequisite": dep["task_a"],
                    "dependent": dep["task_b"],
                    "raw_text": sent_text,
                })
            continue

        # ── Classify sentence ──
        result = rule_classify(sent_text)
        sent_type = result["type"]
        title = result["title"]

        if sent_type == "INFO":
            continue

        if sent_type == "DECISION":
            decisions.append({"decision_text": sent_text})
            continue

        # ── TASK or EVENT ──
        if not title:
            title = _extract_clean_title(sent_text)
        if not title:
            continue

        deadline = extract_deadline(sent_text)
        deadline_raw = extract_deadline_raw(sent_text)
        owner = extract_owner(sent_text)
        urgency = detect_urgency(sent_text)
        priority = detect_priority(sent_text)
        sentiment = detect_sentiment(sent_text)
        normalized = normalize_task_title(title)

        tasks.append({
            "title": title,
            "normalized_title": normalized,
            "description": sent_text,
            "owner": owner,
            "deadline": deadline,
            "deadline_raw": deadline_raw,
            "priority": priority,
            "urgency": urgency,
            "sentiment": sentiment,
            "type": sent_type,
            "source": "rule_engine",
        })

    return {
        "tasks": tasks,
        "decisions": decisions,
        "dependencies": dependencies,
        "detected_context": detect_context_from_text(text),
    }