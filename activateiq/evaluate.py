"""Evaluation.

1. Classifier check: run the keyword classifier on the 49 rows that DO have a code and compare.
   (Caveat: rules were improved after the first run on these rows, 40/49 -> 49/49, so the second number
   is a training score, not a blind test. Your gold labels are the blind test.)
2. Guardrail tests: every draft must pass the validator, and the validator must catch planted bad drafts.
3. Gold labels: compare the system with YOUR hand labels in gold_labels.csv (fill it in first).
"""
import pandas as pd

from .classify import keyword_classify, llm_classify
from .load import ROOT, load_config, load_data
from .messages import validate
from .pipeline import run

GOLD = ROOT / "gold_labels.csv"


def classifier_check(df):
    has = df[df["rejection_code"].map(lambda v: isinstance(v, str)) & df["rejection_message"].map(lambda v: isinstance(v, str))]
    pred = has["rejection_message"].map(lambda t: keyword_classify(t)[0])
    mask = pred != has["rejection_code"]
    wrong = has.loc[mask, ["application_id", "rejection_code", "rejection_message"]].copy()
    wrong["predicted"] = pred[mask]
    return int((pred == has["rejection_code"]).sum()), len(has), wrong


PLANTED = [
    ("Close application", "English", "Yes", "Sorry, but you can re-apply under a different category."),
    ("Route to compliance", "English", "Yes", "Your application matched a sanctions screening list."),
    ("Send fix nudge", "English", "Yes", "Fix this and your account will be activated within 2 days, guaranteed."),
    ("Send fix nudge", "Tamil", "Yes", "Please upload your PAN again."),
    ("Send fix nudge", "English", "No", "Please upload your PAN again."),
]


def guardrail_tests(df):
    real_fail = int((~df["guardrail_pass"]).sum())
    caught = []
    for action, lang, optin, text in PLANTED:
        row = {"next_best_action": action, "preferred_language": lang, "whatsapp_opted_in": optin, "channel": "WhatsApp"}
        caught.append({"planted_draft": text, "action": action, "language": lang, "issues": "; ".join(validate(row, text))})
    caught = pd.DataFrame(caught)
    return real_fail, len(df), caught


GOLD_CHOICES = {
    "gold_code": ["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10", "R11", "R12", "R13"],
    "gold_route": ["Fixable", "Close application", "Route to compliance", "Manual review"],
    "gold_recoverable": ["Yes", "No", "Not applicable"],
    "gold_action": ["Call merchant", "Send fix nudge", "Send resume reminder", "Send final nudge", "Confirm reason",
                    "Manual review", "Close application", "Route to compliance"],
}


def _system_answers(df, cfg=None):
    """What the system says, in the same words as the labels. A reason still waiting for a person counts as its
    proposed code, with the route and recoverability that code would lead to."""
    cfg = cfg or load_config()
    rc = cfg["recoverability"]
    out = df[["application_id", "code", "next_best_action"]].copy()
    implied = df["code"].map({"R10": "Close application", "R12": "Route to compliance"}).fillna("Fixable")
    out["route"] = df["route"].where(df["route"] != "Confirm reason", implied)
    fixable = out["route"] == "Fixable"
    rec = (df["days_since_last_activity"] <= rc["max_days_inactive"]) & (df["attempts"] < rc["max_attempts"])
    out["recoverable"] = "Not applicable"
    out.loc[fixable & rec, "recoverable"] = "Yes"
    out.loc[fixable & ~rec, "recoverable"] = "No"
    return out.rename(columns={"next_best_action": "action"})


def gold_check(df):
    """Compare the system with the hand labels. Returns None until at least one label is filled in."""
    if not GOLD.exists():
        return None
    g = pd.read_csv(GOLD, dtype=str)
    labelled = g[g[list(GOLD_CHOICES)].notna().any(axis=1)]
    if labelled.empty:
        return None
    m = labelled.merge(_system_answers(df), on="application_id", how="left")
    res = {"labelled_cases": len(m)}
    wrong = []
    for name in ("code", "route", "recoverable", "action"):
        gcol = f"gold_{name}"
        sub = m[m[gcol].notna()]
        if sub.empty:
            continue
        ok = sub[gcol].str.strip().str.lower() == sub[name].astype(str).str.strip().str.lower()
        res[name] = (int(ok.sum()), len(sub))
        wrong += [{"Application": r.application_id, "What": name, "Your label": r[gcol], "System": r[name]}
                  for _, r in sub[~ok].iterrows()]
    return res, pd.DataFrame(wrong)


def rules_vs_ai(cfg=None, allow_call=False):
    """Word rules vs AI model on every rejection message.

    Test set: the 49 applications that have BOTH a code and a message. We hide the code, let each
    reader guess it from the message, and compare with the real code. The 4 message-only cases have
    no answer to check against, so we only show whether the two readers agree.
    AI answers come from llm_answers.json; set allow_call=True (with a key) to fill it.
    """
    cfg = cfg or load_config()
    apps, catalog = load_data(cfg)
    msg = apps["rejection_message"].map(lambda v: isinstance(v, str) and v.strip() != "")
    has_code = apps["rejection_code"].map(lambda v: isinstance(v, str) and v.strip() != "")
    rows = []
    for _, r in apps[msg].iterrows():
        k_code = keyword_classify(r.rejection_message)[0]
        a_code, a_conf, note = llm_classify(r.rejection_message, catalog, cfg, allow_call=allow_call)
        rows.append({"application_id": r.application_id, "test": "Code hidden" if has_code[_] else "No code (real case)",
                     "rejection_message": r.rejection_message, "real_code": r.rejection_code if has_code[_] else "",
                     "word_rules": k_code or "", "ai_model": a_code or "", "ai_confidence": a_conf if a_code else None,
                     "ai_note": note})
    return pd.DataFrame(rows)


def compare_summary(t):
    test = t[t["test"] == "Code hidden"]
    answered = test[test["ai_model"] != ""]
    blank = t[t["test"] != "Code hidden"]
    return {"cases": len(test), "rules_right": int((test["word_rules"] == test["real_code"]).sum()),
            "ai_answered": len(answered), "ai_right": int((answered["ai_model"] == answered["real_code"]).sum()),
            "agree": int((answered["ai_model"] == answered["word_rules"]).sum()),
            "blank_cases": len(blank), "blank_answered": int((blank["ai_model"] != "").sum()),
            "blank_agree": int(((blank["ai_model"] == blank["word_rules"]) & (blank["ai_model"] != "")).sum())}


if __name__ == "__main__":
    df, _ = run()
    ok, n, wrong = classifier_check(df)
    print(f"Classifier on coded rows: {ok}/{n}")
    if len(wrong):
        print(wrong.to_string(index=False))
    fails, total, caught = guardrail_tests(df)
    print(f"\nGuardrail validator on real drafts: {total - fails}/{total} pass")
    print("Planted bad drafts:")
    print(caught.to_string(index=False))
    g = gold_check(df)
    print("\nGold labels:", "not filled in yet (label them on the How accurate is it page)" if g is None else g[0])
    if g is not None and len(g[1]):
        print(g[1].to_string(index=False))
