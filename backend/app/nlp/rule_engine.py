# """
# STKE Rule-Based Engine — v2.0
# Upgrades in this version:
#   - TASK_VERBS split into OWNERSHIP_VERBS + INTERVENTION_VERBS
#   - classify_verb_type() — determines ownership vs intervention
#   - resolve_pronoun_owner() — maps I/we/my → current_user, team/everyone → shared
#   - infer_task_ownership() — chain inference post-processing pass
#   - compute_confidence_score() — replaces hardcoded 0.85
#   - spaCy doc caching — nlp() called once per sentence (4-5x speedup)
#   - spaCy model load wrapped in try/except (no more silent crashes)
#   - detect_sentiment() removed from hot path (was computed, never used)
# """

# import re
# import logging
# from datetime import datetime
# from typing import Optional

# import spacy
# import dateparser
# from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# logger = logging.getLogger(__name__)


# # ── Load models (safe, with error handling) ───────────────────
# try:
#     nlp = spacy.load("en_core_web_sm")
#     logger.info("spaCy model 'en_core_web_sm' loaded successfully.")
# except OSError:
#     nlp = None
#     logger.error(
#         "spaCy model 'en_core_web_sm' not found. "
#         "Run: python -m spacy download en_core_web_sm"
#     )

# sentiment_analyzer = SentimentIntensityAnalyzer()


# # ── Keyword lists ──────────────────────────────────────────────

# URGENT_KEYWORDS = [
#     "asap", "urgent", "urgently", "immediately", "right now",
#     "critical", "emergency", "right away", "as soon as possible",
# ]

# PRIORITY_HIGH_KEYWORDS = [
#     "important", "must", "required", "high priority",
#     "need to", "needs to", "have to", "has to",
# ]

# # ── STEP 1: TASK_VERBS split into two distinct sets ───────────
# #
# # OWNERSHIP_VERBS: Doing this verb makes YOU the artifact owner.
# # The person who performs these actions is responsible for the output.
# # Example: "John will CREATE the report" → John owns the report.
# #
# OWNERSHIP_VERBS = {
#     "create",   "write",    "build",    "develop",  "design",
#     "draft",    "prepare",  "implement","produce",  "compose",
#     "generate", "author",   "construct","establish","formulate",
#     "make",     "rewrite",  "rebuild",  "redo",     "rework",
#     "launch",   "deploy",   "release",  "publish",  "deliver",
#     "submit",   "present",  "send",     "upload",   "migrate",
#     "install",  "configure","setup",    "schedule", "organize",
#     "plan",     "arrange",  "book",     "fix",      "debug",
#     "resolve",  "complete", "finish",   "update",   "document",
#     "train",    "analyze",  "report",   "collect",  "provide",
#     "share",    "notify",   "contact",  "call",     "email",
#     "coordinate","handle",  "manage",   "lead",     "run",
#     "execute",  "process",  "clean",    "download", "assign",
# }

# # INTERVENTION_VERBS: Doing this verb does NOT transfer artifact ownership.
# # The person acts ON someone else's output but doesn't take ownership.
# # Example: "Sarah will REVIEW the report" → John still owns the report.
# #
# INTERVENTION_VERBS = {
#     "review",   "approve",  "check",    "validate", "proofread",
#     "verify",   "test",     "inspect",  "assess",   "evaluate",
#     "sign",     "authorize","confirm",  "acknowledge","endorse",
#     "audit",    "examine",  "screen",   "scan",     "monitor",
#     "oversee",  "supervise","observe",  "follow",   "track",
#     "ensure",   "investigate","look",   "read",     "attend",
# }

# # Combined for backward compatibility — used in rule_classify()
# ALL_TASK_VERBS = OWNERSHIP_VERBS | INTERVENTION_VERBS


# # ── Pronoun resolution sets ────────────────────────────────────

# # These pronouns almost always refer to the logged-in user
# SELF_PRONOUNS = {"i", "we", "my", "our", "us", "me", "myself", "ourselves"}

# # These indicate a role, not a specific name
# ROLE_WORDS = {
#     "manager", "management", "director", "lead", "head", "supervisor",
#     "cto", "ceo", "cfo", "vp", "president", "founder", "owner",
#     "admin", "administrator", "coordinator", "stakeholder", "client",
#     "customer", "hr", "finance", "legal", "ops", "operations",
# }

# # These indicate shared/group ownership — no individual owner
# GROUP_WORDS = {
#     "team", "everyone", "everybody", "all", "group", "department",
#     "company", "organization", "org", "staff", "crew", "squad",
#     "committee", "board", "members", "colleagues", "folks",
# }


# # ── Context detection signals ──────────────────────────────────

# TASK_PATTERNS = [
#     r"(?:need|needs)\s+to\s+",
#     r"(?:has|have)\s+to\s+",
#     r"(?:should|must|shall)\s+",
#     r"(?:please|kindly)\s+",
#     r"(?:make\s+sure|ensure)\s+",
#     r"(?:don'?t\s+forget|remember)\s+to\s+",
#     r"(?:assigned\s+to|responsible\s+for)\s+",
# ]

# DECISION_KEYWORDS = [
#     "decided", "agreed", "finalized", "approved", "confirmed",
#     "we decided", "we agreed", "we finalized", "we approved",
#     "decision was", "team decided", "management approved",
#     "it was decided", "consensus", "concluded", "resolved to",
#     "we will go with", "we chose", "we selected", "we picked",
# ]

# EVENT_KEYWORDS = [
#     "meeting", "standup", "call at", "conference",
#     "scheduled for", "scheduled on", "scheduled at",
#     "workshop", "webinar", "presentation at",
#     "demo at", "sync at", "session at",
#     "interview", "appointment",
# ]

# DEPENDENCY_STARTERS = ["after ", "once ", "when "]

# STOPWORDS = {
#     "the", "a", "an", "and", "or", "but",
#     "in", "on", "at", "to", "for", "of", "with", "by"
# }

# TIME_TOKENS = {
#     "tomorrow", "today", "yesterday", "pm", "am",
#     "morning", "afternoon", "evening", "night",
#     "monday", "tuesday", "wednesday", "thursday",
#     "friday", "saturday", "sunday",
#     "week", "month", "year", "day", "hour", "minute",
#     "days", "weeks", "months", "years", "hours", "minutes",
#     "by", "before", "after", "until",
# }

# SKIP_PATTERNS = [
#     r"(?i)^(dear|hi|hello|hey|good\s+(morning|afternoon|evening))",
#     r"(?i)^(do not reply|don't reply|please do not reply)",
#     r"(?i)^(if you need (support|help))",
#     r"(?i)^(you (received|are receiving) this)",
#     r"(?i)^(this is an? (automated|automatic))",
#     r"(?i)^(to unsubscribe|to opt.out|to stop)",
#     r"(?i)^(thanks|thank\s+you|regards|sincerely|best|cheers)",
#     r"(?i)^(mr\.|mrs\.|ms\.|dr\.|prof\.)",
#     r"(?i)^https?://",
#     r"(?i)^--+$",
# ]

# EMAIL_SIGNALS    = ["dear", "hi ", "hello", "regards", "sincerely", "subject:", "from:", "to:", "cc:", "forwarded"]
# CHAT_SIGNALS     = ["lol", "btw", "fyi", "asap", "haha", "ok ", "okay", "👍", "✅", "hey!", "sure,", "sounds good"]
# MEETING_SIGNALS  = ["standup", "meeting", "agenda", "action item", "minutes", "attendees", "discussed", "decided"]
# DOCUMENT_SIGNALS = ["section", "chapter", "figure", "table", "appendix", "introduction", "conclusion", "abstract", "reference"]


# # ══════════════════════════════════════════════════════════════
# #  STEP 2: classify_verb_type()
# # ══════════════════════════════════════════════════════════════

