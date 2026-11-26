import ipaddress

import pytest

from leadradar.core.logging import redact
from leadradar.core.origins import (
    HostValidationError,
    normalize_host,
    resolve_request_origin,
    validate_origin,
)
from leadradar.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from leadradar.modules.netsafe.policy import BlockedDestination, check_hostname, is_ip_allowed, validate_url


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "172.17.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1",
                                "0.0.0.0", "224.0.0.1"  # noqa: S104, "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "198.18.0.1"])
def test_private_and_reserved_ips_blocked(ip):
    assert not is_ip_allowed(ipaddress.ip_address(ip))


def test_test_allowlist_is_inert_outside_test_env(monkeypatch):
    from leadradar.core.config import get_settings
    from leadradar.modules.netsafe import policy

    monkeypatch.setattr(get_settings(), "app_env", "production")
    with pytest.raises(BlockedDestination):
        policy.check_hostname("127.0.0.1")


def test_public_ip_allowed():
    assert is_ip_allowed(ipaddress.ip_address("93.184.215.14"))


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "gopher://x.com", "http://localhost/", "http://127.0.0.1/", "http://[::1]/",
    "http://169.254.169.254/latest/meta-data", "http://api:8000/", "http://postgres:5432/", "http://example.com:3000/",
    "http://user:pass@example.com/", "http://metadata.google.internal/", "http://foo.internal/", "http://0x7f000001/",
])
def test_ssrf_urls_blocked(url, monkeypatch):
    monkeypatch.delenv("LEADRADAR_TEST_ALLOW_HOSTS", raising=False)
    with pytest.raises(BlockedDestination):
        validate_url(url)


def test_valid_public_url_allowed():
    t = validate_url("https://example.com/path")
    assert t.host == "example.com" and t.port == 443


def test_single_label_internal_service_names_blocked(monkeypatch):
    monkeypatch.delenv("LEADRADAR_TEST_ALLOW_HOSTS", raising=False)
    for h in ("db", "leadradar-api", "dokploy"):
        with pytest.raises(BlockedDestination):
            check_hostname(h)


def test_host_validation_rejects_injection():
    for bad in ["evil.com/path", "a b", "evil.com@good.com", "x\r\nSet-Cookie: a", "exa_mple.com", ""]:
        with pytest.raises(HostValidationError):
            normalize_host(bad)
    assert normalize_host("App.Example.COM:8443") == "app.example.com:8443"


def test_forwarded_headers_only_trusted_from_proxies():
    h = {"host": "real.example.com", "x-forwarded-host": "evil.com", "x-forwarded-proto": "https"}
    untrusted = resolve_request_origin(h, "203.0.113.9", [])
    assert untrusted.host == "real.example.com" and untrusted.scheme == "http"
    trusted = resolve_request_origin(h, "172.18.0.2", [])
    assert trusted.host == "evil.com" and trusted.scheme == "https"
    with pytest.raises(HostValidationError):
        resolve_request_origin(h, "172.18.0.2", ["real.example.com"])


def test_origin_validation():
    assert validate_origin("https://Reports.Example.com/") == "https://reports.example.com"
    for bad in ["javascript:alert(1)", "https://x.com/path", "https://u:p@x.com", "ftp://x.com"]:
        with pytest.raises(HostValidationError):
            validate_origin(bad)


def test_password_hashing_argon2id():
    h = hash_password("a-very-long-password")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "a-very-long-password")
    assert not verify_password(h, "wrong")
    assert "password_too_short" in validate_password_strength("short")


def test_token_hash_is_keyed_and_stable():
    assert hash_token("abc") == hash_token("abc") and hash_token("abc") != hash_token("abd")
    assert len(hash_token("abc")) == 64


def test_secret_encryption_roundtrip():
    enc = encrypt_secret({"access_token": "s3cr3t"})
    assert "s3cr3t" not in enc
    assert "s3cr3t" in decrypt_secret(enc)


def test_log_redaction_of_public_tokens():
    assert "AbCdEfGh123" not in redact("GET /r/AbCdEfGh1234567 ok")
    assert "secret" not in redact("url?token=secret&x=1")
