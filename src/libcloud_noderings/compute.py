"""
Apache Libcloud compute driver for NodeRings virtual machines.

Sizes are NodeRings plan codes, locations are the cities where plans are sold,
and images are the operating systems a server can be ordered with.
``create_node`` orders the cheapest matching marketplace offer (or the best
rated one with ``ex_sort="rating"``) with an idempotency key, so a lost
response never orders a second server.
"""

import re

from libcloud.common.types import LibcloudError
from libcloud.compute.base import KeyPair, Node, NodeAuthPassword, NodeAuthSSHKey, NodeDriver, NodeImage, NodeLocation, NodeSize
from libcloud.compute.types import KeyPairDoesNotExistError, NodeState

from libcloud_noderings import PROVIDER
from libcloud_noderings._api import compute as api_compute
from libcloud_noderings._api.client import CODE_ALREADY_EXISTS, NodeRingsError, TimeoutError_, is_not_found, trim_enum
from libcloud_noderings._api.compute import NodeRingsUsageError
from libcloud_noderings.common import NodeRingsDriverMixin, error_message

__all__ = ["NodeRingsNodeDriver"]

# SC-GC-1C-1G-20: 1 vCPU, 1 GB memory, 20 GB disk.
_PLAN_RE = re.compile(r"-(\d+)C-(\d+)G-(\d+)$", re.I)

_DISTRO_NAMES = {
    "ubuntu": "Ubuntu",
    "debian": "Debian",
    "fedora": "Fedora",
    "centos": "CentOS Stream",
    "almalinux": "AlmaLinux",
    "rocky": "Rocky Linux",
}


