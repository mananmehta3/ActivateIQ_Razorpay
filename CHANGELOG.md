# Changelog

## 2026-11-08: fixes from the edge-case test files

Found with the test files in `activateiq-testdata/` (answer key column "Worth a look?").

- **Upload refuses impossible numbers.** Negative days since last activity, attempts, TPV or support contacts are refused (T041 had -3 days and got a call at rank 6). Attempts, days and support contacts must be whole numbers: 2.6 attempts is refused instead of being cut to 2 (T039). 2.0 is still read as 2.
- **Code and message disagree → a person decides first.** If the rejection message points to screening (R12) or a restricted category (R10) but the code says something else, the fix nudge is held and the case goes to Manual review (T013, T014). Before, only a note was added and the nudge still went out.
- **R10 is checked before closing.** An R10 code with a message that points to a different reason (T015: "Document blurred") goes to Manual review instead of being closed. A person can choose R10 on screen, and then it closes.
- **Duplicate merchants.** The same business name and phone under a new ID is flagged on upload, and the later copy goes to Manual review, so the merchant does not get two messages (T044 = T022).
- **Word rules:** "allowed nahi" / "nahi allowed" now read as R10 (T011).
- A reason chosen by a person now wins over the reason code too (needed to release the held cases).
- 8 new tests (31 in total): `python -m unittest -v`.
- **Upload page:** the line about columns is replaced by a table of the columns, whether each is required, and what values it can hold.
- **Reset:** the confirmation now also lists the reasons chosen by a person (it already cleared them) and says gold labels are kept.
