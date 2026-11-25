"""
The connection the NodeRings drivers share.

Requests go through Libcloud's own connection class, so proxies, timeouts and
``LIBCLOUD_DEBUG`` logging behave as they do for every other Libcloud driver.
Retries, idempotent orders and waits come from the NodeRings API client.
"""

import io
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit

from libcloud.common.base import ConnectionKey, Response
from libcloud.common.types import InvalidCredsError

from libcloud_noderings._api.client import TOKEN_ENV_VARS, NodeRingsClient, NodeRingsError
from libcloud_noderings._version import __version__

DEFAULT_HOST = "api.noderings.com"


class NodeRingsResponse(Response):
    """Hands every status to the API client, which decodes errors and retries."""

    def success(self):
        return True

    def parse_body(self):
        return self.body


class NodeRingsConnection(ConnectionKey):
    host = DEFAULT_HOST
    responseCls = NodeRingsResponse

    def add_default_headers(self, headers):
        headers["Authorization"] = f"Bearer {self.key}"
        headers["Accept"] = "application/json"
        return headers


class _RawResponse:
    """What the API client reads: a context manager with read()."""

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class NodeRingsDriverMixin:
    """Builds the API client on top of the driver's Libcloud connection."""

    connectionCls = NodeRingsConnection

    def _setup_noderings(self, key, ex_organization_id=None, ex_wait_timeout=900):
        token = key or next((os.environ[v] for v in TOKEN_ENV_VARS if os.environ.get(v)), None)
        if not token:
            raise InvalidCredsError("A NodeRings API token is required as the driver's key, or in NODERINGS_TOKEN")
        self.connection.user_agent_append(f"libcloud-noderings/{__version__}")
        self.ex_wait_timeout = ex_wait_timeout
        self._client = NodeRingsClient(
            token=token,
            api_url=f"{'https' if self.connection.secure else 'http'}://{self.connection.host}"
            + (f":{self.connection.port}" if self.connection.port not in (None, 443, 80) else ""),
            organization_id=ex_organization_id or os.environ.get("NODERINGS_ORGANIZATION_ID"),
            user_agent=None,
            opener=self._open,
        )
        return token

    def _open(self, url, method, data, headers, timeout):  # pylint: disable=unused-argument
        parts = urlsplit(url)
        action = parts.path + (f"?{parts.query}" if parts.query else "")
        send = {k: v for k, v in headers.items() if k.lower() not in ("authorization", "user-agent")}
        response = self.connection.request(action, data=data, headers=send, method=method, raw=False)
        body = response.body if isinstance(response.body, bytes) else (response.body or "").encode("utf-8")
        if response.status == 401:
            raise InvalidCredsError("NodeRings rejected the API token")
        if response.status >= 400:
            raise HTTPError(url, response.status, "error", {}, io.BytesIO(body))
        return _RawResponse(body)


def error_message(err):
    """A readable message for an API error."""
    return str(err) if isinstance(err, NodeRingsError) else f"{type(err).__name__}: {err}"
