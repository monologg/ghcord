import pytest


@pytest.fixture(autouse=True)
def ledger_db(tmp_path, monkeypatch):
    # Isolated ledger DB per test — keeps ghcord.db out of the working directory
    monkeypatch.setenv("GHCORD_DB", str(tmp_path / "ledger.db"))
