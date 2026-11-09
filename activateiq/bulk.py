"""Bulk add: check an uploaded CSV or Excel file of applications before adding them."""
import math

import pandas as pd

from .pipeline import merchant_key

# Same column names as the P3_Applications sheet, plus two optional ones.
COLUMNS = ["application_id", "business_name", "business_type", "industry", "city", "preferred_language",
           "expected_monthly_tpv_inr_lakh", "whatsapp_opted_in", "phone", "step_reached", "application_status",
           "days_since_last_activity", "attempts", "support_contacts", "rejection_code", "rejection_message"]
REQUIRED = ["business_type", "preferred_language", "expected_monthly_tpv_inr_lakh", "whatsapp_opted_in",
            "step_reached", "application_status", "days_since_last_activity", "attempts"]
ALLOWED = {
    "business_type": ["Proprietorship", "Private Limited", "Partnership", "LLP", "Trust / NGO"],
    "preferred_language": ["English", "Hinglish", "Hindi", "Tamil", "Kannada", "Marathi"],
    "whatsapp_opted_in": ["Yes", "No"],
    "step_reached": ["Business details", "KYC docs", "Bank verification", "Website/App review"],
    "application_status": ["Stalled", "Rejected"],
}
NUMBERS = {"expected_monthly_tpv_inr_lakh": float, "days_since_last_activity": int, "attempts": int, "support_contacts": int}

GUIDE = {
    "application_id": "A new ID, e.g. A3101. Leave empty to get one (N0001, N0002, …)",
    "business_name": "Text",
    "business_type": "One of: " + ", ".join(ALLOWED["business_type"]),
    "industry": "Text",
    "city": "Text",
    "preferred_language": "One of: " + ", ".join(ALLOWED["preferred_language"]),
    "expected_monthly_tpv_inr_lakh": "Number, 0 or more (decimals allowed), e.g. 12.5",
    "whatsapp_opted_in": "Yes or No",
    "phone": "Phone number",
    "step_reached": "One of: " + ", ".join(ALLOWED["step_reached"]),
    "application_status": "Stalled or Rejected",
    "days_since_last_activity": "Whole number, 0 or more",
    "attempts": "Whole number, 0 or more",
    "support_contacts": "Whole number, 0 or more (empty = 0)",
    "rejection_code": "The reviewer's reason code, R01 to R13 (see the rejection catalog)",
    "rejection_message": "The reviewer's message",
}


def guide():
    """The upload columns as a table: column, required or optional, what it can hold."""
    return pd.DataFrame({"Column": COLUMNS, "Required": ["Yes" if c in REQUIRED else "No" for c in COLUMNS],
                         "What it can hold": [GUIDE[c] for c in COLUMNS]})


def template():
    """A sample file the operations team can fill in."""
    return pd.DataFrame([
        {"application_id": "", "business_name": "Sharma Sweets", "business_type": "Proprietorship", "industry": "Food & Beverage",
         "city": "Jaipur", "preferred_language": "Hindi", "expected_monthly_tpv_inr_lakh": 18, "whatsapp_opted_in": "Yes",
         "phone": "9876543210", "step_reached": "KYC docs", "application_status": "Rejected", "days_since_last_activity": 6,
         "attempts": 1, "support_contacts": 0, "rejection_code": "R01", "rejection_message": ""},
        {"application_id": "", "business_name": "Green Leaf Store", "business_type": "Partnership", "industry": "Retail",
         "city": "Pune", "preferred_language": "Marathi", "expected_monthly_tpv_inr_lakh": 9.5, "whatsapp_opted_in": "No",
         "phone": "", "step_reached": "Bank verification", "application_status": "Stalled", "days_since_last_activity": 12,
         "attempts": 1, "support_contacts": 1, "rejection_code": "", "rejection_message": ""},
    ], columns=COLUMNS)


def read_file(uploaded):
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded, dtype=str)
    return pd.read_excel(uploaded, dtype=str)


def _norm(col):
    return str(col).strip().lower().replace(" ", "_").replace("(", "").replace(")", "")


def check(raw, existing_ids, catalog_codes, start_number):
    """Return (rows that can be added, list of problems). Each problem names the row number in the file."""
    df = raw.rename(columns={c: _norm(c) for c in raw.columns}).dropna(how="all")
    missing_cols = [c for c in REQUIRED if c not in df.columns]
    if missing_cols:
        return pd.DataFrame(), ["The file is missing these columns: " + ", ".join(missing_cols)]
    lookup = {k: {v.lower(): v for v in vals} for k, vals in ALLOWED.items()}
    used, good, problems, n = set(existing_ids), [], [], start_number
    for i, r in df.iterrows():
        line = i + 2  # row 1 is the header
        row, errs = {}, []
        for col in COLUMNS:
            v = r.get(col)
            row[col] = None if pd.isna(v) or str(v).strip() == "" else str(v).strip()
        for col in REQUIRED:
            if row[col] is None:
                errs.append(f"{col} is empty")
        for col, vals in lookup.items():
            if row[col] is not None:
                if row[col].lower() in vals:
                    row[col] = vals[row[col].lower()]
                elif col == "application_status" and row[col].lower() == "activated":
                    errs.append("already activated")
                else:
                    errs.append(f"{col} must be one of: {', '.join(ALLOWED[col])}")
        for col, kind in NUMBERS.items():
            if row[col] is not None:
                try:
                    x = float(row[col])
                except ValueError:
                    errs.append(f"{col} must be a number")
                    continue
                if not math.isfinite(x):
                    errs.append(f"{col} must be a number")
                elif x < 0:
                    errs.append(f"{col} cannot be negative")
                elif kind is int and x != int(x):
                    errs.append(f"{col} must be a whole number")
                else:
                    row[col] = kind(x)
        if row["support_contacts"] is None:
            row["support_contacts"] = 0
        if row["rejection_code"] is not None:
            row["rejection_code"] = row["rejection_code"].upper()
            if row["rejection_code"] not in catalog_codes:
                errs.append(f"rejection_code {row['rejection_code']} is not in the rejection catalog")
        if row["application_id"] is not None:
            row["application_id"] = row["application_id"].upper()
            if row["application_id"] in used:
                errs.append(f"application ID {row['application_id']} already exists")
        if errs:
            problems.append(f"Row {line}: " + "; ".join(errs))
            continue
        if row["application_id"] is None:
            while f"N{n:04d}" in used:
                n += 1
            row["application_id"] = f"N{n:04d}"
        used.add(row["application_id"])
        row["industry"] = row["industry"] or "-"
        row["city"] = row["city"] or "-"
        good.append(row)
    return pd.DataFrame(good, columns=COLUMNS), problems


def duplicate_warnings(good, existing):
    """Rows that look like a merchant already in the list or earlier in the file (same business name and phone).
    They can still be added: the later copy goes to Manual review so the merchant does not get two messages."""
    seen = {}
    if existing is not None and len(existing) and {"business_name", "phone"} <= set(existing.columns):
        for _, r in existing.iterrows():
            k = merchant_key(r["business_name"], r["phone"])
            if k:
                seen.setdefault(k, r["application_id"])
    out = []
    for _, r in good.iterrows():
        k = merchant_key(r["business_name"], r["phone"])
        if k in seen:
            out.append(f"{r['application_id']} ({r['business_name']}) looks like {seen[k]}: same business name and phone")
        elif k:
            seen[k] = r["application_id"]
    return out
