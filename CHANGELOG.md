# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.1](https://github.com/noderings/libcloud-noderings/compare/v0.2.0...v0.2.1) (2026-11-27)


### Documentation

* link the official Go SDK in the README ([#7](https://github.com/noderings/libcloud-noderings/issues/7)) ([553cffc](https://github.com/noderings/libcloud-noderings/commit/553cffc3632188f5e6892d0512247a653eae3a2a))

## [0.2.0](https://github.com/noderings/libcloud-noderings/compare/v0.1.0...v0.2.0) (2026-11-26)


### Features

* choose the provider in create_node ([#4](https://github.com/noderings/libcloud-noderings/issues/4)) ([cad3ef5](https://github.com/noderings/libcloud-noderings/commit/cad3ef5bf121c0bed0aad195f21c3a1078485868))

## [Unreleased]

## [0.1.0] - 2026-11-25

### Added

- Compute driver `NodeRingsNodeDriver`: locations, sizes (plan codes), images (distros),
  `create_node` with SSH key or password auth and idempotent orders, power operations,
  `destroy_node`, key pairs, tags and firewall rulesets.
- DNS driver `NodeRingsDNSDriver`: zones with optional DNSSEC, and records mapped one value at
  a time onto NodeRings record sets.
- `libcloud_noderings.register()` registers both under the provider name `noderings`.
