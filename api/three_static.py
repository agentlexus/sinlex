"""Three.js static assets and browser API URL helpers."""
import os
import sys

from fastapi import Request

from api.config import BASE_DIR


def browser_api_prefix(request: Request = None) -> str:
    pub = os.environ.get("SINLEX_API_PUBLIC", "").strip()
    if pub:
        return pub.rstrip("/")
    if request is not None:
        xf_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        xf_host = (
            request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        ).split(",")[0].strip()
        if xf_proto and xf_host and not xf_host.startswith("127.") and "localhost" not in xf_host:
            return f"{xf_proto}://{xf_host}/api"
    return os.environ.get("SINLEX_API_PREFIX", "").strip()


def three_importmap_json(prefix: str = "") -> str:
    p = prefix or browser_api_prefix()
    static_three = f"{p}/static/three"
    return (
        f'{{"imports":{{"three":"{static_three}/three.module.js",'
        f'"three/addons/":"{static_three}/addons/"}}}}'
    )


def ensure_three_static() -> None:
    import urllib.request

    base = os.path.join(BASE_DIR, "static", "three")
    files = {
        "three.module.js": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
        "addons/controls/OrbitControls.js": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js",
        "addons/loaders/GLTFLoader.js": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js",
        "addons/utils/BufferGeometryUtils.js": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/utils/BufferGeometryUtils.js",
    }
    for rel, url in files.items():
        path = os.path.join(base, rel)
        if os.path.isfile(path) and os.path.getsize(path) > 1000:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            urllib.request.urlretrieve(url, path)
        except Exception as exc:
            print(f"three.js download failed {rel}: {exc}", file=sys.stderr)
