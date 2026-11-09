"""ActivateIQ: merchant onboarding and KYC drop-off recovery. Run: streamlit run app.py"""
import copy
import math
import io
import json
import os
import urllib.parse
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from activateiq.evaluate import classifier_check, guardrail_tests, gold_check, rules_vs_ai, compare_summary, GOLD_CHOICES
from activateiq import bulk
from activateiq.load import load_config, load_data, ROOT
from activateiq.messages import validate
from activateiq.pipeline import run, summary, write_excel

st.set_page_config(page_title="ActivateIQ", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

NAVY, BLUE, LIGHT = "#072654", "#3395FF", "#8CC3FF"
ACTION_COLORS = {"Call merchant": NAVY, "Send fix nudge": BLUE, "Send resume reminder": LIGHT, "Send final nudge": "#F5A623",
                 "Manual review": "#7A869A", "Confirm reason": "#B0B8C4", "Close application": "#E5484D", "Route to compliance": "#9B59B6"}
ADDED = ROOT / "data" / "added_applications.csv"
DECISIONS = ROOT / "outputs" / "decisions.csv"
CONFIRMED = ROOT / "outputs" / "confirmed_reasons.csv"
# An API key can sit in .streamlit/secrets.toml (never committed) instead of the terminal.
try:
    for _k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = st.secrets[_k]
except Exception:  # no secrets file
    pass
BASE = load_config()
_, CATALOG = load_data(BASE)

st.markdown(f"""<style>
.block-container {{padding-top: 1.5rem; max-width: 1250px;}}
.stAppDeployButton, [data-testid="stAppDeployButton"], [data-testid="stMainMenu"], #MainMenu, footer {{display: none !important;}}
[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"] {{display: flex !important; visibility: visible !important;}}
header[data-testid="stHeader"] {{background: transparent;}}
.aiq-title {{background: {NAVY}; color: white; padding: 16px 24px; border-radius: 12px; margin-bottom: 20px;}}
.aiq-title h1 {{color: white; margin: 0; font-size: 26px;}}
.aiq-title p {{color: #CFE2FF; margin: 2px 0 0 0; font-size: 15px;}}
div[data-testid="stMetric"] {{background: #F2F6FC; border-left: 5px solid {BLUE}; border-radius: 10px; padding: 10px 14px;}}
section[data-testid="stSidebar"] {{background: {NAVY};}}
section[data-testid="stSidebar"] * {{color: #EAF2FF !important;}}
section[data-testid="stSidebar"] input {{color: {NAVY} !important; -webkit-text-fill-color: {NAVY} !important;}}
section[data-testid="stSidebar"] button svg {{fill: {NAVY} !important;}}
[data-testid="stMetricValue"] {{font-size: 24px !important;}}
.st-key-sidebar_tools {{position: fixed; bottom: 18px; width: auto !important; gap: 6px; flex-direction: row !important;}}
.st-key-sidebar_tools button {{background: transparent !important; border: 1px solid rgba(140,195,255,.6) !important;
  min-height: 30px !important; padding: 2px 10px !important;}}
.st-key-sidebar_tools button p {{font-size: 13px !important;}}
[data-testid="stMetricValue"] > div {{white-space: normal !important; overflow: visible !important;}}
.aiq-box {{background: #F2F6FC; border-radius: 10px; padding: 14px 18px; margin-bottom: 10px;}}
.aiq-box b {{color: {NAVY};}}
.aiq-step {{color: {BLUE}; font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: .5px; margin-top: 14px;}}
</style>""", unsafe_allow_html=True)


# ---------------- saved data ----------------
def load_added():
    return pd.read_csv(ADDED, dtype={"rejection_code": str, "rejection_message": str, "phone": str}) if ADDED.exists() else pd.DataFrame()


def load_decisions():
    if DECISIONS.exists():
        return pd.read_csv(DECISIONS, dtype=str).fillna("").set_index("application_id").to_dict("index")
    return {}


def save_decision(app_id, status, text, reason=""):
    st.session_state.decisions[app_id] = {"status": status, "final_message": text, "reason": reason,
                                          "decided_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    DECISIONS.parent.mkdir(exist_ok=True)
    pd.DataFrame.from_dict(st.session_state.decisions, orient="index").rename_axis("application_id").to_csv(DECISIONS)


if "decisions" not in st.session_state:
    st.session_state.decisions = load_decisions()


def load_confirmed():
    return pd.read_csv(CONFIRMED, dtype=str).set_index("application_id")["code"].to_dict() if CONFIRMED.exists() else {}


def save_confirmed(app_id, code):
    conf = load_confirmed()
    if code:
        conf[app_id] = code
    else:
        conf.pop(app_id, None)
    CONFIRMED.parent.mkdir(exist_ok=True)
    pd.DataFrame({"application_id": list(conf), "code": list(conf.values())}).to_csv(CONFIRMED, index=False)


@st.cache_data
def compute(added_json, confirmed_json, code_version):
    """code_version changes whenever the rules, templates or config change, so results are never stale."""
    cfg = copy.deepcopy(BASE)
    extra = pd.read_json(io.StringIO(added_json)) if added_json else None
    df, _ = run(cfg, extra, json.loads(confirmed_json))
    return df, summary(df)


def wa_link(text, phone=None):
    num = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if num and len(num) == 10:
        num = "91" + num
    return f"https://wa.me/{num}?text={urllib.parse.quote(text)}" if num else f"https://wa.me/?text={urllib.parse.quote(text)}"


def mail_link(text, app_id):
    return f"mailto:?subject={urllib.parse.quote(f'Your Razorpay application {app_id}')}&body={urllib.parse.quote(text)}"


def yn(v):
    return "Yes" if v is True or v == True else ("No" if v is False or v == False else "Not applicable")  # noqa: E712


def money(v):
    return f"₹{v:,.1f} lakh"


def reason_text(r):
    return f"{r.code} · {r.cause}" if r.code in CATALOG.index else "Not clear yet"


# ---------------- sidebar ----------------
st.sidebar.markdown("## ⚡ ActivateIQ")
page = st.sidebar.radio("Menu", ["Dashboard", "Applications", "Add an application",
                                 "Why merchants stall", "How accurate is it"], label_visibility="collapsed")

added = load_added()
CODE_VERSION = max(p.stat().st_mtime for p in [*(ROOT / "activateiq").glob("*.py"), ROOT / "activateiq" / "templates.json",
                                                ROOT / "config.yaml"])
df, s = compute(added.to_json() if len(added) else "", json.dumps(load_confirmed(), sort_keys=True), CODE_VERSION)
df["approval"] = df["application_id"].map(lambda a: st.session_state.decisions.get(a, {}).get("status", "Waiting"))
phones = dict(zip(added["application_id"], added.get("phone", pd.Series(dtype=str)))) if len(added) else {}

st.markdown('<div class="aiq-title"><h1>ActivateIQ</h1><p>Merchant onboarding and KYC drop-off recovery</p></div>',
            unsafe_allow_html=True)

# Download and Reset sit at the bottom of the sidebar, out of the way of every page.
tools = st.sidebar.container(key="sidebar_tools")
_buf = io.BytesIO()
write_excel(_buf, df, s, st.session_state.decisions)
tools.download_button("⬇ Download results", _buf.getvalue(), f"activateiq_results_{datetime.now():%d%b%Y}.xlsx",
                      help="Excel file: every application with its reason, decision, action, nudge and approval status, plus the summary")
with tools.popover("↺ Reset"):
    st.markdown(f"This removes **{len(added)} added application{'s' if len(added) != 1 else ''}** and "
                f"**{len(st.session_state.decisions)} approve, reject or sent mark{'s' if len(st.session_state.decisions) != 1 else ''}** and "
                f"**{len(load_confirmed())} reason{'s' if len(load_confirmed()) != 1 else ''} chosen by a person**, and goes back to the "
                "original 100 applications. Your gold labels are kept. This cannot be undone.")
    if st.button("Yes, reset everything", type="primary", use_container_width=True):
        for f in (ADDED, DECISIONS, CONFIRMED):
            if f.exists():
                f.unlink()
        st.cache_data.clear()
        st.session_state.clear()
        st.session_state.decisions = {}
        st.session_state.clear_box = True
        st.rerun()


CODE_CHOICES = [f"{k} · {v}" for k, v in CATALOG["reviewer_reason"].items() if k != "R13"]


def confirm_reason(r, key):
    """A reason read from a message is only a proposal: a person confirms it before any message or closure."""
    msg = r.rejection_message if isinstance(r.rejection_message, str) else "None"
    hold = r.get("hold") if isinstance(r.get("hold"), str) else ""
    if hold:
        given = r.rejection_code if isinstance(r.rejection_code, str) else "none"
        st.info(f"**Reason code:** {given}  \n**Reviewer's message:** “{msg}”  \nOn hold: {hold}. Nothing is sent or "
                "closed until a person chooses the reason.")
    else:
        st.info(f"**Reviewer's message:** “{msg}”  \nThere is no reason code, so no message is written until a person "
                "confirms the reason.")
    if r.route == "Confirm reason":
        st.markdown(f"**Proposed reason:** {r.code} · {r.cause} ({r.diagnosis_source})")
        if r.code == "R10":
            st.warning("If confirmed, this application will be closed. Confirm only if the business category is really "
                       "not supported.")
        if st.button(f"Confirm {r.code}", type="primary", key=f"cf_{key}_{r.application_id}"):
            save_confirmed(r.application_id, r.code)
            st.rerun()
    a, b = st.columns([2, 1], vertical_alignment="bottom")
    other = a.selectbox("Or choose the reason yourself" if r.route == "Confirm reason" else "Choose the reason",
                        CODE_CHOICES, index=None, placeholder="Choose a reason code", key=f"oc_{key}_{r.application_id}")
    if b.button("Use this reason", disabled=other is None, key=f"ou_{key}_{r.application_id}", use_container_width=True):
        save_confirmed(r.application_id, other.split(" · ")[0])
        st.rerun()


def open_application(r, key):
    """One application, compact: nudge and buttons first, details underneath."""
    meaning = CATALOG.loc[r.code, "plain_language_meaning"] if r.code in CATALOG.index else "The reviewer's message is not clear."
    fix = CATALOG.loc[r.code, "standard_fix"] if r.code in CATALOG.index else "Check the application and decide the reason."
    name = r.get("business_name") if isinstance(r.get("business_name"), str) else None
    st.markdown(f"#### {r.application_id}{' · ' + name if name else ''}")
    if r.application_status == "Activated":
        place = f" · {r.city}" if isinstance(r.city, str) else ""
        st.markdown(f"{money(r.expected_monthly_tpv_inr_lakh)}/month · {r.business_type}{place} · {r.preferred_language}")
        st.success("This application is already activated. Nothing to do.")
        return
    place = f" · {r.city}" if isinstance(r.city, str) and r.city.strip("- ") else ""
    st.markdown(f"**{r.next_best_action}** · {money(r.expected_monthly_tpv_inr_lakh)}/month · {r.business_type}{place}  \n"
                f"**Why it stalled:** {reason_text(r) if r.route != 'Confirm reason' else 'not confirmed yet'}  \n"
                f"**Follow-up:** {r.follow_up}")
    if r.next_best_action in ("Manual review", "Confirm reason"):
        confirm_reason(r, key)
        return
    if r.human_check.count(";"):
        st.warning("Check before approving: " + "; ".join(r.human_check.split("; ")[1:]).lower())
    if r.next_best_action == "Call merchant":
        st.markdown(f"**What to say on the call** (in {r.preferred_language})  \n"
                    f"1. Say you are calling from the Razorpay onboarding team about application {r.application_id}.  \n"
                    f"2. Explain the problem: {meaning}  \n"
                    f"3. Explain the fix: {fix}  \n"
                    "4. Ask if anything is unclear and help them start the fix while on the call. Do not promise a date or approval.  \n"
                    "5. After the call, send the message below so they have the steps in writing.")
    status = r.approval
    saved = st.session_state.decisions.get(r.application_id, {})
    channel = "WhatsApp" if r.whatsapp_opted_in == "Yes" else "email"
    label = "Message to send after the call" if r.next_best_action == "Call merchant" else "Nudge"
    text = st.text_area(f"{label}, in {r.preferred_language}, by {channel}", saved.get("final_message") or r.nudge_draft,
                        height=175, key=f"t_{key}_{r.application_id}_{abs(hash(r.nudge_draft)) % 10**8}")
    issues = validate(r, text)
    if issues:
        st.error("Fix this before approving: " + "; ".join(issues))
    else:
        st.caption("✓ No dates, promises or waivers · ✓ " + r.preferred_language +
                   (" · ✓ WhatsApp opt-in checked" if channel == "WhatsApp" else " · Email, because the merchant has not opted in to WhatsApp"))
    if status in ("Approved", "Sent", "Rejected"):
        st.markdown(f"Status: **{status}**" + (f" ({saved.get('reason')})" if saved.get("reason") else ""))
    if status in ("Approved", "Sent"):
        a, b = st.columns(2)
        if channel == "WhatsApp":
            a.link_button("💬 Send on WhatsApp", wa_link(text, phones.get(r.application_id)), type="primary", use_container_width=True)
        else:
            a.link_button("✉️ Send by email", mail_link(text, r.application_id), type="primary", use_container_width=True)
        if status == "Approved" and b.button("Mark as sent", key=f"s_{key}_{r.application_id}", use_container_width=True):
            save_decision(r.application_id, "Sent", text)
            st.rerun()
    else:
        a, b, c = st.columns([1, 1.5, 0.9])
        label = "Approve closure" if r.next_best_action == "Close application" else "Approve"
        if a.button(label, key=f"a_{key}_{r.application_id}", type="primary", disabled=bool(issues), use_container_width=True):
            save_decision(r.application_id, "Approved", text)
            st.rerun()
        reason = b.selectbox("Reason for rejecting", ["Wrong reason code", "Wrong language or tone", "Do not contact now", "Other"],
                             index=None, placeholder="Reason for rejecting", key=f"rr_{key}_{r.application_id}",
                             label_visibility="collapsed")
        if c.button("Reject", key=f"r_{key}_{r.application_id}", disabled=reason is None, use_container_width=True):
            save_decision(r.application_id, "Rejected", text, reason)
            st.rerun()
    with st.expander("Application details"):
        msg = r.rejection_message if isinstance(r.rejection_message, str) else "None"
        st.markdown(f"**What it means:** {meaning}  \n**What the merchant must do:** {fix}  \n**Reviewer's message:** {msg}  \n"
                    f"**Step reached:** {r.step_reached} · **Days since last activity:** {int(r.days_since_last_activity)} · "
                    f"**Attempts:** {int(r.attempts)}  \n**Fixable:** {r.fixable} · **Recoverable:** {yn(r.recoverable)} · "
                    f"**WhatsApp opted in:** {r.whatsapp_opted_in}  \n**How the reason was found:** {r.evidence} ({r.diagnosis_source})")
        if pd.notna(r.priority_score):
            days_fix = int(CATALOG.loc[r.code, "typical_days_to_fix"])
            effort = 1 + BASE["priority"]["effort_weight"] * (days_fix - 1)
            st.markdown(f"**Why it ranks #{int(r.priority_rank) if pd.notna(r.priority_rank) else '-'}:** "
                        f"size {math.log1p(r.expected_monthly_tpv_inr_lakh):.2f} (from ₹{r.expected_monthly_tpv_inr_lakh} lakh TPV) × "
                        f"recovery score {r.p_recover:.2f} (lower when inactive longer or after more attempts) ÷ "
                        f"effort {effort:.2f} (fix usually takes {days_fix} days) = **{r.priority_score:.2f}**. "
                        "The recovery score is a rule of thumb, not a measured probability.")
        if r.evidence == "Reason confirmed by a person":
            if st.button("Undo reason confirmation", key=f"u_{key}_{r.application_id}"):
                save_confirmed(r.application_id, None)
                st.rerun()


SHORT_COLS = {"priority_rank": "Priority", "application_id": "Application", "next_best_action": "Action",
              "application_status": "Status", "expected_monthly_tpv_inr_lakh": "TPV (₹ lakh)",
              "approval": "Nudge"}


def pick_and_open(frame, key, height=520):
    """List on the left, selected application on the right, so nothing needs scrolling."""
    left, right = st.columns([1.45, 1.1], gap="large")
    with left:
        t = frame[list(SHORT_COLS)].rename(columns=SHORT_COLS).copy()
        t["Priority"] = pd.to_numeric(t["Priority"], errors="coerce").astype("Int64")
        ev = st.dataframe(t, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                          key=f"tbl_{key}", height=min(35 * len(t) + 38, height))
    rows = ev.selection.rows if ev and ev.selection else []
    with right:
        if rows:
            open_application(frame.iloc[rows[0]], key)
        else:
            st.info("Click an application in the list to open it here.")


TABLE_COLS = {"priority_rank": "Priority", "application_id": "Application", "next_best_action": "Action", "cause": "Reason",
              "expected_monthly_tpv_inr_lakh": "Expected TPV (₹ lakh/month)", "days_since_last_activity": "Days since last activity",
              "preferred_language": "Preferred language", "channel": "Channel", "approval": "Status"}


def table(frame):
    t = frame[list(TABLE_COLS)].rename(columns=TABLE_COLS).copy()
    t["Priority"] = pd.to_numeric(t["Priority"], errors="coerce").astype("Int64")
    return t


SEND_ACTIONS = ["Send fix nudge", "Send resume reminder", "Send final nudge"]


def bulk_send(frame):
    """Approve and send many nudges at once. Only simple, safe cases; everything else stays one by one."""
    ready = frame[(frame["approval"] == "Waiting") & frame["next_best_action"].isin(SEND_ACTIONS)
                  & (frame["guardrail_pass"] == True) & ~frame["human_check"].astype(str).str.contains(";")]  # noqa: E712
    approved = frame[frame["approval"] == "Approved"]
    with st.expander(f"Send in bulk · {len(ready)} ready to approve · {len(approved)} approved, not sent"):
        st.caption("Bulk approval covers only fix nudges and reminders that passed the safety check and need no extra check. "
                   "Calls, manual review, closures, compliance cases and reasons read from a message stay one by one. "
                   "Use the filters above to choose which applications to include.")
        a, b, c = st.columns(3)
        with a.popover(f"Approve {len(ready)} nudges", use_container_width=True, disabled=ready.empty):
            st.markdown(f"**Read before approving.** These {len(ready)} nudges will be approved as written.")
            st.dataframe(ready[["application_id", "next_best_action", "preferred_language", "channel", "nudge_draft"]]
                         .rename(columns={"application_id": "Application", "next_best_action": "Action",
                                          "preferred_language": "Language", "channel": "Channel", "nudge_draft": "Nudge"}),
                         hide_index=True, height=260)
            if st.button(f"Yes, approve {len(ready)} nudges", type="primary", key="bulk_ok"):
                for _, r in ready.iterrows():
                    save_decision(r.application_id, "Approved", r.nudge_draft)
                st.rerun()
        rows = []
        for _, r in approved.iterrows():
            text = st.session_state.decisions.get(r.application_id, {}).get("final_message") or r.nudge_draft
            wa = r.whatsapp_opted_in == "Yes"
            rows.append({"application_id": r.application_id, "business_name": r.get("business_name"),
                         "phone": phones.get(r.application_id), "channel": "WhatsApp" if wa else "Email",
                         "preferred_language": r.preferred_language, "message": text,
                         "whatsapp_link": wa_link(text, phones.get(r.application_id)) if wa else ""})
        b.download_button(f"Download send list ({len(approved)})", pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
                          f"activateiq_send_list_{datetime.now():%d%b%Y}.csv", disabled=approved.empty,
                          use_container_width=True, help="CSV with channel, language and message for each approved nudge, "
                                                          "ready to upload to the WhatsApp or email tool")
        if c.button(f"Mark {len(approved)} as sent", disabled=approved.empty, use_container_width=True, key="bulk_sent"):
            for _, r in approved.iterrows():
                save_decision(r.application_id, "Sent",
                              st.session_state.decisions.get(r.application_id, {}).get("final_message") or r.nudge_draft)
            st.rerun()


# ---------------- Dashboard ----------------
if page == "Dashboard":
    st.info("**Where to start:** open **Applications**, use the filters to pick a group (for example Action = Call merchant), "
            "click an application, read the message and approve it. Use **Add an application** for new cases, and "
            "**Why merchants stall** for what the product team should fix.")
    c = st.columns(4)
    c[0].metric("Stalled or rejected applications", s["non_activated"])
    c[1].metric("Fixable", s["fixable"])
    c[2].metric("Recoverable", s["recoverable"])
    c[3].metric("Expected TPV of recoverable (per month)", money(s["recoverable_tpv_lakh"]))
    c = st.columns(4)
    c[0].metric("Fixable but inactive too long", s["fixable_but_stale"])
    c[1].metric("Reason to confirm", s["confirm_reason"] + s["clarify"])
    c[2].metric("Closed (restricted business)", s["closed_r10"])
    c[3].metric("Routed to compliance", s["compliance_r12"])
    c = st.columns(4)
    c[0].metric("Expected TPV of all 75 (per month)", money(s["non_activated_tpv_lakh"]))
    c[1].metric("Nudges waiting for approval", int(((df["approval"] == "Waiting") & (df["nudge_draft"] != "")).sum()))
    c[2].metric("Nudges approved", int((df["approval"] == "Approved").sum()))
    c[3].metric("Nudges sent", int((df["approval"] == "Sent").sum()))
    st.caption("TPV figures are the expected monthly TPV given in the application data. They are not actual revenue or "
               "recovered revenue: the data has no results after outreach.")

    l, r = st.columns(2)
    acts = df["next_best_action"].value_counts().reset_index()
    acts.columns = ["Action", "Applications"]
    l.markdown("#### What to do with each application")
    l.altair_chart(alt.Chart(acts).mark_bar(cornerRadiusEnd=5).encode(
        x=alt.X("Applications:Q"), y=alt.Y("Action:N", sort="-x", title=None),
        color=alt.Color("Action:N", scale=alt.Scale(domain=list(ACTION_COLORS), range=list(ACTION_COLORS.values())), legend=None),
        tooltip=["Action", "Applications"]).properties(height=250), use_container_width=True)
    steps = df["step_reached"].value_counts().reset_index()
    steps.columns = ["Step reached", "Applications"]
    r.markdown("#### Step where applications stalled")
    r.altair_chart(alt.Chart(steps).mark_bar(cornerRadiusEnd=5, color=BLUE).encode(
        x="Applications:Q", y=alt.Y("Step reached:N", sort="-x", title=None),
        tooltip=["Step reached", "Applications"]).properties(height=250), use_container_width=True)

    st.markdown("#### Recoverable applications, highest priority first")
    st.caption("Priority is based on expected TPV, days since last activity, attempts, and how long the fix usually takes.")
    st.dataframe(table(df[df["recoverable"] == True]), hide_index=True, use_container_width=True)  # noqa: E712

# ---------------- Applications ----------------
elif page == "Applications":
    if st.session_state.pop("clear_box", False):
        st.session_state.q_box = ""
    with st.form("search"):
        a, b = st.columns([4, 1])
        q = a.text_input("Search", placeholder="Search by application ID, business name, city, industry or business type",
                         label_visibility="collapsed", key="q_box")
        go = b.form_submit_button("Search", type="primary", use_container_width=True)
    if go:
        if q.strip():
            st.session_state.app_query = q.strip()
        else:
            st.session_state.app_query = ""
            st.warning("Type an application ID, business name, city, industry or business type, then press Search.")
    found = st.session_state.get("app_query", "")
    if not isinstance(found, str):
        found = ""
    activated = load_data(BASE)[0].query("application_status == 'Activated'").copy()
    activated["next_best_action"], activated["approval"] = "Nothing to do", "-"
    every = pd.concat([df, activated], ignore_index=True)
    f0, f1, f2, f3 = st.columns(4)
    f_app = f0.selectbox("Application status", ["Stalled", "Rejected", "Activated"], index=None, placeholder="All")
    f_status = f1.selectbox("Nudge status", ["Waiting", "Approved", "Sent", "Rejected"], index=None, placeholder="All")
    f_action = f2.selectbox("Action", sorted(df["next_best_action"].unique()), index=None, placeholder="All")
    f_lang = f3.selectbox("Preferred language", sorted(df["preferred_language"].dropna().unique()), index=None,
                          placeholder="All")
    hit = every
    if found:
        fields = [c for c in ["application_id", "business_name", "city", "industry", "business_type"] if c in every.columns]
        hay = every[fields].astype(str).apply(lambda col: col.str.lower())
        hit = hit[hay.apply(lambda col: col.str.contains(found.lower(), regex=False)).any(axis=1)]
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"Showing results for **{found}**")
        if c2.button("Clear search", use_container_width=True):
            st.session_state.app_query = ""
            st.session_state.clear_box = True
            st.rerun()
    if f_app:
        hit = hit[hit["application_status"] == f_app]
    if f_status:
        hit = hit[hit["approval"] == f_status]
    if f_action:
        hit = hit[hit["next_best_action"] == f_action]
    if f_lang:
        hit = hit[hit["preferred_language"] == f_lang]
    if hit.empty:
        st.error("No applications match this search.")
    else:
        waiting = int((hit["approval"] == "Waiting").sum())
        st.caption(f"{len(hit)} application{'s' if len(hit) > 1 else ''} · {waiting} waiting for approval · "
                   "highest priority first")
        bulk_send(hit)
        hit = hit.assign(_act=hit["application_status"] == "Activated")
        pick_and_open(hit.sort_values(["_act", "priority_rank", "priority_score"], ascending=[True, True, False],
                                      na_position="last"), "list")

# ---------------- Add an application ----------------
elif page == "Add an application":
    st.markdown("#### Add stalled applications")
    st.markdown("ActivateIQ finds the reason, decides the action and writes the nudge for each application you add.")
    one, many = st.tabs(["One application", "Upload a file (Excel or CSV)"])
    codes = [f"{k} · {v}" for k, v in CATALOG["reviewer_reason"].items() if k != "R13"]
    with many:
        up = st.file_uploader("Upload file", type=["csv", "xlsx"], label_visibility="collapsed",
                              key=f"upload_{st.session_state.get('upload_n', 0)}")
        if up is not None:
            try:
                raw = bulk.read_file(up)
            except Exception:
                raw = None
                st.error("This file could not be read. Upload a .csv or .xlsx file.")
            if raw is not None:
                existing = set(load_data(BASE)[0]["application_id"]) | set(added.get("application_id", []))
                good, problems = bulk.check(raw, existing, set(CATALOG.index), len(added) + 1)
                if problems:
                    st.error(f"{len(problems)} row{'s' if len(problems) > 1 else ''} cannot be added. Fix them in the file "
                             "and upload it again, or add the other rows now.")
                    st.markdown("\n".join(f"- {p}" for p in problems[:20]) + ("\n- …" if len(problems) > 20 else ""))
                if len(good):
                    st.success(f"{len(good)} row{'s' if len(good) > 1 else ''} ready to add.")
                    dups = bulk.duplicate_warnings(good, added)
                    if dups:
                        st.warning("These look like merchants already in the list. If added, they go to Manual review, so "
                                   "the merchant does not get two messages:\n" + "\n".join(f"- {d}" for d in dups[:20]))
                    st.dataframe(good[["application_id", "business_name", "business_type", "city", "step_reached",
                                       "application_status", "rejection_code"]], hide_index=True, use_container_width=True)
                    if st.button(f"Add {len(good)} application{'s' if len(good) > 1 else ''}", type="primary"):
                        good["signup_date"] = datetime.now().strftime("%d %b %Y")
                        pd.concat([added, good], ignore_index=True).to_csv(ADDED, index=False)
                        st.session_state.bulk_added = len(good)
                        st.session_state.upload_n = st.session_state.get("upload_n", 0) + 1
                        st.rerun()
        if st.session_state.get("bulk_added"):
            st.success(f"Added {st.session_state.pop('bulk_added')} applications. They are now in Applications.")
        st.markdown("**What the file should look like**")
        st.markdown("An Excel (.xlsx) or CSV file with one application per row and these columns. Rows with a missing "
                    "required value, or a value that is not allowed, are not added: the app lists each such row and what to fix.")
        st.dataframe(bulk.guide(), hide_index=True, use_container_width=True, height=598,
                     column_config={"What it can hold": st.column_config.TextColumn(width="large")})
        st.download_button("Download a sample file (CSV)", bulk.template().to_csv(index=False), "activateiq_upload_sample.csv")
    with one:
        with st.form("new_app"):
            business_name = st.text_input("Business name")
            a, b, c = st.columns(3)
            business_type = a.selectbox("Business type", ["Proprietorship", "Private Limited", "Partnership", "LLP", "Trust / NGO"], index=None)
            industry = b.text_input("Industry")
            city = c.text_input("City")
            language = a.selectbox("Preferred language", ["English", "Hinglish", "Hindi", "Tamil", "Kannada", "Marathi"], index=None)
            whatsapp = b.selectbox("WhatsApp opted in", ["Yes", "No"], index=None)
            phone = c.text_input("Phone number (optional)")
            step = a.selectbox("Step reached", ["Business details", "KYC docs", "Bank verification", "Website/App review"], index=None)
            status = b.selectbox("Application status", ["Stalled", "Rejected"], index=None)
            tpv = c.number_input("Expected monthly TPV (₹ lakh)", min_value=0.0, value=None, step=0.1)
            days_in = a.number_input("Days since last activity", min_value=0, value=None, step=1)
            attempts_in = b.number_input("Attempts", min_value=1, value=None, step=1)
            contacts = c.number_input("Support contacts", min_value=0, value=None, step=1)
            code = st.selectbox("Reason code from the reviewer (leave empty if there is none)", codes, index=None, placeholder="No reason code")
            msg = st.text_area("Reviewer's message (leave empty if there is none)")
            submitted = st.form_submit_button("Check application", type="primary")
        if submitted:
            required = {"Business type": business_type, "Preferred language": language, "WhatsApp opted in": whatsapp,
                        "Step reached": step, "Application status": status, "Expected monthly TPV": tpv,
                        "Days since last activity": days_in, "Attempts": attempts_in}
            missing = [k for k, v in required.items() if v is None]
            if missing:
                st.error("Please fill in: " + ", ".join(missing))
            else:
                existing = set(load_data(BASE)[0]["application_id"]) | set(added.get("application_id", []))
                n = len(added) + 1
                while f"N{n:04d}" in existing:
                    n += 1
                new_id = f"N{n:04d}"
                row = {"application_id": new_id, "business_name": business_name.strip() or None, "business_type": business_type, "industry": industry or "-", "city": city or "-",
                       "preferred_language": language, "signup_date": datetime.now().strftime("%d %b %Y"),
                       "expected_monthly_tpv_inr_lakh": tpv, "whatsapp_opted_in": whatsapp, "step_reached": step,
                       "application_status": status, "days_since_last_activity": int(days_in), "attempts": int(attempts_in),
                       "support_contacts": int(contacts or 0), "rejection_code": code.split(" · ")[0] if code else None,
                       "rejection_message": msg.strip() or None, "phone": phone.strip() or None}
                pd.concat([added, pd.DataFrame([row])], ignore_index=True).to_csv(ADDED, index=False)
                st.session_state.last_added = new_id
                st.rerun()
        if st.session_state.get("last_added") in set(df["application_id"]):
            st.success(f"Added as {st.session_state.last_added}. It is now in Applications.")
            open_application(df[df["application_id"] == st.session_state.last_added].iloc[0], "n")

# ---------------- Why merchants stall ----------------
elif page == "Why merchants stall":
    st.markdown("#### Why merchants stall")
    st.markdown("These are the reasons behind the **fixable** applications, grouped together. The biggest groups are the ones "
                "the product team should fix first, because one product change helps many merchants at once.")
    tc = s["top_causes"].reset_index().rename(columns={"group": "Reason", "applications": "Applications",
                                                        "expected_tpv_lakh": "Expected TPV (₹ lakh/month)"})
    st.altair_chart(alt.Chart(tc).mark_bar(cornerRadiusEnd=5, color=BLUE).encode(
        x="Applications:Q", y=alt.Y("Reason:N", sort="-x", title=None, axis=alt.Axis(labelLimit=420)),
        tooltip=["Reason", "Applications", "Expected TPV (₹ lakh/month)"]).properties(height=230), use_container_width=True)
    stopped = df[df["code"] == "R13"]
    top_step = stopped["step_reached"].value_counts()
    name = tc[tc["Reason"].str.startswith("Name mismatch")]
    st.markdown("**What this means**")
    st.markdown(
        f"- **{len(stopped)} merchants stopped without any rejection.** Most stopped at *{top_step.index[0]}* "
        f"({top_step.iloc[0]} merchants). A reminder that names the exact step is the fix.\n"
        f"- **{int(name['Applications'].sum()) if len(name) else 0} were rejected because names did not match** "
        "(the PAN name, business name or bank account name).\n"
        "- **Website issues** (missing policy pages, website not live, category different from website) come next.")
    st.markdown('<div class="aiq-box"><b>Fix to ask the product team for first:</b> check that the PAN name, business name and '
                'bank account name match while the merchant is filling in the form, before they upload documents.</div>',
                unsafe_allow_html=True)

# ---------------- How accurate is it ----------------
elif page == "How accurate is it":
    st.markdown("#### How accurate is it")
    ok, n, _ = classifier_check(df)
    fails, total, caught = guardrail_tests(df)
    c = st.columns(3)
    c[0].metric("Reason codes read correctly", f"{ok} of {n}")
    c[1].metric("Nudges with no dates, promises or waivers", f"{total - fails} of {total}")
    c[2].metric("Unsafe test nudges stopped", f"{len(caught[caught['issues'] != ''])} of {len(caught)}")
    st.markdown(f"""
**Reason codes read correctly.** {ok} applications have both a reason code and a reviewer's message. We hid the code, read the
message, and checked if we got the same code. The first version got 40 of 49 right; the mistakes are listed below, and we fixed them.

**Nudges with no dates, promises or waivers.** Every nudge is checked before it can be approved: no dates, no promises, no waivers,
no compliance reasons, no workaround for restricted businesses, the merchant's preferred language, and WhatsApp only if opted in.

**Unsafe test nudges stopped.** We wrote {len(caught)} unsafe nudges on purpose to make sure the check catches them.""")
    st.markdown("#### Word rules vs AI model")
    t = rules_vs_ai(BASE)
    cs = compare_summary(t)
    if cs["ai_answered"] == 0:
        st.info("The AI model has not read the messages yet. Run `python -m activateiq.compare` once with an API key "
                "(see README). Its answers are saved, so this page then works without a key.")
    else:
        c = st.columns(3)
        c[0].metric("Word rules: code read correctly", f"{cs['rules_right']} of {cs['cases']}")
        c[1].metric("AI model: code read correctly", f"{cs['ai_right']} of {cs['ai_answered']}")
        c[2].metric("Message-only cases where both agree", f"{cs['blank_agree']} of {cs['blank_cases']}")
        st.markdown(f"""
**How we tested.** {cs['cases']} applications have both a reason code and a reviewer's message. We hid the code and let each
reader guess it from the message alone. The word rules were written while looking at these same messages, so their score is
flattering; the AI model never saw them before, so its score is the fairer one.
**How the app uses it.** For the {cs['blank_cases']} applications with only a message, both readers read it. If they agree, we keep
the code. If they disagree, a person decides (Manual review). The AI model never decides alone.""")
        diff = t[t["word_rules"] != t["ai_model"]]
        with st.expander(f"Messages where the two readers disagree ({len(diff)})"):
            st.dataframe(diff[["application_id", "test", "real_code", "word_rules", "ai_model", "rejection_message"]].rename(
                columns={"application_id": "Application", "test": "Test", "real_code": "Real code", "word_rules": "Word rules",
                         "ai_model": "AI model", "rejection_message": "Reviewer's message"}), hide_index=True, use_container_width=True)
    with st.expander("Mistakes in the first version"):
        st.markdown("- *GSTIN inactive / legal name mismatch* was read as a bank problem (R04) instead of GST (R02)\n"
                    "- *Document not readable* was missed (R05)\n- *Site requires login* was missed (R07)\n"
                    "- *Is business category ko support nahi kar sakte* was missed (R10)\n- *Compliance review pending* was missed (R12)")
    with st.expander("The unsafe test nudges"):
        st.dataframe(caught.rename(columns={"planted_draft": "Test nudge", "action": "Action", "language": "Language",
                                            "issues": "What the check caught"}), hide_index=True, use_container_width=True)
    st.markdown("#### Test against your own answers (30 cases)")
    st.caption("You label 30 applications yourself, without looking at what the app says. The app then compares. "
               "The 30 cases include every kind: reason code given, reason read from a message, no rejection, "
               "restricted business and compliance. Your labels are saved in gold_labels.csv, separate from the app's answers.")
    base_df = compute("", "{}", CODE_VERSION)[0]  # the app's own answers, before any person confirmed a reason
    g = gold_check(base_df)
    if g is None:
        st.info("No labels yet. Open **Label the 30 cases** below and fill in the four answer columns.")
    else:
        res, wrong = g
        names = {"code": "Reason code", "route": "Decision", "recoverable": "Recoverable", "action": "Action"}
        cols = st.columns(4)
        for i, (k, label) in enumerate(names.items()):
            if k in res:
                cols[i].metric(f"{label} correct", f"{res[k][0]} of {res[k][1]}")
        st.caption(f"{res['labelled_cases']} cases labelled so far.")
        if len(wrong):
            with st.expander(f"Where the app and your labels differ ({len(wrong)})"):
                st.dataframe(wrong, hide_index=True, use_container_width=True)
    with st.expander("Label the 30 cases"):
        gold = pd.read_csv(ROOT / "gold_labels.csv", dtype=str)
        cc = {k: st.column_config.SelectboxColumn(k.replace("gold_", "Your ").replace("_", " "), options=v)
              for k, v in GOLD_CHOICES.items()}
        cc["notes"] = st.column_config.TextColumn("Notes")
        edited = st.data_editor(gold, column_config=cc, hide_index=True, use_container_width=True, key="gold_editor",
                                disabled=[c for c in gold.columns if c not in list(GOLD_CHOICES) + ["notes"]])
        if st.button("Save labels", type="primary"):
            edited.to_csv(ROOT / "gold_labels.csv", index=False, encoding="utf-8-sig")
            st.success("Saved.")
            st.rerun()
    rej = {k: v for k, v in st.session_state.decisions.items() if v.get("status") == "Rejected"}
    if rej:
        st.markdown(f"**Nudges rejected by the team: {len(rej)}**")
        st.dataframe(pd.DataFrame.from_dict(rej, orient="index").rename_axis("Application").reset_index()[
            ["Application", "reason", "decided_at"]].rename(columns={"reason": "Reason", "decided_at": "When"}), hide_index=True)
