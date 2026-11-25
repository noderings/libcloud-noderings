# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Email **partners@noderings.com** with:

- a description of the issue and its impact
- steps to reproduce, or a proof of concept
- the package version (`pip show libcloud-noderings`) and Libcloud version

We acknowledge reports within three working days and keep you updated until the issue is fixed. Credit is given in the release notes unless you ask us not to.

## Supported versions

Security fixes are made for the latest minor release.

## Handling credentials

The drivers take the NodeRings service account token as their key, or read it from the `NODERINGS_TOKEN` environment variable. Load it from a secret store or the environment rather than writing it in code, and give the service account the narrowest NodeRings role that covers what your code manages. With `LIBCLOUD_DEBUG` set, Libcloud logs request headers, including the token, so use it only on a machine you trust and delete the log afterwards.
