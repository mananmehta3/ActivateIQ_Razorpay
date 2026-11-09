# Changelog: how ActivateIQ was built

This is the full record of how ActivateIQ went from a first idea to the current app. For each change it says what changed and why. Changes are in order, oldest first. Dates are in IST.

Problem chosen: **Problem 3, merchant onboarding and KYC drop-off recovery.**

---

## Phase 1: Understanding the problem (7 Nov)

**Read the brief and the Data Pack first, before designing anything.**
- The Data Pack has 100 applications. 25 are activated, which leaves **75 to act on**.
- 49 of the 75 have a rejection code. 22 have no code and no message: the merchant just stopped. Only 4 have a rejection message but no code (A3022, A3028, A3081, A3051).
- 67 of the 75 are fixable, with ₹933.9 lakh a month of expected TPV.

**First architecture (made with ChatGPT), then reviewed and changed.**
- The first draft used an AI model (LLM) at almost every step.
- The data showed that was not needed. 49 cases already have a code, so finding the reason is a lookup in the rejection catalog, and 22 are R13 by definition. Only 4 cases need anything to *read* a message.
- **Decision:** rules first, and an AI model only where rules cannot work. This keeps cost close to zero and gives the same answer every time.
- Messages are written **once** as templates (reason codes × 6 languages) and filled in for each merchant. Nothing is made up for each merchant, and re-runs cost nothing.

**Looked at other tools and at the industry.**
- **Jev / SnapJudgments** (a small model that picks one answer from a fixed list) could fit the 4 message-only cases. Kept as optional, because 4 cases did not justify a new tool.
- **Razorpay's current practice** (public sources): event-triggered drop-off messages (MoEngage, 29% onboarding uplift), instant website and policy-page checks, real-time PAN/CKYC checks, and paid assisted onboarding.
- **Positioning:** ActivateIQ does not rebuild reminders Razorpay already sends. It adds three things on top: finding the exact reason, a plain-language fix in the merchant's language, and deciding where the onboarding team should spend its time.

**What if there were 10,000 applications instead of 100?**
- The rules still run in seconds at no cost.
- An AI agent is not needed. The AI model is only needed for messages without a code, and each unique message is paid for once.

## Phase 2: Product definition and decision rules (8 Nov, morning)

**Wrote the product definition (ActivateIQ) and made it more specific.**
- Added the real numbers to the problem: 75 not activated, 67 fixable, ₹933.9 lakh a month stuck, 22 merchants who just stopped.
- Added the summary the brief asks for: how many are recoverable, the TPV at stake, and the top systemic causes.

**Fixed five problems in the first decision rules.**
1. **No code and no message = R13, not "unknown".** The brief says "some applications have no rejection at all: the merchant just stopped", and the catalog defines R13 as exactly that. Calling them unknown would have sent the biggest recovery group (22 merchants) to manual review.
2. **Check the message as well as the code.** A3051 has no code, but its message says "Business category not supported by policy", which is really R10. A check on the code alone would miss it.
3. **Keep fixable and recoverable separate.** The brief scores them separately. Recoverable means fixable **and** active in the last 30 days **and** fewer than 3 attempts.
4. **Priority multiplies instead of adding weights.** Adding TPV, days and attempts with percentage weights mixes units. The new formula is `log(1 + TPV) × recovery score ÷ effort`. The log stops a few very large merchants from filling the whole list.
5. **A fixed set of 7 actions,** with exactly one per application, so every decision can be checked.

**Principle: rules decide, AI explains, humans approve.**

## Phase 3: First build (8 Nov)

**v1: pipeline and output table.**
- Ran end to end on all 75 applications. The output table gives each one a reason, how the reason was found, fixable, recoverable, priority, action, channel, human check, a message in the merchant's language, and the safety check result.
- **Safety check:** every message is checked for WhatsApp without opt-in, wrong language, promises of approval or dates, screening words in compliance messages, and workarounds offered to restricted businesses. All 75 real messages passed, and 5 of 5 deliberately bad messages were caught.
- **Honest note on accuracy:** the word rules first scored 40/49 against the given codes. They were fixed to 49/49, but on the same rows, so that score is flattering. This is why hand labels were added later (Phase 7).
- **A bug found in testing:** with a stricter confidence setting, the inferred R10 (A3051) was still being closed. Fixed so that an uncertain reading always goes to a person first.

