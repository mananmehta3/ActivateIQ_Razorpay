"""Fill cached templates and check every draft with a rule-based validator."""
import json
import re

from .load import ROOT

TEMPLATES = json.loads((ROOT / "activateiq" / "templates.json").read_text())["languages"]
RESUME_LINK = "https://dashboard.razorpay.com"  # where merchants log in to finish activation

SCRIPTS = {"Hindi": r"[ऀ-ॿ]", "Marathi": r"[ऀ-ॿ]",
           "Tamil": r"[஀-௿]", "Kannada": r"[ಀ-೿]"}
INDIC = r"[ऀ-෿]"

# (pattern, plain-language label) pairs used by the safety check.
PROMISES = [(r"guarantee", "promises a result"), (r"waive|waiver", "offers a waiver"),
            (r"will be (approved|activated|live)", "promises approval or activation"),
            (r"within \d+ ?(hour|day|working)", "promises a time"), (r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", "mentions a date"),
            (r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2}\b", "mentions a date"),
            (r"\btomorrow\b|\bkal tak\b", "promises a time"), (r"\bpakka\b", "promises a result"),
            (r"refund (will|is being)", "promises a refund")]
COMPLIANCE_WORDS = [r"sanction", r"screening", r"negative list", r"watch ?list", r"blacklist", r"\baml\b",
                    r"compliance", r"fraud", r"money laundering"]
WORKAROUNDS = [r"another category", r"different category", r"re-?apply", r"new application", r"change (your|the) category",
               r"select the correct category", r"sahi category"]


def draft(row):
    lang = TEMPLATES.get(row["preferred_language"], TEMPLATES["English"])
    a, code, action = row["application_id"], row["code"], row["next_best_action"]
    f = {"app_id": a, "resume_link": RESUME_LINK, "step": lang["steps"].get(row["step_reached"], row["step_reached"])}
    if action in ("Manual review", "Confirm reason"):
        return ""
    if action == "Close application":
        return lang["CLOSE"].format(**f)
    if action == "Route to compliance":
        return lang["REVIEW"].format(**f)
    if code == "R13":
        text = lang["R13"].format(**f)
    else:
        text = " ".join([lang["intro"].format(**f), lang[code], lang["cta"].format(**f)])
    if action == "Send final nudge":
        text += " " + lang["LAST"]
    return text


def validate(row, text):
    """Return a list of guardrail problems (empty = pass)."""
    if not text:
        return []
    t, issues = text.lower(), []
    for p, label in PROMISES:
        if re.search(p, t) and label not in issues:
            issues.append(label)
    if row["next_best_action"] in ("Route to compliance", "Close application") and any(re.search(p, t) for p in COMPLIANCE_WORDS):
        issues.append("reveals a compliance screening reason")
    if row["next_best_action"] == "Close application" and any(re.search(p, t) for p in WORKAROUNDS):
        issues.append("suggests a workaround for a restricted business category")
    lang = row["preferred_language"]
    if lang in SCRIPTS and not re.search(SCRIPTS[lang], text):
        issues.append(f"not written in {lang}")
    if lang in ("English", "Hinglish") and re.search(INDIC, text):
        issues.append(f"not written in {lang}")
    if row["channel"].startswith("WhatsApp") and row["whatsapp_opted_in"] != "Yes":
        issues.append("WhatsApp used but the merchant has not opted in")
    return issues
