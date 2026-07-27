from __future__ import annotations

import os
import sys
import threading

import certifi
import uvicorn


def configure_tls_trust() -> str:
    """Point OpenSSL-based clients at the CA bundle shipped with the sidecar."""
    configured = os.getenv("SSL_CERT_FILE")
    if configured:
        return configured
    ca_bundle = certifi.where()
    os.environ["SSL_CERT_FILE"] = ca_bundle
    return ca_bundle


def watch_parent(server: uvicorn.Server) -> None:
    """Stop Uvicorn when the Tauri parent closes or asks for shutdown."""
    try:
        for line in sys.stdin:
            if line.strip() == "shutdown":
                break
    finally:
        server.should_exit = True


def main() -> None:
    configure_tls_trust()
    from app.main import app

    host = os.getenv("STOCK_LAB_DESKTOP_API_HOST", "127.0.0.1")
    port = int(os.getenv("STOCK_LAB_DESKTOP_API_PORT", "8765"))
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, loop="asyncio", access_log=False))
    threading.Thread(target=watch_parent, args=(server,), name="tauri-parent-watch", daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
