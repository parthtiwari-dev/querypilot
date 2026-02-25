import json
import sys
import time
from pathlib import Path

import requests


API_URL = "http://127.0.0.1:8001/query"
SCRIPT_DIR   = Path(__file__).parent          # backend/scripts/
BACKEND_DIR  = SCRIPT_DIR.parent              # backend/
RESULTS_FILE = BACKEND_DIR / "evaluation_results/day6_full_results.json"

# 10 queries: 3 easy, 4 medium, 2 hard, 1 adversarial
TEST_IDS = [
    "easy_001",
    "easy_005",
    "easy_010",
    "medium_003",
    "medium_007",
    "medium_010",
    "medium_009",
    "hard_001",
    "hard_005",
    "adv_004",
]



def load_baseline():
    if not RESULTS_FILE.exists():
        print(f"ERROR: Baseline results not found at {RESULTS_FILE}")
        sys.exit(1)

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    by_id = {}
    for r in data["results"]:
        rid = r.get("id")
        if rid:
            by_id[rid] = r
    return by_id


def normalize_sql(sql: str | None) -> str | None:
    if not sql:
        return None
    s = sql.strip().rstrip(";")
    # collapse whitespace
    return " ".join(s.split()).lower()


def run_single_test(test_id: str, baseline: dict) -> dict:
    base = baseline.get(test_id)
    if not base:
        print(f"[WARN] Baseline missing for id={test_id}, skipping")
        return {"id": test_id, "skipped": True}

    question = base["question"]

    payload = {
        "question": question,
        "schema_name": "ecommerce",
        "max_attempts": 3,
    }

    t0 = time.time()
    resp = requests.post(API_URL, json=payload)
    latency_ms = round((time.time() - t0) * 1000, 2)

    if resp.status_code != 200:
        print(f"[{test_id}] HTTP {resp.status_code}: {resp.text}")
        return {
            "id": test_id,
            "http_status": resp.status_code,
            "ok": False,
            "latency_ms": latency_ms,
        }

    data = resp.json()

    # Baseline fields
    success_base = bool(base.get("success"))
    attempts_base = int(base.get("attempts", 0))
    error_type_base = base.get("error_type")
    sql_base = normalize_sql(base.get("sql"))

    # API fields
    success_api = bool(data.get("success"))
    attempts_api = int(data.get("attempts", 0))
    error_type_api = data.get("error_type")
    sql_api = normalize_sql(data.get("sql"))
    tables_api = data.get("schema_tables_used") or []
    correction_applied_api = bool(data.get("correction_applied"))

    # Parity checks
    mismatches = []

    if success_api != success_base:
        mismatches.append(f"success api={success_api} base={success_base}")

    if attempts_api != attempts_base:
        mismatches.append(f"attempts api={attempts_api} base={attempts_base}")

    if (error_type_api or None) != (error_type_base or None):
        mismatches.append(f"error_type api={error_type_api} base={error_type_base}")

    if sql_api != sql_base:
        mismatches.append("sql mismatch")

    # Structural checks
    if success_api and not tables_api:
        mismatches.append("schema_tables_used empty on success")

    if correction_applied_api != (attempts_api > 1):
        mismatches.append(
            f"correction_applied inconsistent (corr={correction_applied_api}, attempts={attempts_api})"
        )

    ok = len(mismatches) == 0

    # Print per-query line
    tag = "OK" if ok else "MISMATCH"
    print(
        f"[{test_id}] {tag} | "
        f"succ api/base={success_api}/{success_base} | "
        f"att api/base={attempts_api}/{attempts_base} | "
        f"err api/base={error_type_api}/{error_type_base} | "
        f"corr={correction_applied_api} | "
        f"tables={len(tables_api)} | "
        f"lat={latency_ms:.0f}ms"
    )
    if mismatches:
        for m in mismatches:
            print(f"    → {m}")

    return {
        "id": test_id,
        "ok": ok,
        "latency_ms": latency_ms,
        "mismatches": mismatches,
    }


def main():
    print("=== QueryPilot API Parity Test (local) ===")
    baseline = load_baseline()

    results = []
    for tid in TEST_IDS:
        res = run_single_test(tid, baseline)
        if not res.get("skipped"):
            results.append(res)

    checked = [r for r in results if "ok" in r]
    if not checked:
        print("No tests executed.")
        sys.exit(1)

    ok_count = sum(1 for r in checked if r["ok"])
    total = len(checked)

    latencies = [r["latency_ms"] for r in checked]
    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[len(latencies_sorted) // 2]
    worst = max(latencies)

    print("\n=== Summary ===")
    print(f"Parity: {ok_count}/{total} queries matched baseline")
    print(f"Latency p50: {p50:.0f} ms")
    print(f"Latency worst: {worst:.0f} ms")

    # Exit code for CI / discipline
    sys.exit(0 if ok_count == total else 1)


if __name__ == "__main__":
    main()
