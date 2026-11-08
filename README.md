# ActivateIQ: onboarding and KYC drop-off recovery

Razorpay Campus AI Build-a-thon, Problem 3.
For every stalled or rejected application, ActivateIQ (1) diagnoses why it stalled, (2) explains the fix in simple language in the
merchant's preferred language, (3) decides whether the case is recoverable or must be closed or routed to compliance, and
(4) drafts the right nudge. It also tells the product team which fixable causes affect the most merchants.

**Rules decide, AI explains, a person approves every nudge.**

## How to run it
```bash
pip install -r requirements.txt
streamlit run app.py              # the app
python -m activateiq.pipeline     # checks all 75 non-activated applications and writes outputs/
python -m activateiq.evaluate     # test results
```

## Pages in the app
- **Sidebar, under the menu**: **Download results** gives an Excel file with every application (reason, decision, action, nudge, approval status) and the summary. **Reset** removes added applications and all approve or reject decisions, after you confirm.
- **Dashboard**: headline numbers (non-activated, fixable, recoverable, expected TPV), what to do with each application, the step where applications stalled, and the recoverable applications in priority order.
- **Applications**: all 100 applications, highest priority first, with a search box (application ID, business name, city, industry, business type; press Search) and filters for application status, nudge status, action and language (they apply straight away). Click an application to read, edit, approve or reject its nudge. Every edit goes through the safety check again. After approval, **Send on WhatsApp** opens WhatsApp with the nudge filled in (only if the merchant opted in; a person still presses send). Otherwise **Send by email**. Decisions are saved to `outputs/decisions.csv`. **Send in bulk** (on the same page) approves many fix nudges and reminders at once, after showing them all; only nudges that passed the safety check and need no extra check are included. It then gives a send list (CSV with channel, language and message) to upload to the WhatsApp or email tool, and marks them as sent.
- **Add an application**: the onboarding team enters one stalled application, or uploads an Excel or CSV file with many (same columns as the P3_Applications sheet; a sample file can be downloaded on the page). Rows with problems are listed with the row number and are not added. Each added application gets its reason, action and nudge straight away. Added applications are saved to `data/added_applications.csv`.
- **Why merchants stall**: the fixable reasons grouped, biggest first (the top systemic causes), and the product fix to ship first.
- **How accurate is it**: how often the reason code is read correctly, word rules vs AI model, the safety check on every nudge, the unsafe test nudges it caught, and the test against your own labels.
- The limits (30 days, 3 attempts, 10 calls) are set in `config.yaml`.
- Colours follow Razorpay's blue and navy (`.streamlit/config.toml`). No Razorpay logo is used.

## How each application is handled
1. **Find the reason.**
   - Rejection code given → look it up in the rejection catalog.
   - No rejection code and no rejection message → the merchant stopped (R13, as the catalog defines it).
   - Rejection message only (4 applications: A3022, A3028, A3081, A3051) → the reason is only a **proposal** until a person confirms it on screen (**Confirm reason**). No message is written and nothing is closed before that; A3051 (looks like R10) is closed only after a person confirms it. Two readers propose the reason: word rules, and an AI model (Claude) that must pick one of the catalog codes. If they agree, we keep the code; if they disagree, a person decides (Manual review). A person confirms every code read from a message before anything is sent.
2. **Check restricted and compliance cases first.**
   - R10 restricted business category → close the application politely, with no workaround. A person confirms first, because closing cannot be undone.
   - R12 compliance screening hit → route to compliance. The merchant is only told it is under review and never sees the reason.
3. **Fixable or recoverable?** Fixable = the rejection catalog says it can be fixed. Recoverable = fixable, inactive for 30 days or less, and fewer than 3 attempts (both can be changed). The rest are "fixable but inactive too long".
4. **Priority** = expected TPV × recovery likelihood, lowered slightly for fixes with more typical days to fix. Recovery likelihood is our own assumption (lower when the reason was read from the message, when the merchant has been inactive longer, or has tried more times; slightly higher if they contacted support). The data has no outcomes, so this is not a prediction model.
   - Reason code **and** a message that disagree: if the message points to screening (R12) or a restricted category (R10), or the code is R10 and the message points to something else, nothing is sent or closed. The case goes to **Manual review** until a person chooses the reason. Other disagreements are flagged for the person approving the nudge.
   - The same merchant twice (same business name and phone, new ID): the later copy goes to **Manual review**, so the merchant gets one message.
