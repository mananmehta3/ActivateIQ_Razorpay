"""Run the full ActivateIQ pipeline and build the summary."""
import copy
import re

import pandas as pd

from .load import load_config, load_data, ROOT
from .rules import diagnose, decide, channel, assign_actions
from .score import score
from .messages import draft, validate

CAUSE_GROUPS = {"R13": "Merchant stopped, no rejection (R13)", "R01": "Name mismatch: PAN or bank account (R01, R03)", "R03": "Name mismatch: PAN or bank account (R01, R03)",
                "R06": "Website issues (R06, R07, R11)", "R07": "Website issues (R06, R07, R11)", "R11": "Website issues (R06, R07, R11)",
                "R02": "Document problems: GST, unreadable, address, signatory (R02, R05, R08, R09)", "R05": "Document problems: GST, unreadable, address, signatory (R02, R05, R08, R09)",
                "R08": "Document problems: GST, unreadable, address, signatory (R02, R05, R08, R09)", "R09": "Document problems: GST, unreadable, address, signatory (R02, R05, R08, R09)",
                "R04": "Bank verification failed (R04)"}


def merchant_key(name, phone):
    """Same merchant = same business name (ignoring case and spaces) and same phone digits. None if either is missing."""
    if not isinstance(name, str) or not name.strip() or phone is None or (isinstance(phone, float) and pd.isna(phone)):
        return None
    digits = re.sub(r"\D", "", re.sub(r"\.0+$", "", str(phone).strip()))[-10:]
    return (" ".join(name.lower().split()), digits) if digits else None


def duplicates(df):
    """For each application, the earlier application ID of the same merchant, or None."""
    if "business_name" not in df.columns or "phone" not in df.columns:
        return pd.Series([None] * len(df), index=df.index, dtype=object)
    seen, out = {}, []
    for _, r in df.iterrows():
        k = merchant_key(r["business_name"], r["phone"])
        out.append(seen.get(k) if k else None)
        if k and k not in seen:
            seen[k] = r["application_id"]
    return pd.Series(out, index=df.index, dtype=object)


