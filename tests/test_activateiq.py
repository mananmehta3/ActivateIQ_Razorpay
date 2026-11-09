"""Automated checks for ActivateIQ. Run from the project folder:  python -m unittest -v

These check the rules against the Data Pack, not against hand labels (those are in gold_labels.csv).
"""
import os
import unittest

import pandas as pd

os.environ.pop("ANTHROPIC_API_KEY", None)  # tests never call the AI model

from activateiq import bulk  # noqa: E402
from activateiq.evaluate import guardrail_tests  # noqa: E402
from activateiq.load import load_config, load_data  # noqa: E402
from activateiq.messages import TEMPLATES, COMPLIANCE_WORDS, WORKAROUNDS, validate  # noqa: E402
from activateiq.pipeline import run, summary  # noqa: E402

CFG = load_config()
APPS, CATALOG = load_data(CFG)
DF, _ = run(CFG)
S = summary(DF)


def row(app_id, df=DF):
    return df[df["application_id"] == app_id].iloc[0]


def first(code):
    """First application in the data with this reason code given."""
    return DF[(DF["rejection_code"] == code)].iloc[0]


class Counts(unittest.TestCase):
    def test_every_non_activated_application_once(self):
        expected = set(APPS.loc[APPS["application_status"] != "Activated", "application_id"])
        self.assertEqual(len(DF), 75)
        self.assertEqual(set(DF["application_id"]), expected)
        self.assertTrue(DF["application_id"].is_unique)

    def test_tpv_totals_match_source(self):
        src = APPS[APPS["application_status"] != "Activated"]
        self.assertAlmostEqual(S["non_activated_tpv_lakh"], round(src["expected_monthly_tpv_inr_lakh"].sum(), 1))
        fx = DF[DF["fixable"] == "Yes"]
        self.assertAlmostEqual(S["fixable_tpv_lakh"], round(fx["expected_monthly_tpv_inr_lakh"].sum(), 1))
        self.assertEqual(S["coded_fixable"], 42)
        self.assertAlmostEqual(S["coded_fixable_tpv_lakh"], 518.3)

    def test_headline_counts(self):
        self.assertEqual((S["fixable"], S["closed_r10"], S["compliance_r12"], S["confirm_reason"]), (67, 4, 3, 4))


class Diagnosis(unittest.TestCase):
    def test_r01_given(self):
        r = first("R01")
        self.assertEqual((r.code, r.evidence, r.route), ("R01", "Reason code given", "Fixable"))
        self.assertNotEqual(r.nudge_draft, "")

    def test_r05_given(self):
        r = first("R05")
        self.assertEqual((r.code, r.route, r.fixable), ("R05", "Fixable", "Yes"))

    def test_r10_given_is_closed_without_workaround(self):
        for _, r in DF[DF["rejection_code"] == "R10"].iterrows():
            self.assertEqual(r.next_best_action, "Close application")
            self.assertTrue(pd.isna(r.priority_rank))
            self.assertFalse(any(__import__("re").search(p, r.nudge_draft.lower()) for p in WORKAROUNDS))

    def test_r12_given_goes_to_compliance_and_reveals_nothing(self):
        for _, r in DF[DF["rejection_code"] == "R12"].iterrows():
            self.assertEqual(r.next_best_action, "Route to compliance")
            self.assertTrue(pd.isna(r.priority_rank))
            self.assertFalse(any(__import__("re").search(p, r.nudge_draft.lower()) for p in COMPLIANCE_WORDS))

    def test_no_code_no_message_is_r13_with_neutral_reminder(self):
        blank = DF[DF["rejection_code"].isna() & DF["rejection_message"].isna()]
        self.assertEqual(len(blank), 22)
        self.assertTrue((blank["code"] == "R13").all())
        for _, r in blank.iterrows():  # the reminder names the step, not a made-up rejection
            self.assertNotIn("reject", r.nudge_draft.lower())

    def test_message_only_cases_wait_for_a_person(self):
        expected = {"A3022": "R05", "A3028": "R01", "A3081": "R09", "A3051": "R10"}
        for app_id, code in expected.items():
            r = row(app_id)
            self.assertEqual(r.code, code, app_id)              # proposed reason
            self.assertEqual(r.route, "Confirm reason", app_id)  # not closed, not in the recovery list
            self.assertEqual(r.nudge_draft, "", app_id)          # no message before confirmation
            self.assertTrue(pd.isna(r.priority_rank), app_id)

    def test_a3051_is_not_closed_before_confirmation(self):
        self.assertNotEqual(row("A3051").next_best_action, "Close application")

    def test_confirmed_reason_unlocks_message(self):
        df, _ = run(CFG, confirmed={"A3022": "R05", "A3051": "R10"})
        self.assertEqual(row("A3022", df).route, "Fixable")
        self.assertNotEqual(row("A3022", df).nudge_draft, "")
        self.assertEqual(row("A3051", df).next_best_action, "Close application")

    def test_person_can_pick_a_different_reason(self):
        df, _ = run(CFG, confirmed={"A3028": "R03"})
        self.assertEqual(row("A3028", df).code, "R03")