**v2: a working app, not just a table.**
- Added a dashboard with charts, a page to approve messages, and a page to add applications.
- Every message can be edited, and the safety check runs again on the edited text. Rejecting a message needs a reason.
- WhatsApp is only offered when the merchant opted in, and email otherwise. A person always presses send.
- Razorpay colours, no logo, because this is a student prototype.

**Plain wording everywhere.**
- Replaced high-level jargon with the words the brief and Excel use: stalled application, step reached, rejection code, rejection message, reviewer reason, standard fix, fixable, recoverable, nudge, route to compliance, systemic causes.

## Phase 4: Making it simple to use (8 Nov, midday)

- **Removed the Deploy button and all slogan lines** from the screen.
- **No scrolling to read a message.** The list is on the left, and the selected application opens on the right with its message and buttons.
- **Search by business name** as well as application ID, city, industry and business type. The Data Pack has no business name column, so names exist only for applications added on screen.
- **Merged "Approve nudges" and "Find an application" into one Applications page.** They did the same job. It has a full list, a search button and simple filters.
- **Bug fixed:** an old search saved in the browser crashed the new page. It now stores its search separately and ignores old values.
- **Search runs only when there is text to search.** Filters apply straight away, and each dropdown closes after a pick.
- **All 100 applications are shown,** including activated ones, with an Application status filter. "Status" was renamed "Nudge status" so the two are not confused.
- **Upload many applications at once** from Excel or CSV. Each row is checked, and rows with problems are listed by row number and not added.
- **Download results** as one Excel file, with every application plus the summary and systemic causes.
- **Reset** removes added applications and decisions and goes back to the original 100, so the demo can be run again.
- **Removed the settings sliders.** The brief does not ask for them, and they added questions to defend in the demo. The limits (30 days, 3 attempts, 10 calls) are in `config.yaml` and stated as assumptions.
- **Bug fixed:** the sidebar menu disappeared. The page style was hiding the arrow that opens it. The sidebar now always opens expanded.
- **Download and Reset moved** to small buttons at the bottom of the sidebar, out of the way of the page menu.
- **Bulk send.** Approve many simple messages at once after reading them, download a send list for the WhatsApp or email tool, and mark them as sent. Calls, closures, compliance and unclear cases stay one by one.
- **Removed the "[resume link]" placeholder.** A merchant would have seen a broken message. It now links to `https://dashboard.razorpay.com`, where merchants log in to finish.
- **Bug fixed:** old messages still showed the placeholder. The app kept a saved copy of the results. It now rebuilds them whenever the rules, messages or config change.
- `.gitignore` now leaves out local files: added applications, decisions, `.venv`.

## Phase 5: AI model as a second reader (8 Nov, afternoon)

- **The AI model (Claude) reads the messages that have no code,** next to the word rules. It must pick one of the catalog codes and cannot make up a reason.
- If both agree, the reason is kept. If they disagree, a person decides. **The AI model never decides alone.**
- **Cost:** each message is sent once, and the answers are saved in `llm_answers.json`. After one run (less than $1), the app works without a key and costs nothing.
- **Result:** the AI model and the word rules agree on **all 49** messages that have a code.
- **How accurate is it** page: added a "Word rules vs AI model" comparison.

## Phase 6: Outside review (8 Nov, afternoon)

A ChatGPT audit was checked against the brief and the Excel. Some points were right and some were not.

**Accepted:**
- **A person confirms every reason read from a message** before any message is written or any application closed. A3051 is now closed only after someone confirms it is R10. The confirmation can be undone.
- **Removed the "likely recovered ₹419 lakh" figure.** It was an estimate shown like a result. The dashboard now says expected TPV is not recovered revenue.
- **Each application shows why it ranks where it does,** and the score is called a rule of thumb, not a likelihood.
- **A page to label the 30 test cases** inside the app.
- **23 automated tests.**

**Rejected, with reasons:**
- *Treat the 22 blank cases as "unknown"*: the brief says these merchants "just stopped", which is R13.
- *TPV figures*: the audit mixed up fixable TPV (₹933.9 lakh) and total TPV (₹1,038.4 lakh for all 75).
- *No email without verified contact details*: every Razorpay signup needs an email, so email is stated as an assumption.
- *"The safety check passes everything"*: it is a real check that catches 5 of 5 bad messages.
- *A new priority formula*: the current one is explained and works. Its parts are now shown instead.

