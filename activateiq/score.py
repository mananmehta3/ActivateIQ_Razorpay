"""Priority = log(1 + TPV) x P(recover) / effort.

P(recover) is a transparent heuristic, NOT a trained model: the data has no outcome labels.
Only fixable cases get a score; compliance, closed and clarify cases are never ranked.
"""
import math


def p_recover(row, cfg):
    p = cfg["priority"]
    base = p["evidence_weight"]["inferred" if row["evidence"] == "Read from rejection message" else "explicit"]
    decay = math.exp(-row["days_since_last_activity"] / p["decay_days"])
    attempts = p["attempt_penalty"] ** max(row["attempts"] - 1, 0)
    engaged = 1 + p["support_bonus"] if row["support_contacts"] > 0 else 1
    return min(base * decay * attempts * engaged, 1.0)


def score(row, catalog, cfg):
    if row["route"] != "Fixable":
        return None, None, None
    pr = p_recover(row, cfg)
    days_to_fix = int(catalog.loc[row["code"], "typical_days_to_fix"])
    effort = 1 + cfg["priority"]["effort_weight"] * (days_to_fix - 1)
    tpv = row["expected_monthly_tpv_inr_lakh"]
    return round(pr, 3), round(math.log1p(tpv) * pr / effort, 3), round(tpv * pr, 2)
