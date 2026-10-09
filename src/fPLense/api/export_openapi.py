"""Write the OpenAPI schema to ``web/openapi.json`` without starting a server.

    python -m fPLense.api.export_openapi

P7 generates the frontend's TypeScript types from this file (``openapi-typescript``); a test
fails if it drifts from the live schema.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fPLense import config
from fPLense.api.main import create_app


def export(path: Path = config.WEB_OPENAPI_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    out = export(Path(sys.argv[1]) if len(sys.argv) > 1 else config.WEB_OPENAPI_PATH)
    print(f"-> {out}")
