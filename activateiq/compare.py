"""Run once with a key to let the AI model read every rejection message, then save its answers.

    export ANTHROPIC_API_KEY=...        (Windows: set ANTHROPIC_API_KEY=...)
    python -m activateiq.compare

53 short messages, about one rupee per message or less. Answers are saved in llm_answers.json, so the
app and the "How accurate is it" page work afterwards without any key.
"""
import os

from .evaluate import rules_vs_ai, compare_summary
from .load import load_config

if __name__ == "__main__":
    cfg = load_config()
    key = "ANTHROPIC_API_KEY" if cfg["classifier"].get("llm_provider", "claude") == "claude" else "GEMINI_API_KEY"
    if not os.environ.get(key):
        raise SystemExit(f"Set {key} first, then run this again.")
    t = rules_vs_ai(cfg, allow_call=True)
    errors = t[t["ai_model"] == ""]
    if len(errors):
        print(f"{len(errors)} messages got no AI answer:", errors["ai_note"].unique())
    s = compare_summary(t)
    print(f"Code hidden, {s['cases']} cases: word rules {s['rules_right']} right, AI model {s['ai_right']} of {s['ai_answered']} right")
    print(f"No-code cases: AI answered {s['blank_answered']} of {s['blank_cases']}, agrees with word rules on {s['blank_agree']}")
    print(t[t["word_rules"] != t["ai_model"]][["application_id", "real_code", "word_rules", "ai_model", "rejection_message"]].to_string(index=False))