5. **One action per application**: Call merchant (top 10 by priority), Send fix nudge, Send resume reminder (R13), Send final nudge (inactive too long), Manual review, Close application, Route to compliance.
6. **Nudge and safety check.** Nudges come from a saved set of messages (13 message types × 6 languages) that uses only the catalog's standard fix. WhatsApp only if the merchant opted in, otherwise email (the Data Pack has no email field, so we assume one exists). The safety check stops dates, promises, waivers, compliance reasons, workarounds for restricted categories, the wrong language and WhatsApp without opt-in. Nothing is sent from the app.

## Results on the Data Pack (default assumptions)
| | |
|---|---|
| Non-activated applications | 75 |
| Fixable | 67 (₹933.9 lakh/month expected TPV) |
| Recoverable | 44 (₹668.8 lakh/month; about ₹419.2 lakh likely recovered, estimate) |
| Fixable but inactive too long | 23 |
| Closed (R10) / routed to compliance (R12) | 5 / 3 |
| Reason read from the message (no code) | 4: A3022 → R05, A3028 → R01, A3081 → R09, A3051 → R10 |
| Safety check | 75/75 nudges pass; 5/5 planted bad nudges stopped |
| Reason read from the message vs the reviewer's code (49 applications with both) | first try 40/49 (82%); after fixing the word rules 49/49 (not a fair test, see below) |

Top systemic causes among fixable applications: merchant stopped with no rejection (22, ₹307.6 lakh), name mismatch on PAN or bank account (16, ₹132.2 lakh), document problems (14, ₹306.9 lakh).

## Limits to say out loud
- **Hand-checked answers:** `gold_labels.csv` lists 30 applications (every language, every reason code, the 4 with no code, and all R10 and R12). Fill in your own answers; the app then shows real accuracy.
- **First-try mistakes when reading messages** (fixed, but they show the risk): "GSTIN inactive" was read as a bank problem (R04 instead of R02); "not readable", "requires login", "support nahi kar sakte" and "Compliance review pending" were missed.
- **Every threshold is an assumption**, which is why they can be changed in the app. Expected TPV is the merchant's own estimate.
- **The nudges** were written once by Claude during this build and are reused. Tamil, Kannada and Marathi should be checked by a native speaker.
- **No phone numbers or emails** in the Data Pack. WhatsApp opens a contact picker unless a number is added.
- **No real outcomes**: the data is a snapshot. Measuring real recovered TPV needs a pilot with a control group.

## Tests
`python -m unittest -v` runs 23 automated checks: every non-activated application counted once, TPV totals match the Data Pack, R01/R05/R10/R12/R13 handling, the four message-only cases waiting for a person, confirmed reasons unlocking messages, priority ranks 1 to N without gaps, WhatsApp only with opt-in, six languages, the safety check, and bulk upload.

## Hand-labelled test (30 cases)
On **How accurate is it → Label the 30 cases**, label each case yourself without looking at the app's answer, then press Save. The page then shows how many reason codes, decisions, recoverable flags and actions the app got right, and lists every difference. Labels are saved in `gold_labels.csv`, separate from the app's answers.

## AI model (Claude) and cost
- Switched on in `config.yaml` (`use_llm_fallback: true`, `llm_model: claude-opus-5-5`). It is used for one job only: reading rejection messages that have no code. Everything else is rules.
- One-time run, with a key: `export ANTHROPIC_API_KEY=...` then `python -m activateiq.compare`. It reads the 53 rejection messages (49 to test against the real code, 4 real message-only cases) and saves the answers in `llm_answers.json`. Expected cost: under 1 US dollar.
- After that, no key is needed: the app and the **How accurate is it** page use the saved answers. Never put the key in a file you submit; `.streamlit/secrets.toml` is ignored by git if you prefer a file over the terminal.
- Without a key the app still works: the word rules read the messages, as before.

## Files
`config.yaml` (assumptions) · `activateiq/load.py` · `classify.py` (reading rejection messages: word rules + AI model) · `compare.py` (one-time AI run) · `rules.py` (decisions) · `score.py` (priority) · `messages.py` + `templates.json` (nudges and safety check) · `pipeline.py` · `evaluate.py` · `app.py` · `outputs/`
