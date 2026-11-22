import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from redrip import net  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows uses its own certificate store")


def test_prefers_valid_ssl_cert_file(tmp_path, monkeypatch):
    f = tmp_path / "ca.pem"
    f.write_text("x")
    monkeypatch.setenv("SSL_CERT_FILE", str(f))
    assert net.ca_source() == str(f)


def test_finds_distro_bundle_when_env_is_missing_or_wrong(tmp_path, monkeypatch):
    fedora = tmp_path / "tls-ca-bundle.pem"
    fedora.write_text("x")
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "does-not-exist.pem"))
    monkeypatch.setattr(net, "LINUX_CA_BUNDLES", [str(tmp_path / "missing.crt"), str(fedora)])
    assert net.ca_source() == str(fedora)


def test_falls_back_to_certifi(tmp_path, monkeypatch):
    certifi = pytest.importorskip("certifi")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(net, "LINUX_CA_BUNDLES", [str(tmp_path / "missing.crt")])
    assert net.ca_source() == certifi.where()
