"""The package version, from the installed metadata (set by setuptools-scm from the git tag)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("libcloud-noderings")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"
