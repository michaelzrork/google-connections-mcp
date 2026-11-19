"""Icons: one per endpoint, for AI apps that show a connector's picture.

Two ways a client can find one, and this server offers both:
  - `icons` in the MCP serverInfo (spec 2025-11-25), per endpoint: /gmail/mcp
    names /icons/gmail.png, /mcp names /icons/google-connections.png.
  - The origin's favicon (/favicon.ico, /favicon.svg, /apple-touch-icon.png and
    a <link rel="icon"> on /), which is per origin, so it is the general icon.

The art is original (not Google's product logos): SVGs in icons/, PNGs rendered
from them by scripts/render_icons.js. Served from memory, no sign-in needed.
"""
from pathlib import Path

from mcp.types import Icon
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

ICON_DIR = Path(__file__).parent / "icons"
GENERAL = "google-connections"  # the icon for /mcp and the favicon
_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
_CACHE = "public, max-age=86400"


def server_icons(base_url: str, name: str) -> list[Icon]:
    """serverInfo icons for one endpoint. PNG first: clients MUST support PNG,
    SVG only SHOULD."""
    return [
        Icon(src=f"{base_url}/icons/{name}.png", mimeType="image/png", sizes=["256x256"]),
        Icon(src=f"{base_url}/icons/{name}.svg", mimeType="image/svg+xml", sizes=["any"]),
    ]


def _load() -> dict[str, tuple[bytes, str]]:
    """URL path -> (bytes, content type), read once at startup."""
    files = {}
    for f in sorted(ICON_DIR.iterdir()):
        if f.suffix in (".svg", ".png") and f.stem not in ("apple-touch-icon",):
            files[f"/icons/{f.name}"] = (f.read_bytes(), _TYPES[f.suffix])
    files["/favicon.ico"] = ((ICON_DIR / "favicon.ico").read_bytes(), _TYPES[".ico"])
    files["/favicon.svg"] = ((ICON_DIR / f"{GENERAL}.svg").read_bytes(), _TYPES[".svg"])
    files["/apple-touch-icon.png"] = ((ICON_DIR / "apple-touch-icon.png").read_bytes(), _TYPES[".png"])
    return files


_HOME = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Google Connections MCP</title>
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
</head><body><p>Google Connections MCP. Add <code>/mcp</code> (or <code>/&lt;product&gt;/mcp</code>)
as a connector in your AI app.</p></body></html>
"""


def icon_routes() -> list[Route]:
    files = _load()

    def serve(body: bytes, ctype: str):
        async def endpoint(request: Request):
            return Response(body, media_type=ctype, headers={"Cache-Control": _CACHE})
        return endpoint

    async def home(request: Request):
        return HTMLResponse(_HOME, headers={"Cache-Control": _CACHE})

    routes = [Route(path, endpoint=serve(body, ctype), methods=["GET", "HEAD"])
              for path, (body, ctype) in files.items()]
    routes.append(Route("/", endpoint=home, methods=["GET", "HEAD"]))
    return routes