**Also added in this round:**
- **Call merchant** shows a short script for the call (who you are, the problem, the fix, no promises).
- **The follow-up plan** (Day 0, 3, 7, then stop) shows at the top of every application.
- **The dashboard** opens with a short "Where to start" note.

## Phase 7: Testing against my own answers (8 Nov, evening)

- **Hand-labelled 30 applications** without looking at the app's answers. The 30 cover every language, every code, the 4 message-only cases and all R10/R12 cases.
- **Results (latest labels):**
  - reason code: 20 of 20;
  - route: 20 of 30;
  - recoverable: 14 of 30;
  - action: 12 of 30.
- **Why route and recoverable disagree** (the full list is on the How accurate is it page):
  - **The 6 applications with no code and no message** were labelled "Manual review". The app treats them as R13, because the brief says these merchants "just stopped".
  - **The 3 message-only cases** (A3022, A3028, A3081) and A3051 were labelled "Manual review". The app holds them as "Confirm reason" until a person confirms.
  - **3 applications with 3 attempts** (A3015, A3020, A3072) were labelled recoverable. The app's rule is *fewer than* 3 attempts.
  - **R10 cases** were labelled "No" for recoverable. The app uses "Not applicable", because a restricted business is not fixable at all.
  - Most of these are differences in definition, not wrong answers. They show where the rules need to be stated clearly to the team.
- **Ran the AI model comparison** with a real key: 49 of 49 agree.

## Phase 8: Edge-case testing (8 Nov, evening)

Made test files with tricky rows, ran them through the app, and wrote down what it did:
- 48 rows that should load;
- 14 that should be refused;
- one file with a missing column.

**Fixed:**
- **Impossible numbers are refused on upload.**
  - Negative days, attempts, TPV or support contacts are refused. A merchant with -3 days was getting a call at rank 6.
  - Attempts, days and support contacts must be whole numbers. 2.6 attempts was being cut to 2 without a word.
- **When the code and the message disagree, a person decides first.** A message about screening (R12) or a restricted business (R10) under a different code used to get only a note, and the fix nudge still went out. Now nothing is sent until a person chooses the reason.
- **R10 is checked before closing.** An R10 code with a message about something else (for example "Document blurred") goes to a person instead of being closed, because closing cannot be undone.
- **The same merchant twice** (same business name and phone, new ID) is flagged on upload, and the later copy is held, so the merchant gets one message.
- **Word rules:** "allowed nahi" now reads as R10.
- **A reason chosen by a person** now wins over the reason code too.
- **31 automated tests** (8 new). Run them with `python -m unittest -v`.

**Seen, but left as they are:**
- **0 attempts is accepted.** It can mean "never submitted".
- **A code that does not fit the step** (a bank code at website review) is not checked. This is low risk.

## Phase 9: Final polish (8 Nov, night)

- **Upload page:** a table now lists every column, whether it is required, and what values it can hold.
- **Reset:** the confirmation now lists everything it clears: added applications, approve/reject/sent marks, and reasons chosen by a person. It also says the gold labels are kept.
- **Checked a doubt about bulk send:**
  - Bulk send shows 54, not the 42 on the priority list. That is correct.
  - Of the 42 on the priority list, 10 get a call, so they are not in bulk send. The other 32 get a fix nudge or a resume reminder.
  - The other 22 have gone cold and get one final nudge.
  - 32 + 22 = 54.
- **Added `ARCHITECTURE.md`,** a step-by-step description of how the app works.

## Phase 10: Shipping (8 Nov, night)