class NodeRingsNodeDriver(NodeRingsDriverMixin, NodeDriver):
    """
    NodeRings compute driver.

    :param key: a NodeRings service account token (or set ``NODERINGS_TOKEN``)
    :param ex_organization_id: the organization to act in, for tokens that reach several
    :param ex_wait_timeout: seconds to wait for each operation (default 900)
    """

    type = PROVIDER
    name = "NodeRings"
    website = "https://noderings.com"
    features = {"create_node": ["ssh_key", "password"]}

    NODE_STATE_MAP = {
        "running": NodeState.RUNNING,
        "created": NodeState.RUNNING,
        "stopped": NodeState.STOPPED,
        "restarted": NodeState.RUNNING,
        "reinstalling": NodeState.REBOOTING,
    }

    def __init__(self, key=None, secure=True, host=None, port=None, ex_organization_id=None, ex_wait_timeout=900, **kwargs):
        super().__init__(key or "-", secure=secure, host=host, port=port, **kwargs)
        self.connection.key = self._setup_noderings(key, ex_organization_id, ex_wait_timeout)

    # -- helpers ----------------------------------------------------------------

    def _call(self, what, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (NodeRingsError, NodeRingsUsageError, TimeoutError_, OSError) as err:
            raise LibcloudError(f"NodeRings: {what}: {error_message(err)}", driver=self) from err

    def _to_node(self, vm):
        view = api_compute.vm_view(vm)
        state = self.NODE_STATE_MAP.get(view["power_state"], NodeState.UNKNOWN)
        if vm.get("crStatus") in ("CR_STATUS_PENDING", "CR_STATUS_PROCESSING") and not vm.get("ipv4"):
            state = NodeState.PENDING
        public = [ip for ip in (vm.get("ipv4"), vm.get("ipv6")) if ip]
        extra = {
            "plan_code": vm.get("planCode"),
            "plan_id": vm.get("planId"),
            "region_id": vm.get("regionId"),
            "distro": view["distro"],
            "power_state": view["power_state"],
            "provisioning_status": view["provisioning_status"],
            "billing_type": view["billing_type"],
            "tags": view["tags"],
            "firewall_ruleset_id": vm.get("firewallRulesetId") or None,
            "provider_name": vm.get("providerName"),
            "country": vm.get("regionCountry"),
            "city": vm.get("regionCity"),
        }
        return Node(
            id=vm["id"],
            name=vm.get("hostname"),
            state=state,
            public_ips=public,
            private_ips=[],
            driver=self,
            size=None,
            image=None,
            extra=extra,
        )

    @staticmethod
    def _location_id(country, city):
        return f"{country}/{city}"

    # -- catalog ------------------------------------------------------------------

    def list_locations(self):
        """Cities where virtual machines are sold. The ID is ``Country/City``."""
        regions = self._call("listing locations", self._client.list_marketplace_regions, "ASSET_TYPE_VM")
        out = []
        for r in regions:
            country, city = r.get("country") or "", r.get("city") or ""
            out.append(
                NodeLocation(
                    id=self._location_id(country, city),
                    name=city,
                    country=country,
                    driver=self,
                    extra={"country": country, "city": city},
                )
            )
        return out

    def list_sizes(self, location=None):
        """
        Plans that are sold, optionally only in one location. The size ID is the
        plan code. vCPU, memory (MB) and disk (GB) are read from the code.
        """
        country = city = None
        if location is not None:
            country, city = location.extra.get("country"), location.extra.get("city")
        plans = self._call(
            "listing sizes", self._client.list_available_plans, country=country, city=city, asset_type="ASSET_TYPE_VM"
        )
        out, seen = [], set()
        for plan in plans:
            code = plan.get("planCode")
            if not code or code in seen:
                continue
            seen.add(code)
            m = _PLAN_RE.search(code)
            vcpus, ram_gb, disk_gb = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (None, None, None)
            out.append(
                NodeSize(
                    id=code,
                    name=code,
                    ram=ram_gb * 1024 if ram_gb else None,
                    disk=disk_gb,
                    bandwidth=None,
                    price=None,
                    driver=self,
                    extra={
                        "vcpus": vcpus,
                        "billing_type": trim_enum(plan.get("billingType"), "BILLING_TYPE_"),
                        "compute_type": trim_enum(plan.get("computeType"), "COMPUTE_TYPE_"),
                        "compute_category": trim_enum(plan.get("computeCategory"), "COMPUTE_CATEGORY_"),
                    },
                )
            )
        return out

    def list_images(self, location=None, ex_only_active=True):  # pylint: disable=unused-argument
        """Operating systems a server can be ordered with, such as ``ubuntu_24_04``."""
        distros = self._call("listing images", self._client.list_distros)
        out = []
        for d in distros:
            slug = trim_enum(d.get("distro"), "DISTRO_")
            if not slug:
                continue
            family, _, ver = slug.partition("_")
            name = f"{_DISTRO_NAMES.get(family, family.title())} {ver.replace('_', '.')}".strip()
            out.append(NodeImage(id=slug, name=name, driver=self, extra={"distro": d.get("distro")}))
        return out

    # -- nodes ----------------------------------------------------------------------

    def list_nodes(self):
        return [self._to_node(vm) for vm in self._call("listing nodes", self._client.list_virtual_machines)]

    def ex_get_node(self, node_id):
        """The node with this ID or unique hostname, or ``None``."""
        vm = self._call("finding the node", api_compute.find_vm, self._client, node_id)
        return self._to_node(vm) if vm else None

    def create_node(
        self,
        name,
        size,
        image,
        location=None,
        auth=None,
        ex_ssh_keys=None,
        ex_tags=None,
        ex_firewall_ruleset=None,
        ex_billing_type="usage",
        ex_sort="price",
        ex_provider_id=None,
        ex_plan_id=None,
        ex_region_id=None,
        ex_wait=True,
    ):
        """
        Order a NodeRings virtual machine.

        :param name: hostname of the server
        :param size: a :class:`NodeSize` from ``list_sizes`` (or a plan code string)
        :param image: a :class:`NodeImage` from ``list_images`` (or a distro such as ``ubuntu_24_04``)
        :param location: a :class:`NodeLocation` from ``list_locations``; required unless
            ``ex_plan_id`` and ``ex_region_id`` are given
        :param auth: :class:`NodeAuthSSHKey` (stored as a NodeRings key if new) or
            :class:`NodeAuthPassword`
        :param ex_ssh_keys: names or IDs of NodeRings SSH keys to install
        :param ex_tags: tags on the server
        :param ex_firewall_ruleset: name or ID of a firewall ruleset to attach
        :param ex_billing_type: ``usage`` (hourly, default), ``subscription`` or ``free``
        :param ex_sort: ``price`` (cheapest, default) or ``rating`` (best rated)
        :param ex_provider_id: only consider offers from this provider
        :param ex_plan_id: exact plan ID, instead of size and location
        :param ex_region_id: exact region ID, with ``ex_plan_id``
        :param ex_wait: wait until the server is provisioned and has an address (default True)
        """
        client = self._client
        if ex_plan_id and ex_region_id:
            plan_id, region_id = ex_plan_id, ex_region_id
        else:
            if location is None:
                raise LibcloudError(
                    "create_node needs a location from list_locations(), or ex_plan_id and ex_region_id", driver=self
                )
            plan_code = size.id if isinstance(size, NodeSize) else str(size)
            plan_id, region_id, _ = self._call(
                "finding an offer",
                api_compute.choose_offer,
                client,
                plan_code,
                location.extra.get("country"),
                location.extra.get("city"),
                billing_type=ex_billing_type,
                provider_id=ex_provider_id,
                sort=ex_sort,
            )
        distro = image.id if isinstance(image, NodeImage) else str(image)

        key_ids = self._call("resolving SSH keys", api_compute.resolve_ssh_keys, client, ex_ssh_keys or [])
        password = None
        if isinstance(auth, NodeAuthSSHKey):
            key_ids.append(self._ensure_key(f"libcloud-{name}", auth.pubkey).extra["id"])
        elif isinstance(auth, NodeAuthPassword):
            password = auth.password
        if not key_ids and not password:
            raise LibcloudError("create_node needs auth (an SSH key or a password) or ex_ssh_keys", driver=self)

        ruleset_id = None
        if ex_firewall_ruleset:
            ruleset_id = self._call("resolving the firewall ruleset", api_compute.resolve_ruleset, client, ex_firewall_ruleset)

        vm = self._call(
            f"ordering {name}",
            api_compute.order_vm,
            client,
            name,
            plan_id,
            region_id,
            distro=distro,
            ssh_key_ids=key_ids,
            password=password,
            tags=ex_tags,
            wait=False,
            timeout=self.ex_wait_timeout,
        )
        if ex_wait or ruleset_id:
            vm = self._wait_address(vm["id"])
        if ruleset_id:
            vm = self._call(
                "attaching the firewall", api_compute.attach_firewall, client, vm["id"], ruleset_id, True, self.ex_wait_timeout
            )
        return self._to_node(vm)

    def _wait_address(self, vm_id):
        client = self._client

        def check():
            vm = client.get_virtual_machine(vm_id)
            if vm.get("crStatus") == "CR_STATUS_FAILED":
                raise NodeRingsUsageError(f"provisioning of {vm_id} failed; delete it and try another offer")
            return (vm.get("crStatus") == "CR_STATUS_APPLIED" and bool(vm.get("ipv4") or vm.get("ipv6"))), vm

        from libcloud_noderings._api.client import Waiter  # pylint: disable=import-outside-toplevel

        return self._call("waiting for the server", Waiter(self.ex_wait_timeout).wait, "the server to get an address", check)

    def _power(self, node, want):
        self._call(
            f"changing the power of {node.name}", api_compute.set_power, self._client, node.id, want, True, self.ex_wait_timeout
        )
        return True

    def reboot_node(self, node):
        return self._power(node, "restarted")

    def start_node(self, node):
        return self._power(node, "running")

    def stop_node(self, node):
        return self._power(node, "stopped")

    def destroy_node(self, node):
        def delete():
            try:
                self._client.delete_virtual_machine(node.id)
            except NodeRingsError as err:
                if not is_not_found(err):
                    raise
            return True

        from libcloud_noderings._api.client import Waiter  # pylint: disable=import-outside-toplevel

        return self._call(f"deleting {node.name}", Waiter(self.ex_wait_timeout).retry_busy, delete)

    def ex_set_tags(self, node, tags):
        """Replace the node's tags."""
        have = set(node.extra.get("tags") or [])
        want = set(tags or [])
        self._call(
            "updating tags",
            self._client.update_virtual_machine_tags,
            node.id,
            add=sorted(want - have),
            remove=sorted(have - want),
        )
        node.extra["tags"] = sorted(want)
        return True

    def ex_attach_firewall(self, node, ruleset):
        """Attach a firewall ruleset (name or ID) to the node."""
        ruleset_id = self._call("resolving the firewall ruleset", api_compute.resolve_ruleset, self._client, ruleset)
        self._call(
            "attaching the firewall", api_compute.attach_firewall, self._client, node.id, ruleset_id, True, self.ex_wait_timeout
        )
        return True

    def ex_detach_firewall(self, node):
        """Detach the node's firewall ruleset."""
        vm = self._call("reading the node", self._client.get_virtual_machine, node.id)
        current = vm.get("firewallRulesetId")
        if current:
            self._call(
                "detaching the firewall", api_compute.detach_firewall, self._client, node.id, current, True, self.ex_wait_timeout
            )
        return True

    # -- key pairs ----------------------------------------------------------------------

    def _to_key_pair(self, key):
        return KeyPair(
            name=key.get("name"),
            public_key=key.get("publicKey"),
            fingerprint=key.get("fingerprint"),
            driver=self,
            extra={"id": key.get("id"), "key_type": key.get("keyType")},
        )

    def list_key_pairs(self):
        return [self._to_key_pair(k) for k in self._call("listing SSH keys", self._client.list_ssh_keys)]

    def get_key_pair(self, name):
        for key in self.list_key_pairs():
            if key.name == name:
                return key
        raise KeyPairDoesNotExistError(name=name, driver=self)

    def import_key_pair_from_string(self, name, key_material):
        key = self._call("importing the SSH key", self._client.create_ssh_key, name, key_material.strip())
        return self._to_key_pair(key)

    def delete_key_pair(self, key_pair):
        key_id = key_pair.extra.get("id") or self.get_key_pair(key_pair.name).extra["id"]

        def delete():
            try:
                self._client.delete_ssh_key(key_id)
            except NodeRingsError as err:
                if not is_not_found(err):
                    raise
            return True

        return self._call("deleting the SSH key", delete)

    def _ensure_key(self, name, public_key):
        """The stored key with this public key, imported under ``name`` if it is new."""
        material = " ".join(public_key.split()[:2])
        for key in self.list_key_pairs():
            if " ".join((key.public_key or "").split()[:2]) == material:
                return key
        try:
            return self.import_key_pair_from_string(name, public_key)
        except LibcloudError as err:
            cause = err.__cause__
            if isinstance(cause, NodeRingsError) and cause.code == CODE_ALREADY_EXISTS:
                return self.get_key_pair(name)
            raise
