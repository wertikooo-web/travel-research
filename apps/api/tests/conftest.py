import os
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

os.environ["TRIPMATCH_FAKE_LLM"] = "1"

_test_db_path = API_ROOT / "test_tripmatch.db"
if _test_db_path.exists():
    _test_db_path.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)