# def classify_verb_type(verb_lemma: str) -> str:
#     """
#     Given a verb lemma, return its type:
#       - 'ownership'    → person performing this becomes/remains artifact owner
#       - 'intervention' → person acts on artifact but does NOT take ownership
#       - 'unknown'      → verb not in either list

#     Usage:
#         classify_verb_type("create")   → "ownership"
#         classify_verb_type("review")   → "intervention"
#         classify_verb_type("sneeze")   → "unknown"
#     """
#     v = verb_lemma.lower().strip()
#     if v in OWNERSHIP_VERBS:
#         return "ownership"
#     if v in INTERVENTION_VERBS:
#         return "intervention"
#     return "unknown"


# # ══════════════════════════════════════════════════════════════
# #  STEP 3: resolve_pronoun_owner()
# # ══════════════════════════════════════════════════════════════

# def resolve_pronoun_owner(text: str, current_user: str) -> tuple[Optional[str], str]:
#     """
#     Detect ambiguous owner words in a sentence and resolve them.

#     Returns: (owner, owner_type)

#     owner_type values:
#         'self'   → pronoun maps to logged-in user (I/we/my/our)
#         'role'   → role word found (manager/CTO/team lead)
#         'shared' → group word found (team/everyone/all)
#         None     → no pronoun/role/group word found — caller handles it

#     Examples:
#         "We need to submit the report"    → (current_user, 'self')
#         "The manager should approve it"   → ('manager', 'role')
#         "Everyone must review the doc"    → (None, 'shared')
#         "John will fix the bug"           → (None, None)  ← no pronoun, caller uses NER
#     """
#     lower = text.lower()
#     words = set(re.findall(r"\b\w+\b", lower))

#     # Check self-pronouns first (highest priority)
#     if words & SELF_PRONOUNS:
#         return current_user, "self"

#     # Check role words
#     matched_roles = words & ROLE_WORDS
#     if matched_roles:
#         # Return the first matched role word as the owner label
#         role = next(iter(matched_roles))
#         return role, "role"

#     # Check group words
#     if words & GROUP_WORDS:
#         return None, "shared"

#     # No pronoun/role/group found — NER will handle it
#     return None, None


# # ══════════════════════════════════════════════════════════════
# #  STEP 4: infer_task_ownership()
# # ══════════════════════════════════════════════════════════════

# def infer_task_ownership(tasks: list, current_user: str) -> list:
#     """
#     Post-processing pass that resolves ownership for every extracted task.

#     This runs AFTER rule_extract() has built the raw task list.
#     It applies the Artifact Ownership + Chain Inference model:

#     Rules (in priority order):
#       1. Explicit PERSON name from NER          → owner_type = 'explicit'
#       2. Pronoun resolves to self (I/we/my)     → owner_type = 'self'
#       3. Role word (manager/CTO)                → owner_type = 'role'
#       4. Group word (team/everyone)             → owner_type = 'shared'
#       5. Intervention verb on known artifact    → artifact_owner keeps ownership
#          intervention_by = the reviewer/approver
#       6. Chain inference from last artifact     → owner_type = 'inferred', owner_inferred=True
#       7. Complete fallback                      → current_user, owner_inferred=True

#     Mutates and returns the task list with new fields:
#         owner          : str | None  (resolved owner name)
#         owner_type     : str         ('explicit'|'self'|'role'|'shared'|'inferred'|'fallback')
#         owner_inferred : bool        (True = inferred, needs user verification)
#         verb_type      : str         ('ownership'|'intervention'|'unknown')
#         intervention_by: str | None  (person doing review/approve if intervention)
#     """
#     if not tasks:
#         return tasks

#     # Tracks the current artifact owner as we walk through the task chain
#     # Key insight: ownership only transfers on OWNERSHIP verbs, not intervention verbs
#     last_artifact_owner: Optional[str] = None

#     for task in tasks:
#         raw_owner = task.get("owner")        # from extract_owner() — NER result
#         sent_text = task.get("description", "")
#         verb_lemma = task.get("verb_lemma", "")  # populated by upgraded rule_classify()

#         # ── Classify the verb type ──
#         verb_type = classify_verb_type(verb_lemma) if verb_lemma else "unknown"
#         task["verb_type"] = verb_type

#         # ── Rule 1: Explicit PERSON name from NER ──
#         if raw_owner and raw_owner not in SELF_PRONOUNS:
#             # Verify it's not actually a role/group word masquerading as a name
#             if raw_owner.lower() in ROLE_WORDS:
#                 task["owner"] = raw_owner.lower()
#                 task["owner_type"] = "role"
#                 task["owner_inferred"] = False
#                 task["intervention_by"] = None
#             elif raw_owner.lower() in GROUP_WORDS:
#                 task["owner"] = None
#                 task["owner_type"] = "shared"
#                 task["owner_inferred"] = False
#                 task["intervention_by"] = None
#             else:
#                 # Genuine person name
#                 if verb_type == "intervention":
#                     # Intervention: reviewer doesn't take artifact ownership
#                     # The artifact owner stays; intervention_by = this person
#                     task["owner"] = last_artifact_owner or current_user
#                     task["owner_type"] = "explicit" if last_artifact_owner else "fallback"
#                     task["owner_inferred"] = last_artifact_owner is None
#                     task["intervention_by"] = raw_owner
#                 else:
#                     # Ownership verb: this person takes/confirms ownership
#                     task["owner"] = raw_owner
#                     task["owner_type"] = "explicit"
#                     task["owner_inferred"] = False
#                     task["intervention_by"] = None
#                     last_artifact_owner = raw_owner  # update chain
#             continue

#         # ── Rule 2-4: Pronoun / Role / Group resolution ──
#         pronoun_owner, pronoun_type = resolve_pronoun_owner(sent_text, current_user)

#         if pronoun_type == "self":
#             task["owner"] = current_user
#             task["owner_type"] = "self"
#             task["owner_inferred"] = False
#             task["intervention_by"] = None
#             if verb_type != "intervention":
#                 last_artifact_owner = current_user
#             continue

#         if pronoun_type == "role":
#             task["owner"] = pronoun_owner   # e.g. "manager"
#             task["owner_type"] = "role"
#             task["owner_inferred"] = False
#             task["intervention_by"] = None
#             continue

#         if pronoun_type == "shared":
#             task["owner"] = None
#             task["owner_type"] = "shared"
#             task["owner_inferred"] = False
#             task["intervention_by"] = None
#             continue

#         # ── Rule 5 & 6: No explicit owner — use chain inference ──
#         if last_artifact_owner:
#             task["owner"] = last_artifact_owner
#             task["owner_type"] = "inferred"
#             task["owner_inferred"] = True
#             task["intervention_by"] = None
#             # Don't update last_artifact_owner — chain continues from same person
#         else:
#             # ── Rule 7: Complete fallback ──
#             task["owner"] = current_user
#             task["owner_type"] = "fallback"
#             task["owner_inferred"] = True
#             task["intervention_by"] = None
#             last_artifact_owner = current_user

#     return tasks


# # ══════════════════════════════════════════════════════════════
# #  compute_confidence_score() — replaces hardcoded 0.85
# # ══════════════════════════════════════════════════════════════

# def compute_confidence_score(signals: dict) -> float:
#     """
#     Compute a real confidence score based on how many extraction
#     signals fired successfully for this task.

#     signals dict keys (all bool):
#         pattern_matched  : TASK_PATTERN regex matched
#         verb_matched     : verb found in OWNERSHIP or INTERVENTION set
#         owner_found      : explicit person name extracted
#         deadline_found   : deadline successfully parsed
#         owner_inferred   : ownership was inferred (reduces confidence)
#         verb_type_known  : verb type is ownership or intervention (not unknown)

