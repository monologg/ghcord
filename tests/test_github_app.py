import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from githubkit import GitHub

from app.clients.github_app import app_client, load_private_key


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
