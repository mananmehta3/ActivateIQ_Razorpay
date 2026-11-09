"""Deterministic decision rules: evidence level, policy gate, fixable, recoverable, action, channel."""
from .classify import classify, keyword_classify

import re

RESTRICTED, COMPLIANCE, ABANDONED = "R10", "R12", "R13"

# Words in a business name or industry that suggest a restricted category (R10: "gambling or prohibited goods").
# A match never closes anything: it only holds the case for a person. "Drug" alone is left out on purpose, because
# many real chemists are called "... Drug House"; the AI model explanation looks at those.
RESTRICTED_WORDS = (r"cannabis|ganja|marijuana|\bweed\b|charas|hashish|narcotic|cocaine|heroin|\bmdma\b|"
                    r"gambl|betting|casino|\bsatta\b|lottery|firearm|weapon|ammunition|\bguns?\b|porn|escort")


def restricted_hint(row):
    """The word that makes the business name or industry look like a restricted category, or None."""
    for col in ("business_name", "industry"):
        m = re.search(RESTRICTED_WORDS, _txt(row.get(col)) or "", re.I)
        if m:
            return m.group(0)
    return None


def _txt(v):
    """Blank cells arrive as NaN floats; treat anything that isn't non-empty text as missing."""
    return v.strip() if isinstance(v, str) and v.strip() else None


def diagnose(row, catalog, cfg):
    """Return code, evidence level, confidence, source, any code/text conflict, and a reason to hold the case
    for a person (empty if none)."""
    code, text = _txt(row["rejection_code"]), _txt(row["rejection_message"])
    conflict = hold = ""
    if _txt(row.get("confirmed_code")):  # a person decided the reason on screen: that wins over everything
        code, evidence, conf = _txt(row["confirmed_code"]), "Reason confirmed by a person", 1.0
        source = "decided by the onboarding team"
        if _txt(row.get("rejection_message")) and not _txt(row["rejection_code"]):
            source = "read from the rejection message, then confirmed by the onboarding team"
        return code, evidence, conf, source, conflict, hold
    if code:
        evidence, conf, source = "Reason code given", 1.0, "looked up in rejection catalog"
        if text:  # second opinion on the text
            k_code, k_conf, _ = keyword_classify(text)
            if k_code and k_code != code and k_conf >= cfg["classifier"]["confidence_cutoff"]:
                conflict = f"the code says {code} but the reviewer's message points to {k_code}"
                # A message about screening or a restricted category, or any doubt about a closure, goes to a person
                # before anything is sent or closed.
                if k_code in (RESTRICTED, COMPLIANCE) or code == RESTRICTED:
                    hold = conflict
    elif not text:
        code, evidence, conf, source = ABANDONED, "No rejection: merchant stopped (R13)", 1.0, "no rejection code or message"
    else:
        code, conf, source = classify(text, catalog, cfg)
        evidence = "Read from rejection message" if code else "Could not read"
    hint = restricted_hint(row)
    if hint and code != RESTRICTED and not hold:
        hold = f"the business name or industry mentions \"{hint}\", which may be a restricted category (R10)"
    dup = _txt(row.get("duplicate_of"))
    if dup and not hold:
        hold = f"possible duplicate of {dup} (same business name and phone)"
    return code, evidence, conf, source, conflict, hold


def decide(row, d, catalog, cfg):
    """Gate -> fixable -> recoverable -> route. Returns dict of decision fields."""
    code, evidence, conf = d["code"], d["evidence"], d["confidence"]
    inferred = evidence == "Read from rejection message"
    low_conf = evidence == "Could not read" or (inferred and conf < cfg["classifier"]["confidence_cutoff"])
    human = ["Read and approve the nudge before it is sent"]

    if low_conf:  # checked first: a shaky reading must never trigger a close or a compliance route
        route, fixable = "Manual review", "Unknown"
        human.append("Decide the reason yourself: the rejection message is unclear")
    elif d.get("hold"):  # code and message disagree on a closure or screening, or a likely duplicate merchant
        route, fixable = "Manual review", "Unknown"
        human.append("Decide the reason yourself: " + d["hold"])
    elif inferred:  # a reason read from a message is only a proposal until a person confirms it
        route, fixable = "Confirm reason", catalog.loc[code, "fixable"]
        human.append(f"Confirm the reason first: {code} was read from the rejection message, not given as a code")
    elif code == COMPLIANCE:
        route, fixable = "Route to compliance", "Needs compliance review"
        human.append("Compliance team handles this case")
    elif code == RESTRICTED:
        route, fixable = "Close application", "No"
        human.append("Confirm before closing (this cannot be undone)")
    else:
        route, fixable = "Fixable", catalog.loc[code, "fixable"]
    if d["conflict"] and not d.get("hold"):
        human.append("Rejection code and message do not agree: " + d["conflict"])

    rc = cfg["recoverability"]
    recoverable = None
    if route == "Fixable":
        recoverable = (row["days_since_last_activity"] <= rc["max_days_inactive"]
                       and row["attempts"] < rc["max_attempts"])
    return {"route": route, "fixable": fixable, "recoverable": recoverable, "human_check": "; ".join(human)}


def channel(row, route):
    if route in ("Manual review", "Confirm reason"):
        return "None (internal)"
    return "WhatsApp" if row["whatsapp_opted_in"] == "Yes" else "Email"


def assign_actions(df, cfg):
    """One next-best action per case. Needs priority already computed."""
    n = cfg["actions"]["ops_call_capacity"]
    rec = df[df["recoverable"] == True].sort_values("priority_score", ascending=False)  # noqa: E712
    top = set(rec.head(n)["application_id"])
    sched = ", ".join(f"Day {d}" for d in cfg["followup"]["schedule_days"])
    stop = f"stop when the merchant resumes or after {cfg['followup']['max_nudges']} nudges"

    def act(r):
        if r["route"] == "Route to compliance":
            return "Route to compliance", "One under-review message, nothing more"
        if r["route"] == "Close application":
            return "Close application", "None"
        if r["route"] == "Manual review":
            return "Manual review", "Nothing until a person decides the reason"
        if r["route"] == "Confirm reason":
            return "Confirm reason", "Nothing until a person confirms the reason"
        if not r["recoverable"]:
            return "Send final nudge", "One nudge, then stop"
        if r["application_id"] in top:
            return "Call merchant", f"Call, then nudge on {sched}; {stop}"
        if r["code"] == "R13":
            return "Send resume reminder", f"{sched}; {stop}"
        return "Send fix nudge", f"{sched}; {stop}"

    out = df.apply(act, axis=1, result_type="expand")
    df["next_best_action"], df["follow_up"] = out[0], out[1]
    return df
