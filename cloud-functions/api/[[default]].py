from __future__ import annotations

import os
from pathlib import Path
import sys

from fastapi import FastAPI, Request


FUNCTION_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = FUNCTION_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("STOCK_LAB_DATA_DIR", "/tmp/stock-opportunity-lab")

from app.main import app as stock_app  # noqa: E402


app = FastAPI(title="Stock Opportunity Lab EdgeOne Adapter", version="0.1.0")


@app.middleware("http")
async def restore_api_prefix(request: Request, call_next):
    path = request.scope.get("path", "")
    if not path.startswith("/api"):
        request.scope["path"] = f"/api{path if path.startswith('/') else f'/{path}'}"
    return await call_next(request)


app.mount("/", stock_app)
