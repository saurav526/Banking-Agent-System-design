"""
Pytest Test Suite Configuration & Environment Setup Module
==========================================================

Configures global runtime environment variables and test harnesses before any
application modules or settings are loaded.

Key Responsibilities & Configurations:
--------------------------------------
1. Storage Isolation:
   - Sets `DATA_DIR` to an isolated temporary directory (`tempfile.mkdtemp`),
     preventing test runs from accessing, modifying, or corrupting live SQLite
     databases and trace log files.

2. Ingress & Rate-Limit Relaxation:
   - Configures high burst and sustained rate thresholds (`RATE_LIMIT_PER_MINUTE="6000"`,
     `RATE_LIMIT_BURST="1000"`) to avoid synthetic 429 throttling during concurrent
     test runs and load simulations.

3. Offline Mock Backend Enforcement:
   - Defaults `LLM_DEFAULT_PROVIDER` to `"mock"`, guaranteeing zero external API
     dependencies, deterministic assertion behavior, and cost-free test executions.
"""
import os
import tempfile

# Isolated databases + generous limits for tests (must be set before importing the app)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="bank_tests_")
os.environ["RATE_LIMIT_PER_MINUTE"] = "6000"
os.environ["RATE_LIMIT_BURST"] = "1000"
os.environ["LLM_DEFAULT_PROVIDER"] = "mock"
