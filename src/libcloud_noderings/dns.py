"""
Apache Libcloud DNS driver for NodeRings DNS.

NodeRings stores records as sets: one name and type with one or more values.
Libcloud models every value as its own record, so this driver maps one
NodeRings value to one Libcloud :class:`Record`. ``create_record`` adds a
value to its set, ``update_record`` replaces one value, and ``delete_record``
removes one value (and the set with its last value).
"""

import base64
import json

from libcloud.common.types import LibcloudError
from libcloud.dns.base import DNSDriver, Record, Zone
from libcloud.dns.types import RecordDoesNotExistError, RecordType, ZoneDoesNotExistError

from libcloud_noderings import PROVIDER
from libcloud_noderings._api import dns as api_dns
from libcloud_noderings._api.client import NodeRingsError, is_not_found
from libcloud_noderings._api.compute import NodeRingsUsageError
from libcloud_noderings.common import NodeRingsDriverMixin, error_message

__all__ = ["NodeRingsDNSDriver"]

DEFAULT_TTL = 3600


def _record_id(name, rtype, value):
    raw = json.dumps([name, rtype, value], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_record_id(record_id):
    padded = record_id + "=" * (-len(record_id) % 4)
    try:
        name, rtype, value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, TypeError) as err:
        raise RecordDoesNotExistError(
            value=f"{record_id} is not a NodeRings record ID", driver=None, record_id=record_id
        ) from err
    return name, rtype, value


