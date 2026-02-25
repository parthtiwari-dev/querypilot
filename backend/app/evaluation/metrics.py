# backend/app/evaluation/metrics.py
"""
Evaluation metrics for QueryPilot.
All functions accept list[dict] where each dict is one test result
with the field structure produced by run_full_eval.py.
"""

from typing import List, Dict, Any, Optional, Set
import re


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_adversarial(r: dict) -> bool:
    cat = (r.get("category") or "").lower()
    tid = (r.get("id") or r.get("test_id") or "").lower()
    return "adversarial" in cat or tid.startswith("adv")


def _get_error_type(r: dict) -> Optional[str]:
    et = r.get("error_type")
    if et:
        return et
    er = r.get("execution_result")
    if isinstance(er, dict):
        return er.get("error_type")
    return None


def _get_latency(r: dict) -> Optional[float]:
    ms = r.get("latency_ms")
    if ms is not None:
        return ms
    er = r.get("execution_result")
    if isinstance(er, dict):
        return er.get("execution_time_ms")
    return None


def _get_success(r: dict) -> bool:
    return bool(r.get("success") or r.get("actual_success"))


def _get_attempts(r: dict) -> int:
    return int(r.get("attempts") or 0)


def _get_tables(r: dict) -> List[str]:
    tables = r.get("schema_tables_used") or []
    if tables:
        return [t.lower() for t in tables]
    # Fallback: parse FROM/JOIN from sql field
    sql = (r.get("sql") or r.get("final_sql") or "").lower()
    return re.findall(r'(?:from|join)\s+([a-z_][a-z0-9_]*)', sql)


# ---------------------------------------------------------------------------
# 1. execution_success_rate
#    Adversarial tests are EXCLUDED from core success rate
# ---------------------------------------------------------------------------

def execution_success_rate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    core = [r for r in results if not _is_adversarial(r)]
    total = len(core)
    if total == 0:
        return {"rate": 0.0, "success": 0, "failed": 0, "total": 0, "adversarial_excluded": len(results)}

    success = sum(1 for r in core if _get_success(r))
    return {
        "rate": round(success / total, 4),
        "success": success,
        "failed": total - success,
        "total": total,
        "adversarial_excluded": len(results) - total
    }


# ---------------------------------------------------------------------------
# 2. first_vs_final_rate
# ---------------------------------------------------------------------------

def first_vs_final_rate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    core = [r for r in results if not _is_adversarial(r)]
    total = len(core)
    if total == 0:
        return {}

    # first_attempt_success is a bool field in result dict
    first_success = sum(
        1 for r in core
        if r.get("first_attempt_success") or (_get_success(r) and _get_attempts(r) == 1)
    )
    corrected = sum(
        1 for r in core
        if _get_success(r) and _get_attempts(r) > 1
    )
    failed = sum(1 for r in core if not _get_success(r))
    failed_initially = total - first_success
    correction_effectiveness = (
        round(corrected / failed_initially, 4) if failed_initially > 0 else 1.0
    )

    return {
        "first_attempt_rate": round(first_success / total, 4),
        "first_attempt_count": first_success,
        "corrected_count": corrected,
        "correction_effectiveness": correction_effectiveness,
        "final_failures": failed,
        "overall_success_rate": round((first_success + corrected) / total, 4)
    }


# ---------------------------------------------------------------------------
# 3. retry_distribution
# ---------------------------------------------------------------------------

def retry_distribution(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    core = [r for r in results if not _is_adversarial(r)]
    if not core:
        return {}

    dist: Dict[str, int] = {}
    total_attempts = 0
    for r in core:
        a = _get_attempts(r)
        total_attempts += a
        dist[str(a)] = dist.get(str(a), 0) + 1

    return {
        "distribution": dist,
        "avg_attempts": round(total_attempts / len(core), 4),
        "total_attempts": total_attempts
    }


# ---------------------------------------------------------------------------
# 4. hallucination_rate
#    Uses schema_tables_used field vs valid_tables set
# ---------------------------------------------------------------------------

def hallucination_rate(
    results: List[Dict[str, Any]],
    valid_tables: Set[str]
) -> Dict[str, Any]:
    valid_set = {t.lower() for t in valid_tables}
    hallucinated = []

    for r in results:
        tables_used = _get_tables(r)
        phantom = [t for t in tables_used if t not in valid_set]
        if phantom:
            hallucinated.append({
                "id": r.get("id") or r.get("test_id"),
                "phantom_tables": phantom,
                "tables_used": tables_used
            })

    total = len(results)
    return {
        "hallucination_rate": round(len(hallucinated) / total, 4) if total > 0 else 0.0,
        "hallucinated_count": len(hallucinated),
        "cases": hallucinated
    }


# ---------------------------------------------------------------------------
# 5. adversarial_results
#    "Success" for adversarial = system behaved correctly:
#      - success == False          (query was rejected / failed as expected)
#      - error_type is present     (failure was typed, not a crash)
#      - attempts >= 1             (system actually tried)
#      - schema_tables_used has no phantom tables (no hallucination)
# ---------------------------------------------------------------------------

def adversarial_results(results, valid_tables=None):
    adv = [r for r in results if _is_adversarial(r)]
    if not adv:
        return {"count": 0, "note": "No adversarial tests found"}

    valid_set = {t.lower() for t in valid_tables} if valid_tables else set()
    passed, failed = [], []

    for r in adv:
        # Get should_be_valid from the result (need to capture it in runner)
        should_be_valid = r.get("should_be_valid", True)
        actual_success = _get_success(r)
        tables = _get_tables(r)
        has_phantom = bool(valid_set and any(t not in valid_set for t in tables))

        # Correct behavior = outcome matches expectation + no phantom tables
        correctly_handled = (actual_success == should_be_valid) and not has_phantom

        if correctly_handled:
            passed.append(r.get("id") or r.get("test_id"))
        else:
            failed.append({
                "id": r.get("id") or r.get("test_id"),
                "should_be_valid": should_be_valid,
                "actual_success": actual_success,
                "error_type": _get_error_type(r),
                "expected_issue": r.get("expected_issue"),
            })

    total = len(adv)
    return {
        "total": total,
        "correctly_handled": len(passed),
        "incorrectly_handled": len(failed),
        "handling_rate": round(len(passed) / total, 4) if total > 0 else 0.0,
        "passed_ids": passed,
        "failed_details": failed
    }



# ---------------------------------------------------------------------------
# Full report — single call after eval loop
# ---------------------------------------------------------------------------

def full_report(
    results: List[Dict[str, Any]],
    valid_tables: Optional[Set[str]] = None
) -> Dict[str, Any]:
    report = {
        "execution": execution_success_rate(results),
        "first_vs_final": first_vs_final_rate(results),
        "retries": retry_distribution(results),
        "adversarial": adversarial_results(results, valid_tables),
    }
    if valid_tables:
        report["hallucination"] = hallucination_rate(results, valid_tables)
    return report
