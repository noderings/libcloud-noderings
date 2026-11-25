import pytest
from libcloud.common.types import LibcloudError
from libcloud.compute.base import NodeAuthPassword, NodeAuthSSHKey
from libcloud.compute.providers import get_driver
from libcloud.compute.types import KeyPairDoesNotExistError, NodeState

from libcloud_noderings.compute import NodeRingsNodeDriver

PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey laptop"


def test_registered_as_a_provider():
    assert get_driver("noderings") is NodeRingsNodeDriver


def test_catalog(compute):
    loc = compute.list_locations()[0]
    assert (loc.id, loc.name, loc.country) == ("United States/Ashburn", "Ashburn", "United States")
    size = compute.list_sizes(loc)[0]
    assert (size.id, size.ram, size.disk, size.extra["vcpus"]) == ("SC-GC-1C-1G-20", 1024, 20, 1)
    images = {i.id: i.name for i in compute.list_images()}
    assert images == {"ubuntu_24_04": "Ubuntu 24.04", "debian_13": "Debian 13"}


def test_create_node_with_ssh_key(compute, fake):
    loc = compute.list_locations()[0]
    size = compute.list_sizes(loc)[0]
    image = [i for i in compute.list_images() if i.id == "debian_13"][0]
    node = compute.create_node("web-1", size, image, location=loc, auth=NodeAuthSSHKey(PUB), ex_tags=["web"])
    body = fake.created_vm_bodies[-1]
    key = list(fake.ssh_keys.values())[0]
    assert key["name"] == "libcloud-web-1"
    assert body["distro"] == "DISTRO_DEBIAN_13"
    assert body["sshKeyIds"] == [key["id"]]
    assert body["tags"] == ["web"]
    assert body["idempotencyKey"]
    assert node.name == "web-1" and node.state == NodeState.RUNNING and node.public_ips == ["192.0.2.50"]
    # The same key is reused, not imported twice.
    compute.create_node("web-2", size, image, location=loc, auth=NodeAuthSSHKey(PUB))
    assert len(fake.ssh_keys) == 1


def test_create_node_with_password_and_firewall(compute, fake):
    fake("https://api.noderings.com/v1/firewall/rulesets", "POST", b'{"ruleset":{"name":"web"}}', {}, 1)
    loc = compute.list_locations()[0]
    node = compute.create_node(
        "web-1", "SC-GC-1C-1G-20", "ubuntu_24_04", location=loc, auth=NodeAuthPassword("s3cret"), ex_firewall_ruleset="web"
    )
    assert fake.created_vm_bodies[-1]["password"] == "s3cret"
    assert fake.vms[node.id]["firewallRulesetId"] == list(fake.rulesets)[0]


def test_create_node_needs_auth_and_location(compute):
    with pytest.raises(LibcloudError, match="needs auth"):
        compute.create_node("web-1", "SC-GC-1C-1G-20", "ubuntu_24_04", location=compute.list_locations()[0])
    with pytest.raises(LibcloudError, match="needs a location"):
        compute.create_node("web-1", "SC-GC-1C-1G-20", "ubuntu_24_04", auth=NodeAuthPassword("x"))


def test_unknown_offer_is_explained(compute):
    from libcloud.compute.base import NodeLocation

    nowhere = NodeLocation(
        "United States/Nowhere", "Nowhere", "United States", compute, extra={"country": "United States", "city": "Nowhere"}
    )
    with pytest.raises(LibcloudError, match="No offer for plan code SC-GC-1C-1G-20 in Nowhere"):
        compute.create_node("web-1", "SC-GC-1C-1G-20", "ubuntu_24_04", location=nowhere, auth=NodeAuthPassword("x"))


def test_power_tags_and_destroy(compute, fake):
    loc = compute.list_locations()[0]
    node = compute.create_node("web-1", "SC-GC-1C-1G-20", "ubuntu_24_04", location=loc, auth=NodeAuthPassword("x"))
    assert compute.stop_node(node)
    assert compute.list_nodes()[0].state == NodeState.STOPPED
    assert compute.start_node(node) and compute.reboot_node(node)
    assert compute.list_nodes()[0].state == NodeState.RUNNING
    assert compute.ex_set_tags(node, ["a", "b"]) and fake.vms[node.id]["tags"] == ["a", "b"]
    assert compute.ex_get_node("web-1").id == node.id
    assert compute.destroy_node(node)
    assert compute.list_nodes() == []


def test_key_pairs(compute):
    key = compute.import_key_pair_from_string("laptop", PUB)
    assert key.name == "laptop" and key.extra["id"]
    assert [k.name for k in compute.list_key_pairs()] == ["laptop"]
    assert compute.get_key_pair("laptop").public_key == PUB
    assert compute.delete_key_pair(key)
    with pytest.raises(KeyPairDoesNotExistError):
        compute.get_key_pair("laptop")


def test_token_from_environment(monkeypatch):
    monkeypatch.setenv("NODERINGS_TOKEN", "env-token")
    driver = NodeRingsNodeDriver()
    assert driver._client.token == "env-token"


def test_missing_token(monkeypatch):
    for v in ("NODERINGS_TOKEN", "NODERINGS_API_TOKEN", "NR_API_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    from libcloud.common.types import InvalidCredsError

    with pytest.raises(InvalidCredsError):
        NodeRingsNodeDriver()