class NodeRingsDNSDriver(NodeRingsDriverMixin, DNSDriver):
    """
    NodeRings DNS driver.

    :param key: a NodeRings service account token (or set ``NODERINGS_TOKEN``)
    :param ex_organization_id: the organization to act in, for tokens that reach several
    """

    type = PROVIDER
    name = "NodeRings DNS"
    website = "https://noderings.com"

    RECORD_TYPE_MAP = {t: t for t in api_dns.RECORD_TYPES if hasattr(RecordType, t)}

    def __init__(self, key=None, secure=True, host=None, port=None, ex_organization_id=None, **kwargs):
        super().__init__(key or "-", secure=secure, host=host, port=port, **kwargs)
        self.connection.key = self._setup_noderings(key, ex_organization_id)

    # -- helpers ----------------------------------------------------------------

    def _call(self, what, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (NodeRingsError, NodeRingsUsageError, OSError) as err:
            raise LibcloudError(f"NodeRings: {what}: {error_message(err)}", driver=self) from err

    def _to_zone(self, zone):
        return Zone(
            id=zone["id"],
            domain=api_dns.normalize_zone_name(zone.get("name")),
            type="master",
            ttl=None,
            driver=self,
            extra={
                "state": (zone.get("state") or "").removeprefix("DNS_ZONE_STATE_").lower(),
                "dnssec_mode": (zone.get("dnssecMode") or "").removeprefix("DNSSEC_MODE_").lower(),
                "nameservers": list(zone.get("assignedNameservers") or []),
            },
        )

    def _rrsets(self, zone):
        recs = self._call("listing records", self._client.list_dns_records, zone.id)
        return [r for r in recs if not r.get("system")]

    def _rrset(self, zone, name, rtype):
        rel_filter = "" if name == "@" else name
        for rec in self._call("listing records", self._client.list_dns_records, zone.id, rel_filter, rtype):
            if (
                api_dns.relative_name(rec.get("name"), "") == name
                and (rec.get("type") or "").upper() == rtype
                and not rec.get("system")
            ):
                return rec
        return None

    def _records_of(self, zone, rec):
        rtype = (rec.get("type") or "").upper()
        name = api_dns.relative_name(rec.get("name"), "")
        out = []
        for raw in rec.get("rdata") or []:
            value = api_dns.from_api(rtype, raw)
            out.append(
                Record(
                    id=_record_id(name, rtype, value),
                    name=None if name == "@" else name,
                    type=rtype,
                    data=value,
                    zone=zone,
                    driver=self,
                    ttl=int(rec.get("ttl") or DEFAULT_TTL),
                    extra={"ttl": int(rec.get("ttl") or DEFAULT_TTL), "rrset_values": len(rec.get("rdata") or [])},
                )
            )
        return out

    def _write(self, zone, name, rtype, values, ttl):
        err = api_dns.validate_values(rtype, values)
        if err:
            raise LibcloudError(f"{name} {rtype}: {err}", driver=self)
        self._call(
            f"writing {name} {rtype}",
            self._client.upsert_dns_record,
            zone.id,
            {"name": name, "type": rtype, "ttl": int(ttl), "rdata": [api_dns.to_api(rtype, v) for v in values]},
        )

    @staticmethod
    def _rel(name, zone):
        return api_dns.relative_name(name or "", zone.domain)

    # -- zones ----------------------------------------------------------------------

    def list_record_types(self):
        return list(self.RECORD_TYPE_MAP)

    def list_zones(self):
        return [self._to_zone(z) for z in self._call("listing zones", self._client.list_dns_zones)]

    def get_zone(self, zone_id):
        try:
            zone = self._client.get_dns_zone(zone_id)
        except NodeRingsError as err:
            if is_not_found(err):
                raise ZoneDoesNotExistError(value=f"no zone {zone_id}", driver=self, zone_id=zone_id) from err
            raise LibcloudError(f"NodeRings: reading zone {zone_id}: {err}", driver=self) from err
        if not zone:
            raise ZoneDoesNotExistError(value=f"no zone {zone_id}", driver=self, zone_id=zone_id)
        return self._to_zone(zone)

    def create_zone(self, domain, type="master", ttl=None, extra=None):  # pylint: disable=redefined-builtin
        """Create a zone. ``extra={"dnssec": True}`` also signs it with DNSSEC."""
        if type != "master":
            raise LibcloudError("NodeRings hosts master zones only", driver=self)
        created = self._call(f"creating zone {domain}", self._client.create_dns_zone, api_dns.normalize_zone_name(domain))
        if (extra or {}).get("dnssec"):
            self._call("enabling DNSSEC", self._client.enable_dnssec, created["id"])
        # The create response omits the assigned nameservers; read the zone back.
        return self.get_zone(created["id"])

    def delete_zone(self, zone):
        """Delete a zone with all its records."""

        def delete():
            try:
                self._client.delete_dns_zone(zone.id, force=True)
            except NodeRingsError as err:
                if not is_not_found(err):
                    raise
            return True

        return self._call(f"deleting zone {zone.domain}", delete)

    def ex_enable_dnssec(self, zone):
        """Sign the zone with DNSSEC and return the DS record to publish at the registrar."""
        self._call("enabling DNSSEC", self._client.enable_dnssec, zone.id)
        return self._call("reading DNSSEC", self._client.get_dnssec, zone.id).get("ds")

    # -- records ----------------------------------------------------------------------

    def list_records(self, zone):
        out = []
        for rec in self._rrsets(zone):
            out.extend(self._records_of(zone, rec))
        return out

    def get_record(self, zone_id, record_id):
        zone = self.get_zone(zone_id)
        name, rtype, value = _parse_record_id(record_id)
        rec = self._rrset(zone, name, rtype)
        for record in self._records_of(zone, rec) if rec else []:
            if record.id == record_id or api_dns.canonical(rtype, record.data) == api_dns.canonical(rtype, value):
                return record
        raise RecordDoesNotExistError(value=f"no record {name} {rtype} {value}", driver=self, record_id=record_id)

    def create_record(self, name, zone, type, data, extra=None):  # pylint: disable=redefined-builtin
        """
        Add one value. ``name`` is relative to the zone (``None`` or ``""`` for the
        apex); ``extra={"ttl": 300}`` sets the TTL of the whole set.
        """
        rtype = type.upper()
        rel = self._rel(name, zone)
        rec = self._rrset(zone, rel, rtype)
        values = [api_dns.from_api(rtype, v) for v in (rec or {}).get("rdata") or []]
        ttl = (extra or {}).get("ttl") or (rec or {}).get("ttl") or DEFAULT_TTL
        if not any(api_dns.canonical(rtype, v) == api_dns.canonical(rtype, data) for v in values):
            values.append(str(data).strip())
        self._write(zone, rel, rtype, values, ttl)
        return self.get_record(zone.id, _record_id(rel, rtype, str(data).strip()))

    def update_record(self, record, name=None, type=None, data=None, extra=None):  # pylint: disable=redefined-builtin
        """Replace one value; a new name or type moves the value to that set."""
        old_name, old_type, old_value = _parse_record_id(record.id)
        new_name = self._rel(name, record.zone) if name is not None else old_name
        new_type = (type or old_type).upper()
        new_value = data if data is not None else old_value
        if (new_name, new_type) != (old_name, old_type):
            self.delete_record(record)
            return self.create_record(new_name, record.zone, new_type, new_value, extra or {"ttl": record.ttl})
        rec = self._rrset(record.zone, old_name, old_type)
        values = [api_dns.from_api(old_type, v) for v in (rec or {}).get("rdata") or []]
        values = [new_value if api_dns.canonical(old_type, v) == api_dns.canonical(old_type, old_value) else v for v in values]
        if not values:
            values = [new_value]
        ttl = (extra or {}).get("ttl") or (rec or {}).get("ttl") or DEFAULT_TTL
        self._write(record.zone, old_name, old_type, values, ttl)
        return self.get_record(record.zone.id, _record_id(old_name, old_type, str(new_value).strip()))

    def delete_record(self, record):
        name, rtype, value = _parse_record_id(record.id)
        rec = self._rrset(record.zone, name, rtype)
        if not rec:
            raise RecordDoesNotExistError(value=f"no record {name} {rtype}", driver=self, record_id=record.id)
        values = [api_dns.from_api(rtype, v) for v in rec.get("rdata") or []]
        keep = [v for v in values if api_dns.canonical(rtype, v) != api_dns.canonical(rtype, value)]
        if keep:
            self._write(record.zone, name, rtype, keep, rec.get("ttl") or DEFAULT_TTL)
        else:

            def delete():
                try:
                    self._client.delete_dns_record(record.zone.id, name, rtype)
                except NodeRingsError as err:
                    if not is_not_found(err):
                        raise
                return True

            self._call(f"deleting {name} {rtype}", delete)
        return True
