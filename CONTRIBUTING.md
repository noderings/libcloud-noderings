# Contributing

Thanks for helping improve libcloud-noderings.

1. Open an issue describing the bug or change before large pull requests.
2. Fork the repository and create a topic branch.
3. Run `pytest` and `ruff check . && ruff format --check .`; both must pass. The unit tests
   use the in-memory API in `tests/fakeapi.py`, so they need no token.
4. Add tests for new behaviour. For changes that reach the API, also run the live tests
   (`NODERINGS_TOKEN=... pytest tests/test_live.py`); they create and delete real objects.
5. Use [Conventional Commits](https://www.conventionalcommits.org/) and sign off each commit
   (`git commit -s`) to certify the [Developer Certificate of Origin](https://developercertificate.org/).

The files in `src/libcloud_noderings/_api/` are the NodeRings API client shared with the
NodeRings Salt extension. Please describe fixes to them in an issue so they are made in both
places.

The drivers follow Libcloud's driver conventions, so they can be offered to
[apache/libcloud](https://github.com/apache/libcloud) later. Contributions there are covered
by the Apache License.

Please report security problems privately as described in [SECURITY.md](SECURITY.md).
