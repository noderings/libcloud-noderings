# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-25

### Added

- Compute driver `NodeRingsNodeDriver`: locations, sizes (plan codes), images (distros),
  `create_node` with SSH key or password auth and idempotent orders, power operations,
  `destroy_node`, key pairs, tags and firewall rulesets.
- DNS driver `NodeRingsDNSDriver`: zones with optional DNSSEC, and records mapped one value at
  a time onto NodeRings record sets.
- `libcloud_noderings.register()` registers both under the provider name `noderings`.