class Priority(unittest.TestCase):
    def test_ranks_are_1_to_n_without_gaps(self):
        ranks = DF["priority_rank"].dropna().astype(int).sort_values().tolist()
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))

    def test_only_recoverable_cases_are_ranked(self):
        ranked = DF[DF["priority_rank"].notna()]
        self.assertTrue((ranked["recoverable"] == True).all())  # noqa: E712
        self.assertEqual(len(ranked), S["recoverable"])

    def test_rank_follows_score(self):
        ranked = DF[DF["priority_rank"].notna()].sort_values("priority_rank")
        self.assertTrue(ranked["priority_score"].is_monotonic_decreasing)

    def test_top_n_get_a_call(self):
        top = DF[DF["priority_rank"] <= CFG["actions"]["ops_call_capacity"]]
        self.assertTrue((top["next_best_action"] == "Call merchant").all())


class Messages(unittest.TestCase):
    def test_six_languages(self):
        self.assertEqual(set(TEMPLATES), {"English", "Hindi", "Hinglish", "Tamil", "Kannada", "Marathi"})

    def test_whatsapp_only_with_opt_in(self):
        for _, r in DF[DF["channel"] == "WhatsApp"].iterrows():
            self.assertEqual(r.whatsapp_opted_in, "Yes")

    def test_not_opted_in_gets_email(self):
        r = DF[(DF["whatsapp_opted_in"] == "No") & (DF["nudge_draft"] != "")].iloc[0]
        self.assertEqual(r.channel, "Email")

    def test_check_blocks_whatsapp_without_opt_in(self):
        r = {"next_best_action": "Send fix nudge", "preferred_language": "English", "whatsapp_opted_in": "No",
             "channel": "WhatsApp"}
        self.assertTrue(any("opted in" in i for i in validate(r, "Please upload your PAN again.")))

    def test_check_passes_a_clean_message(self):
        r = {"next_best_action": "Send fix nudge", "preferred_language": "English", "whatsapp_opted_in": "Yes",
             "channel": "WhatsApp"}
        self.assertEqual(validate(r, "Please upload a clear copy of your PAN card."), [])

    def test_every_real_draft_passes_and_planted_bad_ones_are_caught(self):
        fails, total, caught = guardrail_tests(DF)
        self.assertEqual(fails, 0)
        self.assertTrue((caught["issues"] != "").all())


class BulkUpload(unittest.TestCase):
    def test_good_and_bad_rows(self):
        t = bulk.template()
        bad = t.iloc[[0]].copy()
        bad["preferred_language"] = "French"
        good, problems = bulk.check(pd.concat([t, bad], ignore_index=True), {"A3001"}, set(CATALOG.index), 1)
        self.assertEqual(len(good), 2)
        self.assertEqual(len(problems), 1)
        self.assertIn("Row 4", problems[0])


def _app(app_id, **kw):
    """One added application; the defaults make a plain fixable R01 case."""
    base = {"application_id": app_id, "business_name": f"Shop {app_id}", "business_type": "Proprietorship",
            "industry": "Retail", "city": "Pune", "preferred_language": "English", "expected_monthly_tpv_inr_lakh": 10.0,
            "whatsapp_opted_in": "Yes", "phone": None, "step_reached": "KYC docs", "application_status": "Stalled",
            "days_since_last_activity": 5, "attempts": 1, "support_contacts": 0, "rejection_code": "R01",
            "rejection_message": None}
    base.update(kw)
    return base


def run_with(*apps, confirmed=None):
    return run(CFG, extra_apps=pd.DataFrame(list(apps)), confirmed=confirmed)[0]


