import asyncio
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from githubkit import GitHub
from githubkit.exception import RequestFailed

from app.clients import github_app
from app.clients.github_app import InstallationMissing, app_client, load_private_key, verify_installed


@pytest.fixture
def rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def test_missing_app_id_raises(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_APP_ID"):
        app_client()


def test_missing_private_key_raises(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY_PATH", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_APP_PRIVATE_KEY"):
        app_client()


def test_inline_key_unescapes_newlines(monkeypatch, rsa_pem):
    # docker-compose env can't carry newlines, so single-line \n notation must be supported
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", rsa_pem.replace("\n", "\\n"))
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY_PATH", raising=False)
    assert load_private_key() == rsa_pem


def test_key_path_reads_file(monkeypatch, tmp_path, rsa_pem):
    pem_file = tmp_path / "app.pem"
    pem_file.write_text(rsa_pem)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(pem_file))
    assert load_private_key() == rsa_pem


def test_app_client_bootstraps_with_valid_key(monkeypatch, rsa_pem):
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", rsa_pem.replace("\n", "\\n"))
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY_PATH", raising=False)
    github = app_client()
    assert isinstance(github, GitHub)


# --- installation coverage check (guards /github subscribe) ---


def request_failed(status: int) -> RequestFailed:
    request = httpx.Request("GET", "https://api.github.com/")
    response = SimpleNamespace(
        raw_request=request,
        raw_response=httpx.Response(status, request=request),
        status_code=status,
    )
    return RequestFailed(response)


@pytest.fixture
def installation_lookup(monkeypatch):
    """Stub app_client() with canned installation lookups; returns the call log."""

    def install(*, repo: int = 404, org: int = 404, user: int = 404, slug: str | None = "ghcord") -> list[str]:
        calls: list[str] = []

        def lookup(kind: str, status: int):
            async def call(*_args):
                calls.append(kind)
                if status != 200:
                    raise request_failed(status)
                return SimpleNamespace(parsed_data=SimpleNamespace(id=1))

            return call

        async def authenticated():
            calls.append("app")
            if slug is None:
                raise request_failed(401)
            return SimpleNamespace(parsed_data=SimpleNamespace(slug=slug))

        apps = SimpleNamespace(
            async_get_repo_installation=lookup("repo", repo),
            async_get_org_installation=lookup("org", org),
            async_get_user_installation=lookup("user", user),
            async_get_authenticated=authenticated,
        )
        monkeypatch.setattr(github_app, "app_client", lambda: SimpleNamespace(rest=SimpleNamespace(apps=apps)))
        return calls

    return install


@pytest.fixture
def app_configured(monkeypatch, rsa_pem):
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", rsa_pem.replace("\n", "\\n"))
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY_PATH", raising=False)


def test_verify_installed_accepts_covered_repo(app_configured, installation_lookup):
    calls = installation_lookup(repo=200)
    asyncio.run(verify_installed("monologg/ghcord"))
    assert calls == ["repo"]  # one lookup, and no install-URL fetch on the happy path


def test_verify_installed_rejects_uncovered_repo(app_configured, installation_lookup):
    # the poppy-labs/dotfiles-ai case: subscribing here would store a subscription that can never fire
    installation_lookup(repo=404)
    with pytest.raises(InstallationMissing) as exc:
        asyncio.run(verify_installed("poppy-labs/dotfiles-ai"))
    assert "poppy-labs/dotfiles-ai" in str(exc.value)
    # masked + angle-bracketed, or Discord pastes GitHub's generic preview card under the error
    assert "[Install it to proceed](<https://github.com/apps/ghcord/installations/select_target>)" in str(exc.value)


def test_verify_installed_falls_back_to_user_installation(app_configured, installation_lookup):
    # a bare owner may be a user account, which is a 404 on the org endpoint
    calls = installation_lookup(org=404, user=200)
    asyncio.run(verify_installed("monologg"))
    assert calls == ["org", "user"]


def test_verify_installed_rejects_uncovered_owner(app_configured, installation_lookup):
    installation_lookup(org=404, user=404)
    with pytest.raises(InstallationMissing, match="poppy-labs"):
        asyncio.run(verify_installed("poppy-labs"))


def test_verify_installed_still_reports_without_install_url(app_configured, installation_lookup):
    # the slug lookup is best-effort — a failure must not swallow the real reason
    installation_lookup(repo=404, slug=None)
    with pytest.raises(InstallationMissing) as exc:
        asyncio.run(verify_installed("poppy-labs/dotfiles-ai"))
    assert "Install it" in str(exc.value)


def test_verify_installed_propagates_non_404(app_configured, installation_lookup):
    # a 500 says nothing about coverage — surfacing it beats reporting "not installed"
    installation_lookup(repo=500)
    with pytest.raises(RequestFailed):
        asyncio.run(verify_installed("monologg/ghcord"))


def test_verify_installed_skipped_when_app_unconfigured(monkeypatch):
    # relay-only deployment: no credentials to check with, so subscribe must not be blocked.
    # app_client() raises before any network call, so nothing can reach GitHub here.
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    asyncio.run(verify_installed("poppy-labs/dotfiles-ai"))
