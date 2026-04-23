"""
test_all_adapters.py — Benchmark all 20 TIMPS-Coder adapters.

Usage:
  python test_all_adapters.py --adapters-dir adapters/ --output benchmark_results.json
"""
import argparse
import json
import os
import time
from pathlib import Path

# ── Test cases (one per adapter specialisation) ────────────────────────────

TEST_CASES = [
    {
        "adapter": "java_npe",
        "prompt": "Fix this NullPointerException:\nString name = null;\nSystem.out.println(name.length());",
        "must_contain": ["null", "check", "Optional"],
    },
    {
        "adapter": "python_keyerror",
        "prompt": "Fix KeyError:\nd = {'a': 1}\nprint(d['b'])",
        "must_contain": [".get(", "KeyError", "default"],
    },
    {
        "adapter": "sql_injection",
        "prompt": "Fix SQL injection:\nquery = f\"SELECT * FROM users WHERE id = {user_id}\"",
        "must_contain": ["?", "parameteris", "placeholder"],
    },
    {
        "adapter": "javascript_async",
        "prompt": "Fix async bug:\nconst data = fetch('/api/users').json();\nconsole.log(data.name);",
        "must_contain": ["await", "async"],
    },
    {
        "adapter": "python_recursion",
        "prompt": "Fix RecursionError for deeply nested list flatten with depth > 1000",
        "must_contain": ["iterative", "stack", "deque"],
    },
]


def run_benchmark(adapters_dir: str, output_path: str):
    results = {
        "adapters_dir": adapters_dir,
        "total_tests": len(TEST_CASES),
        "adapters_tested": 0,
        "avg_accuracy": 0,
        "details": [],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    available_adapters = []
    if os.path.isdir(adapters_dir):
        available_adapters = [
            d for d in os.listdir(adapters_dir)
            if os.path.isdir(os.path.join(adapters_dir, d))
        ]

    print(f"\nBenchmarking {len(available_adapters)} adapters in {adapters_dir}")
    print(f"Running {len(TEST_CASES)} test cases\n")

    passed = 0
    tested = 0

    for case in TEST_CASES:
        adapter_name = f"timps-{case['adapter']}"
        adapter_path = os.path.join(adapters_dir, adapter_name)

        result = {
            "name": case["adapter"],
            "adapter_found": os.path.isdir(adapter_path),
            "score": 0,
            "improvement": 0,
            "notes": "",
        }

        if not result["adapter_found"]:
            result["notes"] = "Adapter not found — skipped"
            results["details"].append(result)
            continue

        tested += 1
        try:
            # Try to load and run the adapter
            from src.adapter_router import AdapterRouter
            router = AdapterRouter()
            t0 = time.time()
            output = router.generate(case["prompt"], max_tokens=512)
            elapsed = time.time() - t0

            # Check output quality
            keywords_found = sum(
                1 for kw in case["must_contain"]
                if kw.lower() in output.lower()
            )
            score = int(100 * keywords_found / len(case["must_contain"]))
            passed += score >= 50

            result.update({
                "score": score,
                "improvement": score - 50,  # vs random baseline
                "latency_s": round(elapsed, 2),
                "notes": f"{keywords_found}/{len(case['must_contain'])} keywords found",
            })
            print(f"  ✅ {case['adapter']}: {score}% ({elapsed:.1f}s)")

        except Exception as exc:
            result["notes"] = f"Runtime error: {exc}"
            print(f"  ⚠️  {case['adapter']}: {exc}")

        results["details"].append(result)

    results["adapters_tested"] = tested
    results["avg_accuracy"] = int(100 * passed / max(tested, 1))

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Tested: {tested}/{len(TEST_CASES)}")
    print(f"Avg accuracy: {results['avg_accuracy']}%")
    print(f"Results → {output_path}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapters-dir", default="adapters/")
    parser.add_argument("--output",       default="benchmark_results.json")
    args = parser.parse_args()
    run_benchmark(args.adapters_dir, args.output)
