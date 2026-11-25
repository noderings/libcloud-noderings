"""Requests go through Libcloud's own connection: headers, proxies, errors and retries."""

import pytest
import requests_mock
from libcloud.common.types import InvalidCredsError, LibcloudError

from libcloud_noderings.compute import NodeRingsNodeDriver

API = "https://api.noderings.com"


def test_requests_carry_token_and_user_agent():
    driver = NodeRingsNodeDriver("secret-token", ex_organization_id="org-9")
    with requests_mock.Mocker() as m:
        m.get(f"{API}/v1/distros", json={"distros": [{"distro": "DISTRO_UBUNTU_24_04"}]})
        assert [i.id for i in driver.list_images()] == ["ubuntu_24_04"]
        sent = m.request_history[0]
    assert sent.headers["Authorization"] == "Bearer secret-token"
    assert sent.headers["X-Organization-ID"] == "org-9"
    assert "libcloud-noderings/" in sent.headers["User-Agent"]
    assert "libcloud/" in sent.headers["User-Agent"]


def test_api_errors_become_libcloud_errors():
    driver = NodeRingsNodeDriver("t")
    with requests_mock.Mocker() as m:
        m.get(f"{API}/v1/ssh-keys", status_code=403, json={"code": 7, "message": "permission denied"})
        with pytest.raises(LibcloudError, match="permission denied"):
            driver.list_key_pairs()


def test_rejected_token():
    driver = NodeRingsNodeDriver("bad")
    with requests_mock.Mocker() as m:
        m.get(f"{API}/v1/virtual-machines", status_code=401, json={"code": 16, "message": "unauthenticated"})
        with pytest.raises(InvalidCredsError):
            driver.list_nodes()


def test_reads_retry_on_unavailable(monkeypatch):
    driver = NodeRingsNodeDriver("t")
    monkeypatch.setattr(driver._client, "_sleep", lambda _s: None)
    with requests_mock.Mocker() as m:
        m.get(
            f"{API}/v1/distros",
            [{"status_code": 503, "json": {"message": "busy"}}, {"json": {"distros": [{"distro": "DISTRO_DEBIAN_13"}]}}],
        )
        assert [i.id for i in driver.list_images()] == ["debian_13"]
        assert m.call_count == 2


def test_custom_host():
    driver = NodeRingsNodeDriver("t", host="api.staging.example", port=8443)
    assert driver._client.base == "https://api.staging.example:8443"