#     Score breakdown (max 1.0):
#         Base classification   0.40  (always — sentence passed classifier)
#         Pattern match         +0.15
#         Verb match            +0.15
#         Owner found           +0.15
#         Deadline found        +0.10
#         Verb type known       +0.05
#         Owner inferred        -0.15 (penalty — user should verify)

#     Examples:
#         Pattern + verb + owner + deadline → 0.40+0.15+0.15+0.15+0.10 = 0.95
#         Only pattern match                → 0.40+0.15 = 0.55
#         Everything inferred               → 0.40-0.15 = 0.25
#     """
#     score = 0.40  # base — passed classification

#     if signals.get("pattern_matched"):  score += 0.15
#     if signals.get("verb_matched"):     score += 0.15
#     if signals.get("owner_found"):      score += 0.15
#     if signals.get("deadline_found"):   score += 0.10
#     if signals.get("verb_type_known"):  score += 0.05
#     if signals.get("owner_inferred"):   score -= 0.15

#     # Clamp between 0.10 and 1.0
#     return round(max(0.10, min(1.0, score)), 2)


# # ══════════════════════════════════════════════════════════════
# #  Utility functions (unchanged from v1, except doc caching)
# # ══════════════════════════════════════════════════════════════

# def detect_context_from_text(text: str) -> str:
#     """Auto-detect context type. Returns: email|chat|meeting|document|webpage"""
#     lower = text.lower()
#     scores = {
#         "email":    sum(1 for s in EMAIL_SIGNALS    if s in lower),
#         "chat":     sum(1 for s in CHAT_SIGNALS     if s in lower),
#         "meeting":  sum(1 for s in MEETING_SIGNALS  if s in lower),
#         "document": sum(1 for s in DOCUMENT_SIGNALS if s in lower),
#     }
#     best = max(scores, key=scores.get)
#     return best if scores[best] >= 2 else "webpage"


# def normalize_task_title(title: str) -> str:
#     """Lowercase → lemmatize → remove stopwords/time words."""
#     if not title or not nlp:
#         return ""
#     doc = nlp(title.lower())
#     tokens = []
#     for tok in doc:
#         if tok.is_punct or tok.is_space:
#             continue
#         if tok.text in STOPWORDS or tok.text in TIME_TOKENS:
#             continue
#         if re.match(r"^\d{1,2}(:\d{2})?(am|pm)?$", tok.text):
#             continue
#         tokens.append(tok.lemma_)
#     return " ".join(tokens).strip()


# def extract_deadline(doc) -> Optional[datetime]:
#     """
#     Extract deadline from a pre-computed spaCy doc.
#     CHANGED: now accepts a doc object instead of raw text (caching fix).
#     """
#     # Try named DATE/TIME entities first
#     for ent in doc.ents:
#         if ent.label_ in ("DATE", "TIME"):
#             parsed = dateparser.parse(ent.text)
#             if parsed:
#                 return parsed

#     # Try full sentence text with future preference
#     return dateparser.parse(doc.text, settings={"PREFER_DATES_FROM": "future"})


# def extract_deadline_raw(text: str) -> Optional[str]:
#     """Extract raw deadline expression (e.g. 'next Friday', 'by tomorrow')."""
#     patterns = [
#         r"\b(by|before|until|due|on)\s+"
#         r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
#         r"\b(by|before|until|due)\s+(today|tomorrow)\b",
#         r"\b(next|this)\s+(week|monday|tuesday|wednesday|thursday|friday)\b",
#         r"\bend\s+of\s+(day|week|month)\b",
#         r"\bin\s+\d+\s+(hour|day|week|month)s?\b",
#         r"\b(today|tomorrow|tonight)\b",
#         r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b",
#     ]
#     lower = text.lower()
#     for pattern in patterns:
#         match = re.search(pattern, lower)
#         if match:
#             return match.group(0).strip()
#     return None


# def extract_owner(doc) -> Optional[str]:
#     """
#     Extract person name via spaCy NER with regex fallback.
#     CHANGED: now accepts a doc object instead of raw text (caching fix).
#     """
#     for ent in doc.ents:
#         if ent.label_ == "PERSON":
#             # Return full name, not just first name
#             return ent.text.strip()

#     # Regex fallback: "John will/needs to/should..."
#     match = re.search(
#         r"([A-Z][a-zA-Z]+)\s+(?:will|should|needs?\s+to|has\s+to|must)\s+",
#         doc.text
#     )
#     if match:
#         name = match.group(1)
#         skip = {
#             "The", "This", "That", "They", "We", "You", "It",
#             "After", "Once", "When", "Please", "Also", "Then",
#         }
#         if name not in skip:
#             return name
#     return None


# def detect_urgency(text: str) -> str:
#     lower = text.lower()
#     return "urgent" if any(kw in lower for kw in URGENT_KEYWORDS) else "normal"


# def detect_priority(text: str) -> str:
#     lower = text.lower()
#     if any(kw in lower for kw in URGENT_KEYWORDS):
#         return "critical"
#     if any(kw in lower for kw in PRIORITY_HIGH_KEYWORDS):
#         return "high"
#     return "medium"


# def _is_passive_voice(doc) -> bool:
#     """
#     Check for passive voice in a pre-computed spaCy doc.
#     CHANGED: accepts doc object instead of raw text.
#     """
#     for i, token in enumerate(doc):
#         if token.dep_ in ("auxpass", "nsubjpass"):
#             return True
#         if (token.lemma_ == "be" and
#                 i + 1 < len(doc) and doc[i + 1].tag_ == "VBN"):
#             return True
#     return False


# def _is_skip_line(text: str) -> bool:
#     stripped = text.strip()
#     if len(stripped) < 3:
#         return True
#     for pat in SKIP_PATTERNS:
#         if re.match(pat, stripped):
#             return True
#     if stripped.startswith("http"):
#         return True
#     if "@" in stripped and "." in stripped and " " not in stripped.strip():
#         return True
#     return False


# def _is_dependency_sentence(text: str) -> bool:
#     low = text.lower().strip()
#     return any(low.startswith(s) for s in DEPENDENCY_STARTERS)


# def _extract_clean_title(sentence: str) -> str:
#     """Extract a clean concise title from a sentence."""
#     cleaned = sentence.strip()
#     cleaned = re.sub(r"^(?:Dear\s+\w+[,.]?\s*)", "", cleaned, flags=re.IGNORECASE).strip()
#     cleaned = re.sub(
#         r"\s*(?:on|for|by|before|until|at)\s+"
#         r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
#         r"(?:[,]?\s*\d{1,2}\s+\w+\s+\d{4})?"
#         r"(?:\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?",
#         "", cleaned, flags=re.IGNORECASE
#     ).strip()
#     cleaned = re.sub(
#         r"\s*(?:by|before|until|on|at)\s+"
#         r"(?:tomorrow|today|next\s+\w+)"
#         r"(?:\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?",
#         "", cleaned, flags=re.IGNORECASE
#     ).strip()
#     cleaned = re.sub(r"[.,;!?]+$", "", cleaned).strip()
#     cleaned = re.sub(
#         r"^(?:please|kindly|also|then|and|so|your|the)\s+",
#         "", cleaned, flags=re.IGNORECASE
#     ).strip()
#     if cleaned:
#         cleaned = cleaned[0].upper() + cleaned[1:]
#     if len(cleaned) > 80:
#         cleaned = cleaned[:77] + "..."
#     return cleaned


# # ══════════════════════════════════════════════════════════════
# #  Rule-based sentence classifier (upgraded with doc caching)
# # ══════════════════════════════════════════════════════════════

# def rule_classify(sentence: str, doc=None) -> dict:
#     """
#     Classify a sentence using keyword/pattern matching.
#     Returns {
#         "type": "TASK"|"EVENT"|"DECISION"|"INFO",
#         "title": "...",
#         "verb_lemma": "...",       # NEW: the matched verb lemma
#         "pattern_matched": bool,   # NEW: for confidence scoring
#         "verb_matched": bool,      # NEW: for confidence scoring
#     }

