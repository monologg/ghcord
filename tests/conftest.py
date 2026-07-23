import pytest


@pytest.fixture(autouse=True)
def ledger_db(tmp_path, monkeypatch):
    # Isolated ledger DB per test — keeps ghcord.db out of the working directory
    monkeypatch.setenv("GHCORD_DB", str(tmp_path / "ledger.db"))
    # App credentials must never leak in from the developer's shell — a test that
    # wants them sets them itself, so nothing can reach the real GitHub API
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
