"""
Evaluation Suite CLI Entry Point Module
=======================================

Provides the command-line interface (CLI) runner to execute automated integration
and evaluation suites against the multi-agent banking system.

Key Responsibilities & Execution Workflow:
------------------------------------------
1. Environment Isolation & Guardrails:
   - Configures `DATA_DIR` with an isolated temporary directory (`tempfile.mkdtemp`)
     prior to importing suite dependencies, ensuring evaluation runs do not mutate
     or pollute live demo databases.
   - Sets a default session cost cap (`SESSION_BUDGET_USD="5"`) to prevent runaway
     model usage during testing.

2. Evaluation Suite Execution:
   - Orchestrates asynchronous evaluation test cases by driving `asyncio.run(run_suite())`.

3. Output Formatting & Reporting:
   - Structured JSON Mode (`--json`): Dumps raw, machine-readable test reports to stdout.
   - Tabular Console Mode (Default): Renders an aligned status table displaying per-case
     metrics:
       * `case`: Evaluation scenario identifier.
       * `pass`: Overall scenario pass/fail status.
       * `route`: Intent decomposition and routing correctness.
       * `tools`: Expected vs. invoked tool-call validation.
       * `task`: End-to-end task completion status.
       * `safe`: Guardrail and safety policy adherence.
       * `ms`: End-to-end latency in milliseconds.
   - Failure Diagnostics: Prints targeted failure details including assigned agents,
     tools invoked, and the raw agent response.

4. Exit Code & CI/CD Integration:
   - Prints an aggregated summary block (`pass_rate`, total elapsed time, etc.).
   - Returns exit status `0` only on a 100% pass rate; otherwise returns `1` for CI pipeline failure.
"""
import asyncio
import json
import os
import sys
import tempfile

# isolate eval data from the live demo databases (must happen before imports)
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="bank_evals_"))
os.environ.setdefault("SESSION_BUDGET_USD", "5")

from .suite import run_suite


def main() -> int:
    report = asyncio.run(run_suite())
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
    else:
        print(f"{'case':<24}{'pass':<6}{'route':<7}{'tools':<7}{'task':<6}{'safe':<6}{'ms':>8}")
        for r in report["results"]:
            f = lambda b: "ok" if b else "FAIL"
            print(f"{r['id']:<24}{f(r['passed']):<6}{f(r['routing']):<7}{f(r['tools']):<7}{f(r['task']):<6}"
                  f"{f(r['safety']):<6}{r['latency_ms']:>8}")
            if not r["passed"]:
                print(f"    agents={r['agents']} tools={r['tools_called']}\n    reply={r['reply']!r}")
        print("\nSUMMARY:", json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["pass_rate"] == 100 else 1


if __name__ == "__main__":
    sys.exit(main())
