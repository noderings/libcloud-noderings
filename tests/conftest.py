import pytest

import libcloud_noderings
from libcloud_noderings.compute import NodeRingsNodeDriver
from libcloud_noderings.dns import NodeRingsDNSDriver
from tests.fakeapi import FakeNodeRings

libcloud_noderings.register()


@pytest.fixture
def fake():
    return FakeNodeRings()


@pytest.fixture
def compute(fake):
    driver = NodeRingsNodeDriver("test-token")
    driver._client._open = fake  # every request goes to the in-memory API
    return driver


@pytest.fixture
def dns(fake):
    driver = NodeRingsDNSDriver("test-token")
    driver._client._open = fake
    return driver
