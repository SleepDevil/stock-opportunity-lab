from __future__ import annotations

import importlib.util
import io
from pathlib import Path


def load_desktop_sidecar():
    path = Path(__file__).resolve().parents[2] / "desktop" / "sidecar.py"
    spec = importlib.util.spec_from_file_location("stock_lab_desktop_sidecar", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sidecar_stops_when_parent_requests_shutdown(monkeypatch):
    sidecar = load_desktop_sidecar()
    server = type("Server", (), {"should_exit": False})()
    monkeypatch.setattr(sidecar.sys, "stdin", io.StringIO("shutdown\n"))

    sidecar.watch_parent(server)

    assert server.should_exit is True


def test_sidecar_stops_when_parent_pipe_closes(monkeypatch):
    sidecar = load_desktop_sidecar()
    server = type("Server", (), {"should_exit": False})()
    monkeypatch.setattr(sidecar.sys, "stdin", io.StringIO(""))

    sidecar.watch_parent(server)

    assert server.should_exit is True


def test_sidecar_configures_bundled_ca_bundle(monkeypatch):
    sidecar = load_desktop_sidecar()
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    ca_bundle = sidecar.configure_tls_trust()

    assert Path(ca_bundle).is_file()
    assert sidecar.os.environ["SSL_CERT_FILE"] == ca_bundle


def test_sidecar_preserves_explicit_ca_bundle(monkeypatch):
    sidecar = load_desktop_sidecar()
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/company-ca.pem")

    assert sidecar.configure_tls_trust() == "/tmp/company-ca.pem"