class EdgeCases(unittest.TestCase):
    def _upload(self, **kw):
        t = bulk.template().iloc[[0]].copy()
        for k, v in kw.items():
            t[k] = v
        return bulk.check(t.astype(str), set(), set(CATALOG.index), 1)

    def test_upload_refuses_negative_numbers(self):
        for col in ("days_since_last_activity", "attempts", "expected_monthly_tpv_inr_lakh", "support_contacts"):
            good, problems = self._upload(**{col: "-3"})
            self.assertEqual(len(good), 0, col)
            self.assertIn(f"{col} cannot be negative", problems[0])

    def test_upload_refuses_part_numbers_for_counts(self):
        good, problems = self._upload(attempts="2.6")
        self.assertEqual(len(good), 0)
        self.assertIn("attempts must be a whole number", problems[0])
        good, _ = self._upload(attempts="2.0", expected_monthly_tpv_inr_lakh="12.3456")
        self.assertEqual((good.iloc[0]["attempts"], good.iloc[0]["expected_monthly_tpv_inr_lakh"]), (2, 12.3456))

    def test_upload_refuses_unbelievable_values(self):
        good, problems = self._upload(business_name="jh#$", industry="uit08o", city="4oiwejsn",
                                      days_since_last_activity="1432", attempts="45", support_contacts="34",
                                      phone="12345", rejection_message="gerdojf[paw")
        self.assertEqual(len(good), 0)
        for word in ("business_name", "industry", "city", "days_since_last_activity cannot be more than 365",
                     "attempts cannot be more than 10", "support_contacts cannot be more than 20", "phone",
                     "rejection_message"):
            self.assertIn(word, problems[0])

    def test_upload_accepts_real_world_text(self):
        good, problems = self._upload(business_name="Raju's Chai, Snacks & More (राजू)", city="Delhi NCR",
                                      industry="grocery & food", phone="+91 98765 43210",
                                      rejection_message="पैन कार्ड पर नाम मेल नहीं खाता")
        self.assertEqual(problems, [])
        self.assertEqual(good.iloc[0]["industry"], "Grocery & Food")

    def test_screening_message_holds_the_fix_nudge(self):
        df = run_with(_app("T1", rejection_code="R05", rejection_message="Sanctions screening hit, under review"),
                      _app("T2", rejection_code="R01", rejection_message="Business category is restricted"))
        for app_id in ("T1", "T2"):
            r = row(app_id, df)
            self.assertEqual(r.next_best_action, "Manual review", app_id)
            self.assertEqual(r.nudge_draft, "", app_id)
            self.assertTrue(pd.isna(r.priority_rank), app_id)

    def test_r10_code_is_checked_against_the_message(self):
        df = run_with(_app("T3", rejection_code="R10", rejection_message="Document blurred, please re-upload"))
        self.assertEqual(row("T3", df).next_best_action, "Manual review")  # not closed
        df = run_with(_app("T3", rejection_code="R10", rejection_message="Document blurred, please re-upload"),
                      confirmed={"T3": "R10"})
        self.assertEqual(row("T3", df).next_best_action, "Close application")  # closes once a person decides

    def test_r10_code_with_matching_message_still_closes(self):
        df = run_with(_app("T4", rejection_code="R10", rejection_message="Business category not supported"))
        self.assertEqual(row("T4", df).next_best_action, "Close application")

    def test_duplicate_merchant_gets_one_message(self):
        a = _app("T5", business_name="Ravi Traders", phone="9800000001")
        b = _app("T6", business_name=" ravi  traders ", phone="+91 98000 00001")
        df = run_with(a, b)
        self.assertNotEqual(row("T5", df).nudge_draft, "")
        self.assertEqual(row("T6", df).next_best_action, "Manual review")
        self.assertIn("duplicate of T5", row("T6", df).human_check)
        warn = bulk.duplicate_warnings(pd.DataFrame([b]), pd.DataFrame([a]))
        self.assertEqual(len(warn), 1)

    def test_same_name_without_phone_is_not_a_duplicate(self):
        df = run_with(_app("T7", business_name="Ravi Traders"), _app("T8", business_name="Ravi Traders"))
        self.assertNotEqual(row("T8", df).next_best_action, "Manual review")

    def test_restricted_looking_business_is_held_for_a_person(self):
        df = run_with(_app("T9", business_name="Royal Casino Games"),
                      _app("T10", business_name="Sharma Drug House", industry="Health & Pharmacy"))
        r = row("T9", df)
        self.assertEqual(r.next_best_action, "Manual review")   # held, never closed automatically
        self.assertIn("restricted category", r.human_check)
        self.assertEqual(r.nudge_draft, "")
        self.assertNotEqual(row("T10", df).next_best_action, "Manual review")  # a chemist is not restricted

    def test_hinglish_allowed_nahi_reads_as_r10(self):
        from activateiq.classify import keyword_classify
        self.assertEqual(keyword_classify("Aapka business category allowed nahi hai")[0], "R10")


