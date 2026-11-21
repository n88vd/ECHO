import os

os.environ.setdefault("PROVIDERS", "fake")
os.environ.setdefault("ENV", "test")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_bytes():
    return lambda name: (FIXTURES / name).read_bytes()


def pytest_configure(config):
    from app.core.logging import setup_logging

    setup_logging("WARNING")