- **Code on GitHub:** [mananmehta3/ActivateIQ_Razorpay](https://github.com/mananmehta3/ActivateIQ_Razorpay). Local files (added applications, decisions, confirmed reasons) are left out by `.gitignore`.
- **Live app on Streamlit Community Cloud,** deployed from the GitHub repository. The saved AI model answers (`llm_answers.json`) are in the repository, so the live app needs no API key and costs nothing to run.
- **Animated explainer video** made for the pitch. It introduces the problem and how ActivateIQ works.

## Phase 11: Last UI changes (9 Nov)

- **Upload page:** the upload box is now at the top, with the file instructions (columns, required or not, allowed values) below it.
- **Clearer labels:** "Rejection code" and "Rejection message" are now "Reason code from the reviewer" and "Reviewer's message" on screen. Most of these applications are stalled, not rejected: only R10 and R12 cases have the status Rejected. The column names in the file stay `rejection_code` and `rejection_message`, to match the P3_Applications sheet.
- **README rewritten:** it now starts with the problem and why ActivateIQ was built, and the results, tests and limits match the current app.

## Phase 12: More AI, where it helps (9 Nov)

Reviewed whether the app used enough AI. The rules-first design stays, because it is cheap, gives the same answer every time and is easy to check. Two gaps were found where the AI model clearly helps:
- **The word rules cannot read Hindi or Tamil script.** In the edge-case test, T006 and T007 went to Manual review.
- **Nothing "AI" happened live in the app.** It only used saved answers.

**Added:**
- **Live AI reading.** A reviewer's message on a new application is read by Claude straight away, in any language or script. The reason is proposed, and a person confirms it. If the AI model fails, the case goes to a person.
- **"Ask the AI model to explain"** on every case waiting for a person. Claude gives up to 3 plain sentences on what the note means, which code fits and what to check. It is for the team only, and the person still decides.
- **The app shows when the AI model read a message,** and whether it agreed with the word rules.

**Cost:** about ₹1 per new message, paid once (answers are saved), with a spend limit on the Anthropic console. Expected total for the competition is under ₹100.

**Tests:** 4 new tests, 35 in total. The AI model is replaced by a stand-in in the tests, so they never call the API or cost money.

## Phase 13: Refusing unbelievable values (9 Nov)

Testing the form by hand showed it accepted values no real application would have: a city "4oiwejsn", 1,432 days inactive, 45 attempts, 34 support contacts, and a reviewer's message "gerdojf[paw".

Both the form and file upload now use the same checks:
- **Upper limits:** days since last activity up to 365, attempts up to 10, support contacts up to 20, and expected TPV up to ₹5,000 lakh. The Data Pack's own maximums are far lower (40 days, 4 attempts, 3 contacts, ₹59.9 lakh).
- **Industry** is chosen from the 12 industries in the P3_Applications sheet, or Other.
- **City** may contain only letters, spaces, . or -.
- **Business name** must have letters, and only common symbols (& ' . , ( ) / -).
- **Phone** must be a 10-digit Indian mobile number, and may start with +91.
- **Reviewer's message** must be a readable note of at least 2 words. Hindi and Tamil script count as letters.

**What cannot be checked:** a made-up name made only of letters, such as "jhfwo", looks like a real name to any rule. It is accepted, which is what a real onboarding form would do too.

**Tests:** 2 new tests, 37 in total.

## Phase 14: AI guardrails and restricted businesses (9 Nov)

**Guardrails on the AI model:**

What it already had:
- It can only pick a code from the catalog list.
- If it disagrees with the word rules, or fails, a person decides.
- It never sends anything or closes anything.
- A person confirms every reason it proposes.

What was added:
- **The reviewer's note is treated as data.** The model is told to ignore any instructions written inside the note, so a note cannot steer it.
- **Its explanation is checked before anyone sees it.** An answer that names a code not in the catalog, or is too long, is dropped and not saved, and the person decides from the note.
- **Explanations are for the onboarding team only,** never sent to the merchant.

**Restricted businesses (R10):**
- **The AI explanation now also looks at the business name, type and industry.** If they suggest drugs or other illegal substances, gambling, weapons or adult content, it says R10 may apply. It is told that a normal chemist or pharmacy is not restricted.
- **A rule check on every application:** business names or industries with words like ganja, cannabis, narcotic, casino, betting, satta, lottery, weapon or firearm are held for Manual review.
  - They are never closed automatically, because closing cannot be undone.
  - "Drug" alone is not on the list, because many real chemists are called "… Drug House".

**Tests:** 2 new tests, 39 in total.

## Phase 15: Catching misspelt and other-language warnings (9 Nov)

A hand test found a gap: an application with code R07 (website not live) and the message "Website sells prohibeted goods" (misspelt) got a normal fix nudge. The word rules looked for "prohibited" exactly, so they missed it.

**Fixed:**
- **The word rules now match word stems and more words for R10:** "prohib…", "restrict…", "illegal", "banned" and "not permitted". The Data Pack score stays 49/49.
- **The AI model is now a second reader on coded applications too.** When the word rules cannot read a message at all (a typo or another language), the AI model reads it. If it points to R10 or R12, the nudge is held for a person. The answer is saved, so each message is paid for once.
- **The restricted-word check now covers the reviewer's message too,** as well as the business name and industry.

**Tests:** 2 new tests, 41 in total.

