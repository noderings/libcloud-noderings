# libcloud-noderings

[![CI](https://github.com/noderings/libcloud-noderings/actions/workflows/ci.yml/badge.svg)](https://github.com/noderings/libcloud-noderings/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/libcloud-noderings.svg)](https://pypi.org/project/libcloud-noderings/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

[Apache Libcloud](https://libcloud.apache.org) drivers for [NodeRings](https://noderings.com):
a **compute** driver for NodeRings virtual machines and a **DNS** driver for NodeRings DNS.
Use NodeRings from any Python code or tool built on Libcloud, with the same API as every
other Libcloud provider.

```python
import libcloud_noderings
from libcloud.compute.base import NodeAuthSSHKey
from libcloud.compute.providers import get_driver

libcloud_noderings.register()  # once, before get_driver("noderings")
driver = get_driver("noderings")("YOUR_TOKEN")

location = next(l for l in driver.list_locations() if l.name == "Ashburn")
size = next(s for s in driver.list_sizes(location) if s.id == "SC-GC-1C-1G-20")
image = next(i for i in driver.list_images() if i.id == "ubuntu_24_04")

node = driver.create_node(
    "web-1",
    size,
    image,
    location=location,
    auth=NodeAuthSSHKey(open("/home/me/.ssh/id_ed25519.pub").read()),
)
node, ips = driver.wait_until_running([node])[0]
print(ips)
```

## Requirements

* Python 3.10 or later and Apache Libcloud 3.8 or later
* A NodeRings service account token. Create one in the NodeRings console under
  **Organization → Access Control → Service accounts**.
* For `create_node`: a payment method or credit on the organization. Ordering a server is
  billed; hourly (usage) plans stop billing when `destroy_node` deletes it.

## Installation

```shell
pip install libcloud-noderings
```

## Credentials

Pass the token as the driver's key, or leave it out and set `NODERINGS_TOKEN`:

```python
driver = get_driver("noderings")()  # reads NODERINGS_TOKEN
```

`ex_organization_id=` (or `NODERINGS_ORGANIZATION_ID`) picks the organization for tokens that
reach more than one.

## Compute driver

| Libcloud | NodeRings |
| --- | --- |
| `list_locations()` | Cities where servers are sold. The ID is `Country/City`, such as `United States/Ashburn` |
| `list_sizes(location=None)` | Plans, by plan code (`SC-GC-1C-1G-20`). vCPU, memory and disk are read from the code |
| `list_images()` | Operating systems: `ubuntu_24_04`, `debian_13`, `rocky_9`... |
| `create_node(name, size, image, location, auth=...)` | Orders the cheapest matching offer and waits for an address |
| `list_nodes()`, `ex_get_node(id_or_hostname)` | Servers, with state, IPs and `extra` (plan, distro, tags, firewall, provider, city) |
| `reboot_node`, `start_node`, `stop_node` | Power operations; each waits until it is done |
| `destroy_node(node)` | Deletes the server |
| `list_key_pairs`, `get_key_pair`, `import_key_pair_from_string`, `delete_key_pair` | NodeRings SSH keys |
| `wait_until_running(...)` | Libcloud's own helper; works unchanged |

`create_node` options:

| Argument | Description |
| --- | --- |
| `auth` | `NodeAuthSSHKey(public_key)` (stored as a NodeRings key named `libcloud-<name>` unless the key is already stored) or `NodeAuthPassword(password)` |
| `ex_ssh_keys` | Names or IDs of NodeRings SSH keys to install as well |
| `ex_tags` | Tags on the server |
| `ex_firewall_ruleset` | Name or ID of a firewall ruleset to attach |
| `ex_billing_type` | `usage` (hourly, default), `subscription` or `free` |
| `ex_sort` | `price` (cheapest, default) or `rating` (best rated) |
| `ex_provider_id` | Only consider offers from this provider |
| `ex_plan_id`, `ex_region_id` | An exact plan and region, instead of size and location |
| `ex_wait` | Wait until the server is provisioned and has an address (default `True`) |

Orders carry an idempotency key, so a lost response is retried without ordering a second
server. Extra methods: `ex_set_tags(node, tags)`, `ex_attach_firewall(node, ruleset)` and
`ex_detach_firewall(node)`.

## DNS driver

```python
from libcloud.dns.providers import get_driver as get_dns_driver

dns = get_dns_driver("noderings")("YOUR_TOKEN")
zone = dns.create_zone("example.com", extra={"dnssec": True})
print(zone.extra["nameservers"])  # set these at your registrar

dns.create_record("www", zone, "A", "192.0.2.10", extra={"ttl": 300})
dns.create_record("www", zone, "A", "192.0.2.11")
dns.create_record(None, zone, "MX", "10 mx1.example.net.")
dns.create_record(None, zone, "TXT", "v=spf1 include:_spf.example.net -all")
```

NodeRings stores records as sets: one name and type with one or more values. Libcloud
treats each value as its own record, so:

* `create_record` adds a value to its set (adding a value that is already there changes
  nothing); `extra={"ttl": ...}` sets the TTL of the whole set.
* `update_record` replaces one value; a new name or type moves the value to that set.
* `delete_record` removes one value, and the set with its last value.
* `name=None` or `""` means the zone apex. Write hostnames with a trailing dot. TXT values
  are plain text; the driver quotes them and splits long ones.
* `delete_zone` deletes the zone with all its records. `ex_enable_dnssec(zone)` signs a zone
  and returns the DS record for your registrar.

All record types NodeRings supports are available: A, AAAA, CAA, CNAME, DS, MX, NS, PTR,
SRV, SSHFP, TLSA, TXT and more (`list_record_types()`).

## How it works

Requests go through Libcloud's own connection class, so proxies, timeouts and
`LIBCLOUD_DEBUG=/dev/stderr` logging behave as for any other Libcloud driver. On top of that
the driver retries rate-limited and temporary failures with backoff, never repeats an order
blindly, waits for operations to finish, and turns API errors into `LibcloudError` with the
API's message.

## Development

```shell
pip install -e ".[test]"
pytest                    # unit tests against an in-memory NodeRings API
ruff check . && ruff format --check .
```

The live tests call the real API and remove everything they create:

```shell
NODERINGS_TOKEN=... pytest tests/test_live.py                       # DNS and SSH keys, free
NODERINGS_TOKEN=... NODERINGS_TEST_BILLED=1 pytest tests/test_live.py   # adds a billed server
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Copyright NodeRings. Licensed under the [Apache License, Version 2.0](LICENSE).
