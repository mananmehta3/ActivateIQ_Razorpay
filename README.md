# ActivateIQ: onboarding and KYC drop-off recovery

Razorpay Campus AI Build-a-thon, Problem 3.

## The problem

A merchant signs up on Razorpay but does not finish onboarding. Some get stuck at KYC documents, bank verification or website review. Some are asked to fix something, for example a PAN name that does not match. Some just stop. Until the merchant is activated, they cannot take payments, and Razorpay earns nothing from them.

In the Data Pack:
- 75 of the 100 applications are not activated.
- **67 of them are fixable**, with **₹933.9 lakh a month** of expected TPV waiting.
- **22 merchants stopped without any rejection at all.**

The onboarding team cannot call everyone. Today they have to work out each merchant's reason, the fix and the next step by hand. Merchants often do not understand what went wrong, so they do not come back.

## Why we built ActivateIQ

Razorpay already sends drop-off reminders. ActivateIQ adds what a reminder alone cannot do:

1. **The exact reason.** For every application, it finds why it stalled: from the reason code, from the reviewer's message, or "merchant stopped" (R13).
2. **A clear fix in the merchant's language.** Messages in English, Hindi, Hinglish, Tamil, Kannada and Marathi say exactly what to do, using the catalog's standard fix.
3. **Where to spend the team's time.**
   - It separates applications that can be recovered from those that should be closed (restricted business, R10) or sent to compliance (R12).
   - It ranks the recoverable ones, so the team calls the most valuable merchants first.
4. **What the product team should fix.** It shows which reasons affect the most merchants.

**Rules decide, AI explains, humans approve.** Every decision comes from rules that give the same answer every time. The AI model reads reviewer messages in any language and explains unclear cases to the team. A person approves every reason it proposes and every message before it is sent.

## How to run it

```bash
pip install -r requirements.txt
streamlit run app.py              # the app
python -m activateiq.pipeline     # runs all 75 non-activated applications and writes outputs/
python -m activateiq.evaluate     # test results
python -m unittest -v             # 35 automated checks
```

## Pages in the app

- **Dashboard:**
  - headline numbers (applications to act on, fixable, recoverable, expected TPV);
  - what to do with each application;
  - the step where applications stalled;
  - the priority list.
- **Applications:**
  - all 100 applications, highest priority first;
  - search by application ID, business name, city, industry or business type;
  - filters for application status, nudge status, action and language.
  - Click an application to read, edit, approve or reject its nudge. Every edit goes through the safety check again.
  - **Send in bulk** approves simple nudges at once after showing them all, gives a send list (CSV) for the WhatsApp or email tool, and marks them as sent.
- **Add an application:**
  - Enter one application, or upload an Excel or CSV file with many. The page shows the columns and allowed values.
  - Rows with problems (missing values, values not allowed, negative or part numbers, existing IDs) are listed by row number and not added.
  - A merchant already in the list (same business name and phone) is flagged.
- **Why merchants stall:** the fixable reasons grouped, biggest first (the top systemic causes), and the product fix to ship first.
- **How accurate is it:**
  - reason codes read correctly;
  - word rules vs AI model;
  - the safety check;
  - the bad test messages it caught;
  - the test against hand labels.
- **Sidebar:**
  - **Download results** gives an Excel file with every application and the summary.
  - **Reset** removes added applications, approve/reject/sent marks and reasons chosen by a person. Gold labels are kept.

The limits (30 days, 3 attempts, 10 calls a day) are in `config.yaml`. The colours follow Razorpay's blue and navy, and no Razorpay logo is used.

## How each application is handled

The full description is in [ARCHITECTURE.md](ARCHITECTURE.md).

1. **Find the reason.**
   - Reason code given → look it up in the rejection catalog.
   - No code and no message → the merchant stopped (R13, as the catalog defines it).
   - Reviewer's message only (A3022, A3028, A3081, A3051) → word rules and an AI model (Claude) both read it. The reason is only a **proposal** until a person confirms it on screen. No message is written and nothing is closed before that.
   - Code and message disagree → if the message points to screening (R12) or a restricted category (R10), or the code is R10 and the message points to something else, a person decides first (**Manual review**).
   - The same merchant twice → the later copy goes to Manual review, so the merchant gets one message.
2. **Restricted and compliance cases first.**
   - **R10:** close politely, with no workaround. A person confirms first, because closing cannot be undone.
   - **R12:** route to compliance. The merchant is only told the application is under review.
3. **Fixable or recoverable?**
   - **Fixable:** the rejection catalog says the reason can be fixed.
   - **Recoverable:** fixable, inactive for 30 days or less, and fewer than 3 attempts.
4. **Priority** = `log(1 + expected TPV) × recovery score ÷ effort`.
   - The recovery score is a rule of thumb, not a prediction, because the data has no outcomes. It falls with days inactive and attempts, and rises if the merchant contacted support.
   - Effort comes from the catalog's typical days to fix.
   - Each application shows why it ranks where it does.
5. **One action per application:**
   - Call merchant (top 10 by priority)
   - Send fix nudge
   - Send resume reminder (R13)
   - Send final nudge (fixable but inactive too long)
   - Confirm reason
   - Manual review
   - Close application
   - Route to compliance
   - Follow-up: Day 0, 3 and 7, then stop.
