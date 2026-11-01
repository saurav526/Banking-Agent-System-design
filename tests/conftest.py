import os
import tempfile

# Isolated databases + generous limits for tests (must be set before importing the app)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="bank_tests_")
os.environ["RATE_LIMIT_PER_MINUTE"] = "6000"
os.environ["RATE_LIMIT_BURST"] = "1000"
os.environ["LLM_DEFAULT_PROVIDER"] = "mock"