#     CHANGED: accepts optional pre-computed doc to avoid re-running nlp().
#     """
#     if not nlp:
#         logger.error("spaCy model not loaded. Cannot classify sentence.")
#         return {"type": "INFO", "title": "", "verb_lemma": "", "pattern_matched": False, "verb_matched": False}

#     sent_lower = sentence.lower().strip()

#     if _is_skip_line(sentence):
#         return {"type": "INFO", "title": "", "verb_lemma": "", "pattern_matched": False, "verb_matched": False}

#     # Use provided doc or compute it (should always be provided from rule_extract)
#     if doc is None:
#         doc = nlp(sentence)

#     if _is_passive_voice(doc):
#         if re.search(r"(?i)scheduled\s+(?:for|on|at)", sent_lower):
#             title = _extract_clean_title(sentence)
#             return {"type": "EVENT", "title": title or sentence.strip()[:80], "verb_lemma": "schedule", "pattern_matched": False, "verb_matched": True}
#         return {"type": "INFO", "title": "", "verb_lemma": "", "pattern_matched": False, "verb_matched": False}

#     # Check DECISION
#     for kw in DECISION_KEYWORDS:
#         if kw in sent_lower:
#             return {"type": "DECISION", "title": sentence.strip(), "verb_lemma": "", "pattern_matched": False, "verb_matched": False}

#     # Check EVENT
#     for kw in EVENT_KEYWORDS:
#         if kw in sent_lower:
#             title = _extract_clean_title(sentence)
#             return {"type": "EVENT", "title": title or sentence.strip()[:80], "verb_lemma": "", "pattern_matched": True, "verb_matched": False}

#     # Check TASK via patterns
#     for pattern in TASK_PATTERNS:
#         if re.search(pattern, sent_lower):
#             title = _extract_clean_title(sentence)
#             # Also find the main verb for verb_type classification
#             verb_lemma = _extract_main_verb_lemma(doc)
#             return {"type": "TASK", "title": title or sentence.strip()[:80], "verb_lemma": verb_lemma, "pattern_matched": True, "verb_matched": bool(verb_lemma)}

#     # Check TASK via action verbs (using cached doc — no extra nlp() call)
#     for token in doc:
#         if (token.pos_ == "VERB" and
#                 token.lemma_.lower() in ALL_TASK_VERBS and
#                 token.dep_ not in ("auxpass", "agent")):
#             title = _extract_clean_title(sentence)
#             return {"type": "TASK", "title": title or sentence.strip()[:80], "verb_lemma": token.lemma_.lower(), "pattern_matched": False, "verb_matched": True}

#     # "will + verb" pattern
#     will_match = re.search(r"(?:will|going\s+to)\s+(\w+)", sent_lower)
#     if will_match:
#         verb = will_match.group(1)
#         if verb not in {"be", "have", "get", "do"} and not _is_passive_voice(doc):
#             title = _extract_clean_title(sentence)
#             return {"type": "TASK", "title": title or sentence.strip()[:80], "verb_lemma": verb, "pattern_matched": False, "verb_matched": verb in ALL_TASK_VERBS}

#     return {"type": "INFO", "title": "", "verb_lemma": "", "pattern_matched": False, "verb_matched": False}


# def _extract_main_verb_lemma(doc) -> str:
#     """Extract the main action verb lemma from a pre-computed doc."""
#     for token in doc:
#         if token.pos_ == "VERB" and token.dep_ not in ("auxpass", "agent"):
#             if token.lemma_.lower() in ALL_TASK_VERBS:
#                 return token.lemma_.lower()
#     return ""


# # ══════════════════════════════════════════════════════════════
# #  Dependency extraction (unchanged)
# # ══════════════════════════════════════════════════════════════

# def rule_extract_dependency(sentence: str) -> dict:
#     patterns = [
#         r"(?i)^after\s+(.+?),\s*(.+)$",
#         r"(?i)^once\s+(.+?),\s*(.+)$",
#         r"(?i)^when\s+(.+?),\s*(.+)$",
#     ]
#     for pat in patterns:
#         m = re.match(pat, sentence.strip())
#         if m:
#             return {
#                 "task_a": _extract_clean_title(m.group(1).strip()),
#                 "task_b": _extract_clean_title(m.group(2).strip()),
#             }
#     return {"task_a": "", "task_b": ""}


# # ══════════════════════════════════════════════════════════════
# #  Text preprocessor (unchanged)
# # ══════════════════════════════════════════════════════════════

# def preprocess_text(text: str) -> str:
#     """Strip signatures, greetings, blank lines."""
#     lines = text.split("\n")
#     cleaned = []
#     in_signature = False

#     for line in lines:
#         stripped = line.strip()

#         if stripped == "--" or re.match(r"^-{2,}$", stripped):
#             in_signature = True
#             continue
#         if in_signature:
#             continue
#         if re.match(r"(?i)^(thanks|thank\s+you|regards|sincerely|best|cheers)", stripped):
#             in_signature = True
#             continue
#         if re.match(r"(?i)^(mr\.|mrs\.|ms\.|dr\.|prof\.)", stripped):
#             continue
#         if stripped.startswith("http"):
#             continue

#         stripped = re.sub(r"^(?:Dear\s+\w+[,.]?\s*)", "", stripped, flags=re.IGNORECASE).strip()
#         stripped = re.sub(r"^(?:Hi|Hello|Hey)\s+\w*[,.]?\s*", "", stripped, flags=re.IGNORECASE).strip()

#         if stripped:
#             cleaned.append(stripped)

#     return " ".join(cleaned)


# # ══════════════════════════════════════════════════════════════
# #  MAIN EXTRACTION PIPELINE — rule_extract()
# #  Upgraded: doc caching, verb_lemma, confidence scoring,
# #            ownership resolution integrated
# # ══════════════════════════════════════════════════════════════

# def rule_extract(text: str, current_user: str = "current_user") -> dict:
#     """
#     Full rule-based extraction pipeline.
#     Returns structured dict with tasks, decisions, dependencies.

#     CHANGED in v2.0:
#       - current_user param added for ownership resolution
#       - nlp() called ONCE per sentence (doc cached and passed to all helpers)
#       - verb_lemma and confidence_score computed per task
#       - infer_task_ownership() post-processing applied
#       - detect_sentiment() removed from hot path
#     """
#     if not nlp:
#         logger.error("Cannot extract — spaCy model not loaded.")
#         return {"tasks": [], "decisions": [], "dependencies": [], "detected_context": "unknown"}

#     cleaned = preprocess_text(text)
#     doc = nlp(cleaned)   # ← outer doc for sentence splitting only

#     tasks = []
#     decisions = []
#     dependencies = []
#     processed_deps = set()

#     for sent in doc.sents:
#         sent_text = sent.text.strip()
#         if not sent_text or len(sent_text) < 5:
#             continue

#         # ── Dependency sentences ──
#         if _is_dependency_sentence(sent_text):
#             if sent_text in processed_deps:
#                 continue
#             processed_deps.add(sent_text)
#             dep = rule_extract_dependency(sent_text)
#             if dep["task_a"] and dep["task_b"]:
#                 dependencies.append({
#                     "prerequisite": dep["task_a"],
#                     "dependent": dep["task_b"],
#                     "raw_text": sent_text,
#                 })
#             continue

#         # ── Compute spaCy doc ONCE for this sentence ──
#         # This single doc object is passed to ALL helpers below.
#         # Previously each helper called nlp() separately — 4-5x wasted work.
#         sent_doc = nlp(sent_text)

#         # ── Classify sentence (using cached doc) ──
#         result = rule_classify(sent_text, doc=sent_doc)
#         sent_type = result["type"]
#         title = result["title"]