6. **Nudge and safety check.**
   - Nudges come from fixed templates (6 languages) that use only the catalog's standard fix.
   - WhatsApp is used only if the merchant opted in, and email otherwise.
   - The safety check stops dates, promises, waivers, compliance reasons, workarounds for restricted categories, the wrong language and WhatsApp without opt-in.
   - Nothing is sent without a person's approval.

## Results on the Data Pack

| | |
|---|---|
| Applications to act on (not activated) | 75 (₹1,038.4 lakh/month expected TPV) |
| Fixable | 67 (₹933.9 lakh/month) |
| Recoverable (on the priority list) | 42 (₹611.7 lakh/month): 10 calls, 15 fix nudges, 17 resume reminders |
| Fixable but inactive too long | 22 (one final nudge each) |
| Reason to be confirmed by a person | 4 (A3022 → R05, A3028 → R01, A3081 → R09, A3051 → R10) |
| Closed (R10) / routed to compliance (R12) | 4 / 3 |
| Safety check | 75/75 messages pass; 5/5 deliberately bad messages stopped |
| Reason read from the message vs the reviewer's code (49 applications with both) | word rules 49/49, AI model 49/49 (they agree on all 49) |
| Hand-labelled test (30 cases) | reason code 20/20; route 20/30; recoverable 14/30 (see below) |

Expected TPV is the merchant's own estimate of monthly volume, not recovered revenue.

**Top systemic causes among fixable applications:**
- merchant stopped with no rejection: 22 (₹307.6 lakh);
- name mismatch on PAN or bank account: 16 (₹132.2 lakh);
- document problems: 14 (₹306.9 lakh).

## Limits to say out loud

- **The 49/49 score is flattering.** The word rules first scored 40/49 and were fixed on the same rows. For example, "GSTIN inactive" was read as a bank problem (R04 instead of R02), and "not readable", "requires login" and "support nahi kar sakte" were missed. The AI model and the hand-labelled test are the independent checks.
- **Hand-labelled test:** most differences are about definitions, not wrong reasons. The 7 applications with no code and no message were labelled Manual review, while the app treats them as R13, as the brief says ("the merchant just stopped"). Merchants with exactly 3 attempts were labelled recoverable, while the rule is *fewer than* 3. All differences are listed on the How accurate is it page.
- **Every limit is an assumption** (30 days, 3 attempts, 10 calls), and each can be changed in `config.yaml`.
- **No phone numbers or emails** in the Data Pack. Email is assumed to exist, because every signup needs one. WhatsApp opens a contact picker unless a number was added.
- **No real outcomes:** the data is a snapshot. Measuring real recovered TPV needs a pilot with a control group.

## Tests

`python -m unittest -v` runs 35 automated checks:
- counts and TPV totals match the Data Pack;
- R01, R05, R10, R12 and R13 handling;
- message-only cases wait for a person;
- priority ranks run 1 to N with no gaps;
- WhatsApp only with opt-in, and six languages;
- the safety check and bulk upload;
- the edge cases: negative and part numbers, code and message disagreeing, R10 checked before closing, duplicate merchants;
- the live AI model, using a stand-in, so the tests never call the API: it reads a Hindi-script message, falls back to a person on an error, saves answers, and makes no call without a key.

## AI model (Claude) and cost

The AI model is Claude (`claude-opus-5-5`). It is never the one that decides.

**What it does**
1. **Second reader of reviewer's messages,** next to the word rules. It must pick one of the catalog codes. If the two disagree, a person decides. On the Data Pack they agree on 49/49.
2. **Live reading of new applications.** A message added on screen or by upload is read straight away, in any language or script (Hindi, Tamil and so on). The reason is only proposed, and a person confirms it.
3. **"Ask the AI model to explain"** on any case waiting for a person. It gives a short, plain explanation of the note and which code fits. It is for the onboarding team, never for the merchant.

**Cost:**
- Each message is paid for once, because answers are saved in `llm_answers.json`.
- One call costs about $0.01 (₹1). The first run on the Data Pack cost under 1 US dollar.
- Set a monthly spend limit on the Anthropic console.

**Turning it on:**
- **Locally:** run `export ANTHROPIC_API_KEY=...` before `streamlit run app.py`.
- **On Streamlit Cloud:** open App settings → Secrets and add `ANTHROPIC_API_KEY = "sk-ant-..."`.
- Never put the key in a file you commit. `.streamlit/secrets.toml` is ignored by git.
- Without a key, the app still works on the saved answers and the word rules.

## Files

| File | What it does |
|---|---|
| `app.py` | the Streamlit app |
| `config.yaml` | the limits (assumptions) |
| `activateiq/classify.py` | reading reviewer messages (word rules + AI model) and AI explanations |
| `activateiq/rules.py` | reason, route, action, channel |
| `activateiq/score.py` | priority |
| `activateiq/messages.py`, `templates.json` | nudges and safety check |
| `activateiq/pipeline.py` | runs every step, summary, Excel output |
| `activateiq/bulk.py` | file upload checks |
| `activateiq/evaluate.py` | accuracy checks |
| `activateiq/compare.py` | one-time AI run |
| `gold_labels.csv` | 30 hand-labelled cases |
| `tests/` | automated checks |
| `outputs/` | results table (Excel and CSV) |

See [ARCHITECTURE.md](ARCHITECTURE.md) for how it works, and [CHANGELOG.md](CHANGELOG.md) for how it was built.
