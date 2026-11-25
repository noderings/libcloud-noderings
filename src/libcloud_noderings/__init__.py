"""
Apache Libcloud drivers for NodeRings: virtual machines (compute) and DNS.

Register them once, then use them like any built-in Libcloud provider::

    import libcloud_noderings
    from libcloud.compute.providers import get_driver

    libcloud_noderings.register()
    cls = get_driver("noderings")
    driver = cls("YOUR_TOKEN")
"""

import contextlib

from libcloud_noderings._version import __version__

PROVIDER = "noderings"

__all__ = ["PROVIDER", "__version__", "register"]


def register():
    """Register the NodeRings compute and DNS drivers under the name ``noderings``."""
    from libcloud.compute.providers import set_driver as set_compute_driver
    from libcloud.dns.providers import set_driver as set_dns_driver

    for setter, module, klass in (
        (set_compute_driver, "libcloud_noderings.compute", "NodeRingsNodeDriver"),
        (set_dns_driver, "libcloud_noderings.dns", "NodeRingsDNSDriver"),
    ):
        # set_driver refuses to register a name twice; a second register() is a no-op.
        with contextlib.suppress(AttributeError):
            setter(PROVIDER, module, klass)
