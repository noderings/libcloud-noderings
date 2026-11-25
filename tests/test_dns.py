import pytest
from libcloud.common.types import LibcloudError
from libcloud.dns.providers import get_driver
from libcloud.dns.types import RecordDoesNotExistError, ZoneDoesNotExistError

from libcloud_noderings.dns import NodeRingsDNSDriver


def test_registered_as_a_provider():
    assert get_driver("noderings") is NodeRingsDNSDriver


def test_zones(dns, fake):
    zone = dns.create_zone("Example.com.", extra={"dnssec": True})
    assert zone.domain == "example.com"
    assert zone.extra["nameservers"] == ["ans1.nrings.io", "ans2.nrings.io"]
    assert fake.zones[zone.id]["dnssecMode"] == "DNSSEC_MODE_SIGNED_DS_PENDING"
    assert [z.domain for z in dns.list_zones()] == ["example.com"]
    assert dns.get_zone(zone.id).domain == "example.com"
    assert dns.delete_zone(zone)
    with pytest.raises(ZoneDoesNotExistError):
        dns.get_zone(zone.id)


def test_records_map_values_onto_sets(dns, fake):
    zone = dns.create_zone("example.com")
    a1 = dns.create_record("www", zone, "A", "192.0.2.10", extra={"ttl": 300})
    a2 = dns.create_record("www", zone, "A", "192.0.2.11")
    assert fake.records[zone.id][("www", "A")] == {"ttl": 300, "rdata": ["192.0.2.10", "192.0.2.11"]}
    assert {r.data for r in dns.list_records(zone)} == {"192.0.2.10", "192.0.2.11"}
    assert dns.get_record(zone.id, a1.id).data == "192.0.2.10"

    # Adding the same value again changes nothing.
    dns.create_record("www", zone, "A", "192.0.2.10")
    assert len(fake.records[zone.id][("www", "A")]["rdata"]) == 2

    updated = dns.update_record(a2, data="192.0.2.12")
    assert updated.data == "192.0.2.12"
    assert fake.records[zone.id][("www", "A")]["rdata"] == ["192.0.2.10", "192.0.2.12"]

    dns.delete_record(a1)
    assert fake.records[zone.id][("www", "A")]["rdata"] == ["192.0.2.12"]
    dns.delete_record(updated)
    assert ("www", "A") not in fake.records[zone.id]
    with pytest.raises(RecordDoesNotExistError):
        dns.get_record(zone.id, a1.id)


def test_apex_txt_and_mx(dns, fake):
    zone = dns.create_zone("example.com")
    txt = dns.create_record(None, zone, "TXT", 'v=spf1 -all "quoted"')
    assert fake.records[zone.id][("@", "TXT")]["rdata"] == ['"v=spf1 -all \\"quoted\\""']
    assert txt.name is None and txt.data == 'v=spf1 -all "quoted"'
    dns.create_record("", zone, "MX", "10 mx.example.net.")
    assert {r.type for r in dns.list_records(zone)} == {"TXT", "MX"}


def test_invalid_values_fail_before_the_api(dns, fake):
    zone = dns.create_zone("example.com")
    with pytest.raises(LibcloudError, match="not an IPv4 address"):
        dns.create_record("www", zone, "A", "2001:db8::1")
    assert ("www", "A") not in fake.records[zone.id]


def test_record_types(dns):
    assert {"A", "AAAA", "CNAME", "MX", "TXT", "SRV", "CAA"} <= set(dns.list_record_types())
