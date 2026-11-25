"""
Tests against the real NodeRings API. They skip without NODERINGS_TOKEN; the
server test also needs NODERINGS_TEST_BILLED=1 because it orders a billed VM.
Every object is named after a random run ID and removed at the end.
"""

import os
import subprocess
import uuid

import pytest
from libcloud.compute.base import NodeAuthSSHKey
from libcloud.compute.types import NodeState

from libcloud_noderings.compute import NodeRingsNodeDriver
from libcloud_noderings.dns import NodeRingsDNSDriver

TOKEN = next((os.environ[v] for v in ("NODERINGS_TOKEN", "NODERINGS_API_TOKEN", "NR_API_TOKEN") if os.environ.get(v)), None)
live = pytest.mark.skipif(not TOKEN, reason="needs NODERINGS_TOKEN (calls the real NodeRings API)")
billed = pytest.mark.skipif(
    not (TOKEN and os.environ.get("NODERINGS_TEST_BILLED") == "1"),
    reason="needs NODERINGS_TEST_BILLED=1 (orders a billed server)",
)
RUN = f"lcnr-{uuid.uuid4().hex[:6]}"
DOMAIN = os.environ.get("NODERINGS_TEST_DOMAIN", "example.com")


@live
def test_dns_lifecycle():
    dns = NodeRingsDNSDriver(TOKEN)
    zone = dns.create_zone(f"{RUN}.{DOMAIN}", extra={"dnssec": True})
    try:
        assert zone.extra["nameservers"], "the zone should list its nameservers"
        a1 = dns.create_record("www", zone, "A", "192.0.2.10", extra={"ttl": 300})
        dns.create_record("www", zone, "A", "192.0.2.11")
        dns.create_record(None, zone, "TXT", 'v=spf1 -all "quoted"')
        dns.create_record(None, zone, "MX", "10 mx1.example.net.")
        records = dns.list_records(zone)
        assert {(r.name, r.type, r.data) for r in records} >= {
            ("www", "A", "192.0.2.10"),
            ("www", "A", "192.0.2.11"),
            (None, "TXT", 'v=spf1 -all "quoted"'),
            (None, "MX", "10 mx1.example.net."),
        }
        assert all(r.ttl == 300 for r in records if r.name == "www")
        moved = dns.update_record(a1, data="192.0.2.12")
        dns.delete_record(moved)
        left = {r.data for r in dns.list_records(zone) if r.name == "www"}
        assert left == {"192.0.2.11"}
        assert dns.get_zone(zone.id).extra["dnssec_mode"] != "unsigned"
    finally:
        dns.delete_zone(zone)
    assert zone.domain not in {z.domain for z in dns.list_zones()}


@live
def test_key_pair_lifecycle(tmp_path):
    compute = NodeRingsNodeDriver(TOKEN)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "k")], check=True)
    key = compute.import_key_pair_from_string(f"{RUN}-key", (tmp_path / "k.pub").read_text())
    try:
        assert compute.get_key_pair(f"{RUN}-key").fingerprint
    finally:
        compute.delete_key_pair(key)
    assert f"{RUN}-key" not in {k.name for k in compute.list_key_pairs()}


@billed
def test_node_lifecycle(tmp_path):
    compute = NodeRingsNodeDriver(TOKEN)
    country = os.environ.get("NODERINGS_TEST_COUNTRY", "United States")
    city = os.environ.get("NODERINGS_TEST_CITY", "Ashburn")
    plan = os.environ.get("NODERINGS_TEST_PLAN_CODE", "SC-GC-1C-1G-20")
    location = next(loc for loc in compute.list_locations() if loc.extra == {"country": country, "city": city})
    size = next(s for s in compute.list_sizes(location) if s.id == plan)
    image = next(i for i in compute.list_images() if i.id == "ubuntu_24_04")
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "k")], check=True)
    pub = (tmp_path / "k.pub").read_text()

    node = compute.create_node(f"{RUN}-vm", size, image, location=location, auth=NodeAuthSSHKey(pub), ex_tags=["libcloud"])
    try:
        assert node.public_ips
        node, ips = compute.wait_until_running([node], wait_period=10, timeout=900)[0]
        assert node.state == NodeState.RUNNING
        ssh = [
            "ssh",
            "-i",
            str(tmp_path / "k"),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            f"root@{ips[0]}",
            "hostname",
        ]
        for _ in range(30):
            out = subprocess.run(ssh, capture_output=True, text=True, timeout=60)
            if out.returncode == 0:
                break
            subprocess.run(["sleep", "10"], check=True)
        assert out.returncode == 0, out.stderr
        assert compute.stop_node(node)
        assert compute.ex_get_node(node.id).state == NodeState.STOPPED
        assert compute.start_node(node)
        assert compute.reboot_node(node)
        assert compute.ex_set_tags(node, ["libcloud", "live"])
        assert compute.ex_get_node(node.id).extra["tags"] == ["libcloud", "live"]
    finally:
        compute.destroy_node(node)
        for key in compute.list_key_pairs():
            if key.name == f"libcloud-{RUN}-vm":
                compute.delete_key_pair(key)
    assert f"libcloud-{RUN}-vm" not in {k.name for k in compute.list_key_pairs()}