def run(cfg=None, extra_apps=None, confirmed=None):
    """extra_apps: optional DataFrame of applications entered by the ops team (same columns as P3_Applications)."""
    cfg = cfg or load_config()
    apps, catalog = load_data(cfg)
    if extra_apps is not None and len(extra_apps):
        apps = pd.concat([apps, extra_apps], ignore_index=True)  # keeps extra fields such as business_name, phone
    df = apps[apps["application_status"] != "Activated"].copy()
    # confirmed: {application_id: code} for reasons a person has confirmed on screen
    df["confirmed_code"] = df["application_id"].map(confirmed or {})
    df["duplicate_of"] = duplicates(df)
    rows = []
    for _, r in df.iterrows():
        code, evidence, conf, source, conflict, hold = diagnose(r, catalog, cfg)
        d = {"code": code, "evidence": evidence, "confidence": conf, "diagnosis_source": source, "conflict": conflict,
             "hold": hold}
        d.update(decide(r, d, catalog, cfg))
        rows.append(d)
    df = pd.concat([df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    df["cause"] = df["code"].map(lambda c: catalog.loc[c, "reviewer_reason"] if c in catalog.index else "Unknown")
    scored = df.apply(lambda r: score(r, catalog, cfg), axis=1, result_type="expand")
    df["p_recover"], df["priority_score"], df["risk_adjusted_tpv_lakh"] = scored[0], scored[1], scored[2]
    df["channel"] = df.apply(lambda r: channel(r, r["route"]), axis=1)
    df = assign_actions(df, cfg)
    df["nudge_draft"] = df.apply(draft, axis=1)
    df["guardrail_issues"] = df.apply(lambda r: "; ".join(validate(r, r["nudge_draft"])), axis=1)
    df["guardrail_pass"] = df["guardrail_issues"] == ""
    rec = df["recoverable"] == True  # noqa: E712
    df["priority_rank"] = None
    df.loc[rec, "priority_rank"] = df.loc[rec, "priority_score"].rank(ascending=False, method="first")
    df["priority_rank"] = pd.to_numeric(df["priority_rank"])
    return df.sort_values(["priority_rank", "priority_score"], na_position="last").reset_index(drop=True), cfg


def summary(df):
    # Fixable = the catalog says the reason is fixable (includes reasons still waiting for a person to confirm).
    fx = df[df["fixable"] == "Yes"]
    rec = fx[fx["recoverable"] == True]  # noqa: E712  (only confirmed reasons can be recoverable)
    causes = (fx.assign(group=fx["code"].map(CAUSE_GROUPS))
              .groupby("group").agg(applications=("application_id", "count"),
                                    expected_tpv_lakh=("expected_monthly_tpv_inr_lakh", "sum"))
              .sort_values(["applications", "expected_tpv_lakh"], ascending=False).round(1))
    return {
        "non_activated": len(df),
        "fixable": len(fx),
        "fixable_tpv_lakh": round(fx["expected_monthly_tpv_inr_lakh"].sum(), 1),
        "recoverable": len(rec),
        "recoverable_tpv_lakh": round(rec["expected_monthly_tpv_inr_lakh"].sum(), 1),
        "non_activated_tpv_lakh": round(df["expected_monthly_tpv_inr_lakh"].sum(), 1),
        "coded_fixable": int((fx["evidence"] == "Reason code given").sum()),
        "coded_fixable_tpv_lakh": round(fx.loc[fx["evidence"] == "Reason code given", "expected_monthly_tpv_inr_lakh"].sum(), 1),
        "confirm_reason": int((df["route"] == "Confirm reason").sum()),
        "fixable_but_stale": int(((fx["route"] == "Fixable") & (fx["recoverable"] != True)).sum()),  # noqa: E712
        "closed_r10": int((df["route"] == "Close application").sum()),
        "compliance_r12": int((df["route"] == "Route to compliance").sum()),
        "clarify": int((df["route"] == "Manual review").sum()),
        "inferred": int((df["evidence"] == "Read from rejection message").sum()),
        "needs_extra_human_check": int(df["human_check"].str.contains(";").sum()),
        "guardrail_failures": int((~df["guardrail_pass"]).sum()),
        "actions": df["next_best_action"].value_counts().to_dict(),
        "top_causes": causes,
    }


OUTPUT_COLS = ["priority_rank", "application_id", "business_type", "preferred_language", "step_reached", "application_status",
               "days_since_last_activity", "attempts", "support_contacts", "expected_monthly_tpv_inr_lakh",
               "rejection_code", "rejection_message", "code", "cause", "evidence", "confidence", "diagnosis_source",
               "fixable", "recoverable", "route", "p_recover", "priority_score",
               "next_best_action", "channel", "whatsapp_opted_in", "follow_up", "human_check", "nudge_draft",
               "guardrail_pass", "guardrail_issues"]


# Data Pack columns keep their Excel names; columns ActivateIQ adds get plain names.
EXPORT_NAMES = {"priority_rank": "priority_rank", "code": "diagnosed_reason_code", "cause": "reviewer_reason",
                "evidence": "how_reason_was_found", "confidence": "confidence", "diagnosis_source": "reason_detail",
                "fixable": "fixable", "recoverable": "recoverable", "route": "decision",
                "p_recover": "recovery_score_rule_of_thumb", "priority_score": "priority_score",
                "next_best_action": "action",
                "channel": "channel", "follow_up": "follow_up_plan", "human_check": "before_sending_reviewer_must",
                "nudge_draft": "nudge_draft", "guardrail_pass": "safety_check_passed", "guardrail_issues": "safety_check_problems"}

SUMMARY_NAMES = {"non_activated": "Non-activated applications", "fixable": "Fixable applications",
                 "fixable_tpv_lakh": "Expected TPV of fixable applications (Rs lakh/month)",
                 "recoverable": "Recoverable applications", "recoverable_tpv_lakh": "Expected TPV of recoverable applications (Rs lakh/month)",
                 "fixable_but_stale": "Fixable but inactive too long", "closed_r10": "Closed: restricted business category (R10)",
                 "compliance_r12": "Routed to compliance (R12)", "clarify": "Manual review (reason unclear)",
                 "non_activated_tpv_lakh": "Expected TPV of all non-activated applications (Rs lakh/month)",
                 "coded_fixable": "Fixable, reason code given in the data",
                 "coded_fixable_tpv_lakh": "Expected TPV of fixable applications with a reason code (Rs lakh/month)",
                 "confirm_reason": "Reason read from a message, waiting for a person to confirm",
                 "inferred": "Reason read from rejection message (no code)",
                 "needs_extra_human_check": "Applications needing an extra check by a person",
                 "guardrail_failures": "Nudges failing the safety check"}


def export_table(df):
    out = df[OUTPUT_COLS].copy()
    out["recoverable"] = out["recoverable"].map({True: "Yes", False: "No"}).fillna("Not applicable")
    out["guardrail_pass"] = out["guardrail_pass"].map({True: "Yes", False: "No"})
    return out.rename(columns=EXPORT_NAMES)


def write_excel(target, df, s, decisions=None):
    """Write the results workbook to a path or a file-like buffer. decisions: optional {application_id: {...}}."""
    out = export_table(df)
    if "business_name" in df.columns and df["business_name"].notna().any():
        out.insert(2, "business_name", df["business_name"].values)
    if decisions is not None:
        get = lambda a, k: decisions.get(a, {}).get(k, "")  # noqa: E731
        ids = df["application_id"]
        out["approval_status"] = [get(a, "status") or "Waiting" for a in ids]
        out["approved_or_sent_nudge"] = [get(a, "final_message") if get(a, "status") in ("Approved", "Sent") else "" for a in ids]
        out["rejection_reason_by_team"] = [get(a, "reason") for a in ids]
        out["decided_at"] = [get(a, "decided_at") for a in ids]
    flat = {SUMMARY_NAMES.get(k, k): v for k, v in s.items() if k not in ("actions", "top_causes")}
    with pd.ExcelWriter(target, engine="openpyxl") as xw:
        out.to_excel(xw, sheet_name="Cases", index=False)
        pd.DataFrame(list(flat.items()), columns=["metric", "value"]).to_excel(xw, sheet_name="Summary", index=False)
        s["top_causes"].rename_axis("cause").to_excel(xw, sheet_name="Top systemic causes")
        pd.Series(s["actions"], name="applications").rename_axis("action").to_excel(xw, sheet_name="Actions")
    return out


def export(df, s, outdir=ROOT / "outputs"):
    outdir.mkdir(exist_ok=True)
    export_table(df).to_csv(outdir / "activateiq_cases.csv", index=False, encoding="utf-8-sig")
    write_excel(outdir / "activateiq_output.xlsx", df, s)
    return outdir


if __name__ == "__main__":
    df, cfg = run()
    s = summary(df)
    export(df, s)
    for k, v in s.items():
        print(f"{k}: {v}" if k != "top_causes" else f"top_causes:\n{v}")
