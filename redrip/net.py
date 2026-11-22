"""HTTPS for Red-Rip's own downloads (tools, Jellyfin).

A bundled Python (PyInstaller, inside the AppImage) looks for trusted CA certificates
where they were on the *build* machine. Every Linux distro keeps them somewhere else, so
on many systems that lookup finds nothing and HTTPS fails with CERTIFICATE_VERIFY_FAILED.
This finds the distro's bundle instead, falling back to certifi's copy of Mozilla's list.
Windows uses the Windows certificate store and needs none of this.
"""
from __future__ import annotations

import os
import ssl
import sys
import urllib.error
import urllib.request
from functools import lru_cache

# Where Linux distros (and Flatpak runtimes) keep the system CA bundle
LINUX_CA_BUNDLES = [
    "/etc/ssl/certs/ca-certificates.crt",                 # Debian, Ubuntu, Arch, Gentoo, Flatpak runtimes
    "/etc/pki/tls/certs/ca-bundle.crt",                   # Fedora, RHEL, Bazzite
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora, RHEL
    "/etc/ssl/ca-bundle.pem",                             # openSUSE
    "/var/lib/ca-certificates/ca-bundle.pem",             # openSUSE
    "/etc/ssl/cert.pem",                                  # Alpine, Void
]


def ca_source() -> str | None:
    """The CA file to use, or None for the platform's own default (Windows)."""
    if sys.platform == "win32":
        return None
    env = os.environ.get("SSL_CERT_FILE")
    if env and os.path.isfile(env):
        return env
    for path in LINUX_CA_BUNDLES:
        if os.path.isfile(path):
            return path
    try:
        import certifi  # bundled fallback: Mozilla's list
        return certifi.where()
    except ImportError:
        return None


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=ca_source())


def urlopen(req, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


def _say(msg: str) -> None:
    if sys.stdout is not None:  # the windowed Windows .exe has no console
        print(msg)


def self_test() -> int:
    """`Red-Rip --self-test`: show where certificates come from and try an HTTPS request."""
    _say(f"CA certificates: {ca_source() or 'system default'}")
    try:
        req = urllib.request.Request("https://github.com/", method="HEAD", headers={"User-Agent": "Red-Rip"})
        with urlopen(req, timeout=20) as resp:
            _say(f"HTTPS to github.com: OK (HTTP {resp.status})")
        return 0
    except urllib.error.HTTPError as exc:
        # The server answered over a verified TLS connection: certificates work
        _say(f"HTTPS to github.com: OK (certificates verified; server answered HTTP {exc.code})")
        return 0
    except Exception as exc:
        _say(f"HTTPS to github.com: FAILED ({exc})")
        return 1