#         if sent_type == "INFO":
#             continue

#         if sent_type == "DECISION":
#             decisions.append({"decision_text": sent_text})
#             continue

#         # ── TASK or EVENT ──
#         if not title:
#             title = _extract_clean_title(sent_text)
#         if not title:
#             continue

#         # All helpers receive the pre-computed sent_doc — zero extra nlp() calls
#         deadline      = extract_deadline(sent_doc)
#         deadline_raw  = extract_deadline_raw(sent_text)
#         owner         = extract_owner(sent_doc)
#         urgency       = detect_urgency(sent_text)
#         priority      = detect_priority(sent_text)
#         normalized    = normalize_task_title(title)
#         verb_lemma    = result.get("verb_lemma", "")
#         verb_type     = classify_verb_type(verb_lemma)

#         # ── Compute real confidence score ──
#         signals = {
#             "pattern_matched": result.get("pattern_matched", False),
#             "verb_matched":    result.get("verb_matched", False),
#             "owner_found":     owner is not None,
#             "deadline_found":  deadline is not None,
#             "verb_type_known": verb_type in ("ownership", "intervention"),
#             "owner_inferred":  False,   # updated after infer_task_ownership()
#         }
#         confidence = compute_confidence_score(signals)

#         tasks.append({
#             "title":            title,
#             "normalized_title": normalized,
#             "description":      sent_text,
#             "owner":            owner,
#             "owner_type":       None,       # filled by infer_task_ownership()
#             "owner_inferred":   False,      # filled by infer_task_ownership()
#             "intervention_by":  None,       # filled by infer_task_ownership()
#             "verb_lemma":       verb_lemma,
#             "verb_type":        verb_type,
#             "deadline":         deadline,
#             "deadline_raw":     deadline_raw,
#             "priority":         priority,
#             "urgency":          urgency,
#             "confidence":       confidence,
#             "type":             sent_type,
#             "source":           "rule_engine",
#         })

#     # ── STEP 4: Run ownership resolution post-processing ──
#     tasks = infer_task_ownership(tasks, current_user)

#     # ── Recompute confidence after ownership inference ──
#     # (owner_inferred penalty applied now that we know it)
#     for task in tasks:
#         if task.get("owner_inferred"):
#             # Apply the -0.15 penalty for inferred ownership
#             task["confidence"] = round(max(0.10, task["confidence"] - 0.15), 2)

#     return {
#         "tasks":            tasks,
#         "decisions":        decisions,
#         "dependencies":     dependencies,
#         "detected_context": detect_context_from_text(text),
#     }