class LiveAI(unittest.TestCase):
    """The AI model is mocked: these tests never call the API or touch llm_answers.json."""

    def setUp(self):
        import tempfile
        from unittest import mock
        from activateiq import classify
        import shutil
        from pathlib import Path
        self.classify, self.tmp = classify, tempfile.TemporaryDirectory()
        cache = Path(self.tmp.name) / "c.json"
        if classify.CACHE.exists():  # start from the saved answers, so only new messages reach the (mocked) model
            shutil.copy(classify.CACHE, cache)
        self.patches = [mock.patch.object(classify, "CACHE", cache),
                        mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_ai_reads_a_message_the_word_rules_cannot(self):
        from unittest import mock
        with mock.patch.object(self.classify, "_ask_claude", return_value=("R01", 0.9)) as ask:
            df = run_with(_app("H1", rejection_code=None, rejection_message="पैन कार्ड पर नाम मेल नहीं खाता"))
            r = row("H1", df)
            self.assertEqual((r.code, r.route), ("R01", "Confirm reason"))  # a person still confirms
            self.assertIn("AI model", r.diagnosis_source)
            self.assertEqual(r.nudge_draft, "")
            run_with(_app("H1", rejection_code=None, rejection_message="पैन कार्ड पर नाम मेल नहीं खाता"))
            self.assertEqual(ask.call_count, 1)  # the saved answer is reused, not paid for twice

    def test_ai_error_sends_the_case_to_a_person(self):
        from unittest import mock
        with mock.patch.object(self.classify, "_ask_claude", side_effect=RuntimeError("down")):
            r = row("H2", run_with(_app("H2", rejection_code=None, rejection_message="பெயர் பொருந்தவில்லை")))
            self.assertEqual(r.next_best_action, "Manual review")

    def test_explanation_is_saved_and_reused(self):
        from unittest import mock
        with mock.patch.object(self.classify, "_ask_claude_text", return_value="It fits R05.") as ask:
            first = self.classify.explain_hold("R10", "Document blurred", "code and message disagree", CATALOG, CFG)
            again = self.classify.explain_hold("R10", "Document blurred", "code and message disagree", CATALOG, CFG,
                                               allow_call=False)
        self.assertEqual(first[0], "It fits R05.")
        self.assertEqual(again[0], "It fits R05.")
        self.assertEqual(ask.call_count, 1)

    def test_explanation_sees_the_business_and_bad_answers_are_dropped(self):
        from unittest import mock
        biz = {"business_name": "Green Leaf Herbals", "business_type": "Proprietorship", "industry": "Other"}
        with mock.patch.object(self.classify, "_ask_claude_text", return_value="This fits R99.") as ask:
            text, note = self.classify.explain_hold(None, "Products not allowed", "unclear", CATALOG, CFG, business=biz)
        self.assertIn("Green Leaf Herbals", ask.call_args[0][1])       # the model sees the business details
        self.assertIn("illegal substances", ask.call_args[0][0])       # and is told to look for restricted ones
        self.assertIsNone(text)                                        # an invented code is never shown
        self.assertIn("not in the catalog", note)
        with mock.patch.object(self.classify, "_ask_claude_text", return_value="x" * 1000):
            self.assertIsNone(self.classify.explain_hold(None, "Long", "unclear", CATALOG, CFG)[0])

    def test_no_key_means_no_call(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}), \
                mock.patch.object(self.classify, "_ask_claude_text") as ask:
            text, note = self.classify.explain_hold("R10", "Document blurred", "x", CATALOG, CFG)
        self.assertIsNone(text)
        self.assertIn("not set up", note)
        ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
