"""CLI: python -m banking_agent.evals  [--json]"""
import asyncio
import json
import os
import sys
import tempfile

# isolate eval data from the live demo databases (must happen before imports)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="bank_evals_"))
os.environ.setdefault("SESSION_BUDGET_USD", "5")

from .suite import run_suite  # noqa: E402


def main() -> int:
    report = asyncio.run(run_suite())
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
    else:
        print(f"{'case':<24}{'pass':<6}{'route':<7}{'tools':<7}{'task':<6}{'safe':<6}{'ms':>8}")
        for r in report["results"]:
            f = lambda b: "ok" if b else "FAIL"  # noqa: E731
            print(f"{r['id']:<24}{f(r['passed']):<6}{f(r['routing']):<7}{f(r['tools']):<7}{f(r['task']):<6}"
                  f"{f(r['safety']):<6}{r['latency_ms']:>8}")
            if not r["passed"]:
                print(f"    agents={r['agents']} tools={r['tools_called']}\n    reply={r['reply']!r}")
        print("\nSUMMARY:", json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["pass_rate"] == 100 else 1


if __name__ == "__main__":
    sys.exit(main())