"""
STKE Rule-Based Engine — v3.0
Purely NLP-based, no LLM dependency.

Changes from v2.0:
  - _custom_deadline_parse(): pre-parser handles EOD/EOM/EOW/COB/ASAP/
    business days/sprint/Q1-Q4 before falling back to dateparser.
  - extract_deadline(): calls _custom_deadline_parse first, then
    spaCy NER + dateparser. Still accepts pre-computed doc (caching intact).
  - extract_deadline_raw(): extended regex set to match new patterns.
  - compute_confidence_score(): adds verb_strength signal — strong verbs
    (deploy/build/submit) score higher than medium (send/update/arrange).
  - OWNERSHIP_VERBS split into STRONG_OWNERSHIP_VERBS + MEDIUM_OWNERSHIP_VERBS.
  - _extract_clean_title(): strips EOD/ASAP/sprint noise from titles.
  - All v2.0 features preserved: doc caching, ownership model,
    OWNERSHIP/INTERVENTION split, infer_task_ownership(),
    resolve_pronoun_owner(), spaCy safe load, spaCy error handling.
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Optional

import spacy
import dateparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)


# ── Load models (safe, with error handling) ───────────────────
try:
    nlp = spacy.load("en_core_web_sm")
    logger.info("spaCy model 'en_core_web_sm' loaded successfully.")
except OSError:
    nlp = None
    logger.error(
        "spaCy model 'en_core_web_sm' not found. "
        "Run: python -m spacy download en_core_web_sm"
    )

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

# ── Verb sets ──────────────────────────────────────────────────
#
# Split into STRONG/MEDIUM within OWNERSHIP for confidence scoring.
# Strong verbs = unambiguous creation/delivery actions → higher confidence.
# Medium verbs = clear task but slightly softer signal → medium confidence.
# INTERVENTION verbs = acts on artifact but does NOT transfer ownership.

STRONG_OWNERSHIP_VERBS = {
    "create",   "write",    "build",    "develop",  "design",
    "draft",    "prepare",  "implement","produce",  "compose",
    "generate", "author",   "construct","formulate","make",
    "rewrite",  "rebuild",  "redo",     "rework",   "launch",
    "deploy",   "release",  "publish",  "deliver",  "submit",
    "present",  "upload",   "migrate",  "install",  "configure",
    "fix",      "debug",    "resolve",  "complete", "finish",
    "document",
}

MEDIUM_OWNERSHIP_VERBS = {
    "send",     "update",   "schedule", "organize", "plan",
    "arrange",  "book",     "train",    "analyze",  "report",
    "collect",  "provide",  "share",    "notify",   "contact",
    "call",     "email",    "coordinate","handle",  "manage",
    "lead",     "run",      "execute",  "process",  "clean",
    "download", "assign",   "setup",
}

OWNERSHIP_VERBS = STRONG_OWNERSHIP_VERBS | MEDIUM_OWNERSHIP_VERBS

INTERVENTION_VERBS = {
    "review",   "approve",  "check",    "validate", "proofread",
    "verify",   "test",     "inspect",  "assess",   "evaluate",
    "sign",     "authorize","confirm",  "acknowledge","endorse",
    "audit",    "examine",  "screen",   "scan",     "monitor",
    "oversee",  "supervise","observe",  "follow",   "track",
    "ensure",   "investigate","look",   "read",     "attend",
}

ALL_TASK_VERBS = OWNERSHIP_VERBS | INTERVENTION_VERBS


# ── Pronoun / role / group resolution sets ────────────────────

SELF_PRONOUNS = {"i", "we", "my", "our", "us", "me", "myself", "ourselves"}

ROLE_WORDS = {
    "manager", "management", "director", "lead", "head", "supervisor",
    "cto", "ceo", "cfo", "vp", "president", "founder", "owner",
    "admin", "administrator", "coordinator", "stakeholder", "client",
    "customer", "hr", "finance", "legal", "ops", "operations",
}

GROUP_WORDS = {
    "team", "everyone", "everybody", "all", "group", "department",
    "company", "organization", "org", "staff", "crew", "squad",
    "committee", "board", "members", "colleagues", "folks",
}


# ── Context detection ──────────────────────────────────────────

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

EMAIL_SIGNALS    = ["dear", "hi ", "hello", "regards", "sincerely", "subject:", "from:", "to:", "cc:", "forwarded"]
CHAT_SIGNALS     = ["lol", "btw", "fyi", "asap", "haha", "ok ", "okay", "👍", "✅", "hey!", "sure,", "sounds good"]
MEETING_SIGNALS  = ["standup", "meeting", "agenda", "action item", "minutes", "attendees", "discussed", "decided"]
DOCUMENT_SIGNALS = ["section", "chapter", "figure", "table", "appendix", "introduction", "conclusion", "abstract", "reference"]


# ══════════════════════════════════════════════════════════════
#  classify_verb_type()
# ══════════════════════════════════════════════════════════════

def classify_verb_type(verb_lemma: str) -> str:
    """
    Returns 'ownership', 'intervention', or 'unknown'.
    Also distinguishes 'strong_ownership' vs 'medium_ownership'
    for use in confidence scoring.
    """
    v = verb_lemma.lower().strip()
    if v in STRONG_OWNERSHIP_VERBS:
        return "strong_ownership"
    if v in MEDIUM_OWNERSHIP_VERBS:
        return "medium_ownership"
    if v in INTERVENTION_VERBS:
        return "intervention"
    return "unknown"


# ══════════════════════════════════════════════════════════════
#  resolve_pronoun_owner()
# ══════════════════════════════════════════════════════════════

def resolve_pronoun_owner(text: str, current_user: str) -> tuple:
    """
    Detect ambiguous owner words and resolve them.
    Returns: (owner, owner_type) where owner_type is
    'self' | 'role' | 'shared' | None
    """
    lower = text.lower()
    words = set(re.findall(r"\b\w+\b", lower))

    if words & SELF_PRONOUNS:
        return current_user, "self"

    matched_roles = words & ROLE_WORDS
    if matched_roles:
        role = next(iter(matched_roles))
        return role, "role"

    if words & GROUP_WORDS:
        return None, "shared"

    return None, None


# ══════════════════════════════════════════════════════════════
#  infer_task_ownership()
# ══════════════════════════════════════════════════════════════

def infer_task_ownership(tasks: list, current_user: str) -> list:
    """
    Post-processing pass that resolves ownership for every task.
    Applies Artifact Ownership + Chain Inference model.
    Mutates and returns the task list with owner_type, owner_inferred,
    verb_type, and intervention_by fields populated.
    """
    if not tasks:
        return tasks

    last_artifact_owner: Optional[str] = None

    for task in tasks:
        raw_owner  = task.get("owner")
        sent_text  = task.get("description", "")
        verb_lemma = task.get("verb_lemma", "")
        verb_type  = classify_verb_type(verb_lemma) if verb_lemma else "unknown"
        task["verb_type"] = verb_type

        # Normalise verb_type to ownership/intervention/unknown for logic
        is_ownership     = verb_type in ("strong_ownership", "medium_ownership")
        is_intervention  = verb_type == "intervention"

        # Rule 1: Explicit PERSON name from NER
        if raw_owner and raw_owner.lower() not in SELF_PRONOUNS:
            if raw_owner.lower() in ROLE_WORDS:
                task["owner"] = raw_owner.lower()
                task["owner_type"] = "role"
                task["owner_inferred"] = False
                task["intervention_by"] = None
            elif raw_owner.lower() in GROUP_WORDS:
                task["owner"] = None
                task["owner_type"] = "shared"
                task["owner_inferred"] = False
                task["intervention_by"] = None
            else:
                if is_intervention:
                    task["owner"] = last_artifact_owner or current_user
                    task["owner_type"] = "explicit" if last_artifact_owner else "fallback"
                    task["owner_inferred"] = last_artifact_owner is None
                    task["intervention_by"] = raw_owner
                else:
                    task["owner"] = raw_owner
                    task["owner_type"] = "explicit"
                    task["owner_inferred"] = False
                    task["intervention_by"] = None
                    last_artifact_owner = raw_owner
            continue

        # Rules 2-4: Pronoun / Role / Group
        pronoun_owner, pronoun_type = resolve_pronoun_owner(sent_text, current_user)

        if pronoun_type == "self":
            task["owner"] = current_user
            task["owner_type"] = "self"
            task["owner_inferred"] = False
            task["intervention_by"] = None
            if is_ownership:
                last_artifact_owner = current_user
            continue

        if pronoun_type == "role":
            task["owner"] = pronoun_owner
            task["owner_type"] = "role"
            task["owner_inferred"] = False
            task["intervention_by"] = None
            continue

        if pronoun_type == "shared":
            task["owner"] = None
            task["owner_type"] = "shared"
            task["owner_inferred"] = False
            task["intervention_by"] = None
            continue

        # Rules 5-6: Chain inference
        if last_artifact_owner:
            task["owner"] = last_artifact_owner
            task["owner_type"] = "inferred"
            task["owner_inferred"] = True
            task["intervention_by"] = None
        else:
            # Rule 7: Fallback
            task["owner"] = current_user
            task["owner_type"] = "fallback"
            task["owner_inferred"] = True
            task["intervention_by"] = None
            last_artifact_owner = current_user

    return tasks


# ══════════════════════════════════════════════════════════════
#  compute_confidence_score()
# ══════════════════════════════════════════════════════════════

def compute_confidence_score(signals: dict) -> float:
    """
    Compute confidence from extraction signals.

    signals dict keys:
        pattern_matched  : TASK_PATTERN regex matched
        verb_matched     : verb found in ALL_TASK_VERBS
        verb_strength    : 'strong' | 'medium' | 'intervention' | 'unknown'
        owner_found      : explicit person name extracted
        deadline_found   : deadline successfully parsed
        owner_inferred   : ownership was inferred (penalty)
        verb_type_known  : verb type is not 'unknown'

    Score breakdown (max 1.0):
        Base                 0.40  (passed classifier)
        Pattern match       +0.12
        Verb match          +0.08
        Verb strength bonus +0.10 (strong) | +0.05 (medium) | 0 (intervention/unknown)
        Owner found         +0.15
        Deadline found      +0.10
        Verb type known     +0.05
        Owner inferred      -0.15 (penalty)
    """
    score = 0.40

    if signals.get("pattern_matched"):  score += 0.12
    if signals.get("verb_matched"):     score += 0.08

    strength = signals.get("verb_strength", "unknown")
    if strength == "strong":            score += 0.10
    elif strength == "medium":          score += 0.05

    if signals.get("owner_found"):      score += 0.15
    if signals.get("deadline_found"):   score += 0.10
    if signals.get("verb_type_known"):  score += 0.05
    if signals.get("owner_inferred"):   score -= 0.15

    return round(max(0.10, min(1.0, score)), 2)


# ══════════════════════════════════════════════════════════════
#  Extended deadline extraction — NEW in v3.0
# ══════════════════════════════════════════════════════════════

def _add_business_days(dt: datetime, n: int) -> datetime:
    """Add n business days (Mon-Fri) to dt."""
    while n > 0:
        dt += timedelta(days=1)
        if dt.weekday() < 5:
            n -= 1
    return dt


def _custom_deadline_parse(text: str) -> Optional[datetime]:
    """
    Pre-parser for expressions dateparser doesn't handle well.
    Returns a datetime if matched, None to fall through to dateparser.

    Handles:
      EOD / end of day / COB today    → today 17:00
      COB tomorrow / end of tomorrow  → tomorrow 17:00
      EOW / end of week               → this Friday 17:00
      EOM / end of month              → last day of month 17:00
      ASAP / as soon as possible      → now + 2 hours
      in N business days              → N business days from now
      before standup/meeting/sprint   → today 09:00
      next/this sprint                → now + 14 days
      Q1/Q2/Q3/Q4 [year]             → last day of that quarter 17:00
    """
    now = datetime.now()
    low = text.lower().strip()

    if re.search(r"\b(eod|end\s+of\s+(?:the\s+)?day|cob\s+today|close\s+of\s+business\s+today)\b", low):
        return now.replace(hour=17, minute=0, second=0, microsecond=0)

    if re.search(r"\b(cob\s+tomorrow|end\s+of\s+tomorrow)\b", low):
        return (now + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)

    if re.search(r"\b(eow|end\s+of\s+(?:the\s+)?week)\b", low):
        days_until_friday = (4 - now.weekday()) % 7 or 7
        return (now + timedelta(days=days_until_friday)).replace(hour=17, minute=0, second=0, microsecond=0)

    if re.search(r"\b(eom|end\s+of\s+(?:the\s+)?month)\b", low):
        if now.month == 12:
            last_day = now.replace(year=now.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            last_day = now.replace(month=now.month + 1, day=1) - timedelta(days=1)
        return last_day.replace(hour=17, minute=0, second=0, microsecond=0)

    if re.search(r"\b(asap|as\s+soon\s+as\s+possible)\b", low):
        return now + timedelta(hours=2)

    bd = re.search(r"\bin\s+(\d+)\s+business\s+days?\b", low)
    if bd:
        return _add_business_days(now, int(bd.group(1)))

    if re.search(r"\bbefore\s+(standup|the\s+meeting|sprint\s+ends?|the\s+call|the\s+demo)\b", low):
        return now.replace(hour=9, minute=0, second=0, microsecond=0)

    if re.search(r"\b(next|this)\s+sprint\b", low):
        return now + timedelta(days=14)

    q = re.search(r"\bq([1-4])\s*(?:\'?(\d{2,4}))?\b", low)
    if q:
        quarter = int(q.group(1))
        yr_raw  = q.group(2)
        year    = now.year
        if yr_raw:
            year = int(yr_raw) if len(yr_raw) == 4 else 2000 + int(yr_raw)
        qem = quarter * 3
        if qem == 12:
            last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(year, qem + 1, 1) - timedelta(days=1)
        return last_day.replace(hour=17, minute=0, second=0, microsecond=0)

    return None


def extract_deadline(doc) -> Optional[datetime]:
    """
    Extract deadline from a pre-computed spaCy doc.
    v3.0: tries _custom_deadline_parse first, then NER + dateparser.
    Still accepts doc object for caching compatibility.
    """
    # 1. Custom pre-parser (EOD, ASAP, business days, sprints, quarters)
    custom = _custom_deadline_parse(doc.text)
    if custom:
        return custom

    # 2. spaCy named entities
    for ent in doc.ents:
        if ent.label_ in ("DATE", "TIME"):
            parsed = dateparser.parse(
                ent.text,
                settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
            )
            if parsed:
                return parsed

    # 3. Full-text dateparser fallback
    return dateparser.parse(
        doc.text,
        settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
    )


def extract_deadline_raw(text: str) -> Optional[str]:
    """
    Extract the raw deadline expression.
    v3.0: extended with EOD/EOW/EOM/COB/ASAP/business days/sprint/quarter patterns.
    """
    patterns = [
        # New in v3.0
        r"\b(eod|end\s+of\s+(?:the\s+)?day|cob(?:\s+today)?|close\s+of\s+business)\b",
        r"\b(eow|end\s+of\s+(?:the\s+)?week)\b",
        r"\b(eom|end\s+of\s+(?:the\s+)?month)\b",
        r"\b(asap|as\s+soon\s+as\s+possible)\b",
        r"\bin\s+\d+\s+business\s+days?\b",
        r"\bbefore\s+(?:standup|the\s+meeting|sprint\s+ends?|the\s+call|the\s+demo)\b",
        r"\b(?:next|this)\s+sprint\b",
        r"\bq[1-4](?:\s*\'?\d{2,4})?\b",
        r"\bcob\s+tomorrow\b",
        r"\bend\s+of\s+tomorrow\b",
        # Existing
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


# ══════════════════════════════════════════════════════════════
#  Utility functions (v2.0, doc-caching preserved)
# ══════════════════════════════════════════════════════════════

def detect_context_from_text(text: str) -> str:
    lower = text.lower()
    scores = {
        "email":    sum(1 for s in EMAIL_SIGNALS    if s in lower),
        "chat":     sum(1 for s in CHAT_SIGNALS     if s in lower),
        "meeting":  sum(1 for s in MEETING_SIGNALS  if s in lower),
        "document": sum(1 for s in DOCUMENT_SIGNALS if s in lower),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "webpage"


def normalize_task_title(title: str) -> str:
    if not title or not nlp:
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


def extract_owner(doc) -> Optional[str]:
    """Extract person name. Accepts pre-computed spaCy doc."""
    # First try spaCy NER (works well for common English names)
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            return ent.text.strip()

    # Regex fallback — catches names spaCy en_core_web_sm misses
    # (single first names, Indian names, etc.)
    # Patterns: "Name will/should/must/needs to/has to/is going to <verb>"
    match = re.search(
        r"([A-Z][a-zA-Z]{1,20})\s+(?:will|should|must|shall|"
        r"needs?\s+to|has\s+to|have\s+to|is\s+going\s+to|"
        r"is\s+responsible\s+for|is\s+assigned\s+to)\s+",
        doc.text
    )
    if match:
        name = match.group(1)
        skip = {
            "The", "This", "That", "They", "We", "You", "It",
            "After", "Once", "When", "Please", "Also", "Then",
            "Make", "Ensure", "Note", "See", "Let", "All",
        }
        if name not in skip:
            return name

    return None


def detect_urgency(text: str) -> str:
    return "urgent" if any(kw in text.lower() for kw in URGENT_KEYWORDS) else "normal"


def detect_priority(text: str) -> str:
    lower = text.lower()
    if any(kw in lower for kw in URGENT_KEYWORDS):
        return "critical"
    if any(kw in lower for kw in PRIORITY_HIGH_KEYWORDS):
        return "high"
    return "medium"


def _is_passive_voice(doc) -> bool:
    for i, token in enumerate(doc):
        if token.dep_ in ("auxpass", "nsubjpass"):
            return True
        if token.lemma_ == "be" and i + 1 < len(doc) and doc[i + 1].tag_ == "VBN":
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
    return any(text.lower().strip().startswith(s) for s in DEPENDENCY_STARTERS)


def _extract_clean_title(sentence: str) -> str:
    cleaned = sentence.strip()
    cleaned = re.sub(r"^(?:Dear\s+\w+[,.]?\s*)", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(
        r"\s*(?:on|for|by|before|until|at)\s+"
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
        r"(?:[,]?\s*\d{1,2}\s+\w+\s+\d{4})?"
        r"(?:\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?",
        "", cleaned, flags=re.IGNORECASE
    ).strip()
    cleaned = re.sub(
        r"\s*(?:by|before|until|on|at)\s+"
        r"(?:tomorrow|today|next\s+\w+)"
        r"(?:\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?",
        "", cleaned, flags=re.IGNORECASE
    ).strip()
    # Strip EOD/ASAP/sprint noise — NEW in v3.0
    cleaned = re.sub(
        r"\s*(?:by\s+)?(?:eod|eow|eom|cob|asap|as\s+soon\s+as\s+possible)\s*",
        "", cleaned, flags=re.IGNORECASE
    ).strip()
    cleaned = re.sub(r"[.,;!?]+$", "", cleaned).strip()
    cleaned = re.sub(
        r"^(?:please|kindly|also|then|and|so|your|the)\s+",
        "", cleaned, flags=re.IGNORECASE
    ).strip()
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    if len(cleaned) > 80:
        cleaned = cleaned[:77] + "..."
    return cleaned


# ══════════════════════════════════════════════════════════════
#  rule_classify() — doc caching preserved, match signals added
# ══════════════════════════════════════════════════════════════

def rule_classify(sentence: str, doc=None) -> dict:
    """
    Classify sentence. Returns type, title, verb_lemma,
    pattern_matched, verb_matched, verb_strength.
    Accepts optional pre-computed doc (caching).
    """
    if not nlp:
        return {"type": "INFO", "title": "", "verb_lemma": "",
                "pattern_matched": False, "verb_matched": False, "verb_strength": "unknown"}

    sent_lower = sentence.lower().strip()

    if _is_skip_line(sentence):
        return {"type": "INFO", "title": "", "verb_lemma": "",
                "pattern_matched": False, "verb_matched": False, "verb_strength": "unknown"}

    if doc is None:
        doc = nlp(sentence)

    if _is_passive_voice(doc):
        if re.search(r"(?i)scheduled\s+(?:for|on|at)", sent_lower):
            title = _extract_clean_title(sentence)
            return {"type": "EVENT", "title": title or sentence.strip()[:80],
                    "verb_lemma": "schedule", "pattern_matched": False,
                    "verb_matched": True, "verb_strength": "medium"}
        return {"type": "INFO", "title": "", "verb_lemma": "",
                "pattern_matched": False, "verb_matched": False, "verb_strength": "unknown"}

    for kw in DECISION_KEYWORDS:
        if kw in sent_lower:
            return {"type": "DECISION", "title": sentence.strip(), "verb_lemma": "",
                    "pattern_matched": False, "verb_matched": False, "verb_strength": "unknown"}

    # ── TASK patterns checked BEFORE event keywords ───────────────────────
    # "Lisa must schedule a review meeting" contains "meeting" (event keyword)
    # but it's a task (someone is assigned to do something). Task wins.
    for pattern in TASK_PATTERNS:
        if re.search(pattern, sent_lower):
            title = _extract_clean_title(sentence)
            verb_lemma = _extract_main_verb_lemma(doc)
            vtype = classify_verb_type(verb_lemma)
            strength = "strong" if vtype == "strong_ownership" else \
                       "medium" if vtype == "medium_ownership" else \
                       "intervention" if vtype == "intervention" else "unknown"
            return {"type": "TASK", "title": title or sentence.strip()[:80],
                    "verb_lemma": verb_lemma, "pattern_matched": True,
                    "verb_matched": bool(verb_lemma), "verb_strength": strength}

    # EVENT check — only fires if no TASK pattern matched above
    for kw in EVENT_KEYWORDS:
        if kw in sent_lower:
            title = _extract_clean_title(sentence)
            return {"type": "EVENT", "title": title or sentence.strip()[:80],
                    "verb_lemma": "", "pattern_matched": True,
                    "verb_matched": False, "verb_strength": "unknown"}

    # Direct verb match
    for token in doc:
        if token.pos_ == "VERB" and token.dep_ not in ("auxpass", "agent"):
            lemma = token.lemma_.lower()
            if lemma in ALL_TASK_VERBS:
                title = _extract_clean_title(sentence)
                vtype = classify_verb_type(lemma)
                strength = "strong" if vtype == "strong_ownership" else \
                           "medium" if vtype == "medium_ownership" else \
                           "intervention" if vtype == "intervention" else "unknown"
                return {"type": "TASK", "title": title or sentence.strip()[:80],
                        "verb_lemma": lemma, "pattern_matched": False,
                        "verb_matched": True, "verb_strength": strength}

    # will + verb
    will_match = re.search(r"(?:will|going\s+to)\s+(\w+)", sent_lower)
    if will_match:
        verb = will_match.group(1)
        if verb not in {"be", "have", "get", "do"} and not _is_passive_voice(doc):
            title = _extract_clean_title(sentence)
            vtype = classify_verb_type(verb)
            strength = "strong" if vtype == "strong_ownership" else \
                       "medium" if vtype == "medium_ownership" else "unknown"
            return {"type": "TASK", "title": title or sentence.strip()[:80],
                    "verb_lemma": verb, "pattern_matched": False,
                    "verb_matched": verb in ALL_TASK_VERBS, "verb_strength": strength}

    return {"type": "INFO", "title": "", "verb_lemma": "",
            "pattern_matched": False, "verb_matched": False, "verb_strength": "unknown"}


def _extract_main_verb_lemma(doc) -> str:
    for token in doc:
        if token.pos_ == "VERB" and token.dep_ not in ("auxpass", "agent"):
            if token.lemma_.lower() in ALL_TASK_VERBS:
                return token.lemma_.lower()
    return ""


# ══════════════════════════════════════════════════════════════
#  Dependency extraction (unchanged)
# ══════════════════════════════════════════════════════════════

def rule_extract_dependency(sentence: str) -> dict:
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


# ══════════════════════════════════════════════════════════════
#  Text preprocessor (unchanged)
# ══════════════════════════════════════════════════════════════

def preprocess_text(text: str) -> str:
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
        if re.match(r"(?i)^(thanks|thank\s+you|regards|sincerely|best|cheers)", stripped):
            in_signature = True
            continue
        if re.match(r"(?i)^(mr\.|mrs\.|ms\.|dr\.|prof\.)", stripped):
            continue
        if stripped.startswith("http"):
            continue
        stripped = re.sub(r"^(?:Dear\s+\w+[,.]?\s*)", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"^(?:Hi|Hello|Hey)\s+\w*[,.]?\s*", "", stripped, flags=re.IGNORECASE).strip()
        if stripped:
            cleaned.append(stripped)
    return " ".join(cleaned)


# ══════════════════════════════════════════════════════════════
#  MAIN EXTRACTION PIPELINE
# ══════════════════════════════════════════════════════════════

def rule_extract(text: str, current_user: str = "current_user") -> dict:
    """
    Full rule-based extraction pipeline.
    Returns structured dict with tasks, decisions, dependencies.

    v3.0 changes:
      - _custom_deadline_parse() called inside extract_deadline()
      - verb_strength signal passed to compute_confidence_score()
      - All v2.0 improvements preserved (doc caching, ownership model)
    """
    if not nlp:
        logger.error("Cannot extract — spaCy model not loaded.")
        return {"tasks": [], "decisions": [], "dependencies": [], "detected_context": "unknown"}

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

        if _is_dependency_sentence(sent_text):
            if sent_text in processed_deps:
                continue
            processed_deps.add(sent_text)
            dep = rule_extract_dependency(sent_text)
            if dep["task_a"] and dep["task_b"]:
                dependencies.append({
                    "prerequisite": dep["task_a"],
                    "dependent":    dep["task_b"],
                    "raw_text":     sent_text,
                })
            continue

        # Compute spaCy doc ONCE for this sentence
        sent_doc = nlp(sent_text)

        result    = rule_classify(sent_text, doc=sent_doc)
        sent_type = result["type"]
        title     = result["title"]

        if sent_type == "INFO":
            continue
        if sent_type == "DECISION":
            decisions.append({"decision_text": sent_text})
            continue

        if not title:
            title = _extract_clean_title(sent_text)
        if not title:
            continue

        deadline     = extract_deadline(sent_doc)
        deadline_raw = extract_deadline_raw(sent_text)
        owner        = extract_owner(sent_doc)
        urgency      = detect_urgency(sent_text)
        priority     = detect_priority(sent_text)
        normalized   = normalize_task_title(title)
        verb_lemma   = result.get("verb_lemma", "")
        verb_type    = classify_verb_type(verb_lemma) if verb_lemma else "unknown"

        signals = {
            "pattern_matched": result.get("pattern_matched", False),
            "verb_matched":    result.get("verb_matched", False),
            "verb_strength":   result.get("verb_strength", "unknown"),
            "owner_found":     owner is not None,
            "deadline_found":  deadline is not None,
            "verb_type_known": verb_type != "unknown",
            "owner_inferred":  False,  # updated after infer_task_ownership()
        }
        confidence = compute_confidence_score(signals)

        tasks.append({
            "title":           title,
            "normalized_title":normalized,
            "description":     sent_text,
            "owner":           owner,
            "owner_type":      None,
            "owner_inferred":  False,
            "intervention_by": None,
            "verb_lemma":      verb_lemma,
            "verb_type":       verb_type,
            "deadline":        deadline,
            "deadline_raw":    deadline_raw,
            "priority":        priority,
            "urgency":         urgency,
            "confidence":      confidence,
            "type":            sent_type,
            "source":          "rule_engine",
        })

    # Ownership resolution post-processing
    tasks = infer_task_ownership(tasks, current_user)

    # Apply owner_inferred penalty after resolution
    for task in tasks:
        if task.get("owner_inferred"):
            task["confidence"] = round(max(0.10, task["confidence"] - 0.15), 2)

    return {
        "tasks":            tasks,
        "decisions":        decisions,
        "dependencies":     dependencies,
        "detected_context": detect_context_from_text(text),
    }