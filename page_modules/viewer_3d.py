"""3D-viewer: Three.js в Streamlit iframe (/embed/3d-viewer), загрузка GLB."""
import base64
import json
import os
import urllib.parse

import requests
import streamlit as st

from upload_limits import GLB_INLINE_MAX_BYTES
from upload_step import stage_glb_for_viewer
from utils import API_KEY, NGROK_URL, api_resource_prefix, get_headers

API_PUBLIC_BROWSER = ""

_THREE_JS_CACHE = None

_MSG_GLB_MISSING = "Повторите загрузку STEP или дождитесь конвертации"
_MSG_NOT_GLB = "Сервер вернул не GLB"


def set_api_public_browser(url: str) -> None:
    global API_PUBLIC_BROWSER
    API_PUBLIC_BROWSER = url or ""


def api_browser_base() -> str:
    """Базовый URL API для iframe 3D (доступен из браузера пользователя)."""
    if API_PUBLIC_BROWSER:
        return API_PUBLIC_BROWSER.rstrip("/")
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx() is None:
            return "http://127.0.0.1:8001"
        host = (st.context.headers.get("Host") or "").split(",")[0].strip()
        if host:
            hostname = host.split(":")[0]
            proto = (st.context.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
            if not proto and hostname not in ("localhost", "127.0.0.1"):
                proto = "https"
            if proto == "https":
                return f"https://{host}/api"
            return f"http://{hostname}:8001"
    except Exception:
        pass
    return "http://127.0.0.1:8001"


def _viewer_error_session_key(project_name: str) -> str:
    return f"viewer_3d_error_{urllib.parse.quote(project_name, safe='')}"


def _glb_size_label(glb_size: int, glb_bytes: bytes) -> str:
    size = glb_size if glb_size > 0 else len(glb_bytes or b"")
    if size <= 0:
        return ""
    mb = size / (1024 * 1024)
    if mb >= 0.1:
        return f"~{mb:.1f} МБ"
    return f"~{max(1, size // 1024)} КБ"


def _probe_glb_server_error(project_name: str) -> str | None:
    try:
        resp = requests.get(
            f"{NGROK_URL}/{api_resource_prefix()}/glb/{urllib.parse.quote(project_name, safe='')}",
            headers=get_headers(),
            timeout=10,
        )
        if resp.status_code == 404:
            return _MSG_GLB_MISSING
        if resp.status_code == 200 and len(resp.content) > 4:
            sig = resp.content[:4]
            if not (sig[0] == 0x67 and sig[1] == 0x6C and sig[2] == 0x54 and sig[3] == 0x46):
                return _MSG_NOT_GLB
    except Exception:
        pass
    return None


def _detect_viewer_streamlit_error(
    project_name: str,
    glb_bytes: bytes,
    glb_base64: str,
) -> str | None:
    if not glb_bytes and not glb_base64:
        return _MSG_GLB_MISSING
    uses_fetch = not (glb_bytes and len(glb_bytes) <= GLB_INLINE_MAX_BYTES)
    if uses_fetch and not glb_bytes:
        return _probe_glb_server_error(project_name)
    return None


def glb_bytes_for_viewer(project_name: str, glb_base64: str) -> bytes:
    if glb_base64 and len(glb_base64) > 100:
        try:
            return base64.b64decode(glb_base64)
        except Exception:
            pass
    try:
        resp = requests.get(
            f"{NGROK_URL}/{api_resource_prefix()}/glb/{project_name}",
            headers=get_headers(),
            timeout=90,
        )
        if resp.status_code == 200 and len(resp.content) > 100:
            return resp.content
    except Exception:
        pass
    return b""


def three_js_sources() -> dict:
    """Кэш исходников Three.js для blob-import (без сетевых запросов из sandbox Streamlit)."""
    global _THREE_JS_CACHE
    if _THREE_JS_CACHE is not None:
        return _THREE_JS_CACHE
    base = "/opt/sinlex/static/three"

    def _read(rel: str) -> str:
        with open(os.path.join(base, rel), encoding="utf-8") as f:
            return f.read()

    _THREE_JS_CACHE = {
        "three": _read("three.module.js"),
        "orbit": _read("addons/controls/OrbitControls.js"),
        "gltf": _read("addons/loaders/GLTFLoader.js"),
        "bufutils": _read("addons/utils/BufferGeometryUtils.js"),
        "roomenv": _read("addons/environments/RoomEnvironment.js"),
    }
    return _THREE_JS_CACHE



def site_base_from_browser_api(api_base: str) -> str:
    base = (api_base or "").rstrip("/")
    if base.endswith("/api"):
        return base[:-4]
    return base or "http://127.0.0.1:8001"


def viewer_embed_src(
    project_name: str,
    *,
    height: int = 420,
    storage: str = "projects",
    email: str = "",
    sid: str = "",
    folder: str = "",
    embed_path: str = "3d-viewer",
    casting_ctx: dict | None = None,
    stock_glb_fetch_rel: str = "",
    stock_glb_url: str = "",
) -> str:
    """Публичный URL embed-страницы viewer (для st.iframe и новой вкладки)."""
    enc_name = urllib.parse.quote(project_name, safe="")
    q = f"key={API_KEY}"
    if email:
        q += f"&email={urllib.parse.quote(email, safe='')}"
    if sid:
        q += f"&sid={urllib.parse.quote(sid, safe='')}"
    if folder:
        q += f"&folder={urllib.parse.quote(folder, safe='')}"
    q += f"&height={int(height)}"
    if embed_path == "3d-viewer":
        q += f"&storage={urllib.parse.quote(storage, safe='')}"
    q = append_casting_embed_query(q, casting_ctx)
    # nginx: только /api/* → FastAPI; /embed/* без префикса отдаёт лендинг
    api_base = api_browser_base().rstrip("/")
    return f"{api_base}/embed/{embed_path}/{enc_name}?{q}"


def casting_embed_popup_src(
    project_name: str,
    *,
    height: int = 520,
    email: str = "",
    sid: str = "",
    folder: str = "",
    casting_ctx: dict | None = None,
) -> str:
    return viewer_embed_src(
        project_name,
        height=height,
        storage="casting",
        email=email,
        sid=sid,
        folder=folder,
        embed_path="3d-casting",
        casting_ctx=casting_ctx,
    )



def build_stock_glb_urls(
    project_name: str,
    allowance_mm: float,
    *,
    email: str = "",
    sid: str = "",
    folder: str = "",
) -> tuple[str, str]:
    """Относительный и абсолютный URL stock GLB (только литьё)."""
    allowance = float(allowance_mm or 0)
    if allowance <= 0:
        return "", ""
    enc_name = urllib.parse.quote(project_name, safe="")
    q = f"key={API_KEY}&allowance_mm={allowance:.4f}"
    if email:
        q += f"&email={urllib.parse.quote(email, safe='')}"
    if sid:
        q += f"&sid={urllib.parse.quote(sid, safe='')}"
    if folder:
        q += f"&folder={urllib.parse.quote(folder, safe='')}"
    rel = f"/api/casting/stock-glb/{enc_name}?{q}"
    abs_url = f"{api_browser_base()}/casting/stock-glb/{enc_name}?{q}"
    return rel, abs_url

def casting_ctx_for_html(casting_ctx: dict | None) -> dict:
    if not casting_ctx:
        return {"enabled": False}
    dims = casting_ctx.get("dimensions") or {}
    return {
        "enabled": True,
        "allowance_mm": float(casting_ctx.get("allowance_mm") or 0),
        "shrink_pct": float(casting_ctx.get("shrink_pct") or 0),
        "dim_x": float(dims.get("x") or 0),
        "dim_y": float(dims.get("y") or 0),
        "dim_z": float(dims.get("z") or 0),
    }


def append_casting_embed_query(q: str, casting_ctx: dict | None) -> str:
    ctx = casting_ctx_for_html(casting_ctx)
    if not ctx.get("enabled"):
        return q
    q += "&casting=1"
    q += f"&allowance_mm={ctx['allowance_mm']:.4f}"
    q += f"&shrink_pct={ctx['shrink_pct']:.4f}"
    q += f"&dim_x={ctx['dim_x']:.4f}"
    q += f"&dim_y={ctx['dim_y']:.4f}"
    q += f"&dim_z={ctx['dim_z']:.4f}"
    return q


def broadcast_casting_ctx_to_viewer(allowance_mm: float, shrink_pct: float) -> None:
    """postMessage в iframe viewer при смене параметров литья (fragment params)."""
    st.components.v1.html(
        f"""<script>
        (function() {{
          var msg = {{type:'sinlex_casting_ctx', allowance_mm:{float(allowance_mm):.6f}, shrink_pct:{float(shrink_pct):.6f}}};
          try {{
            var frames = window.parent.document.querySelectorAll('iframe');
            for (var i = 0; i < frames.length; i++) {{
              try {{ frames[i].contentWindow.postMessage(msg, '*'); }} catch (_e) {{}}
            }}
          }} catch (_e) {{}}
        }})();
        </script>""",
        height=0,
    )

def build_three_viewer_html(
    glb_bytes: bytes,
    glb_url: str,
    glb_fetch_rel: str = "",
    *,
    height: int = 420,
    glb_size: int = 0,
    casting_ctx: dict | None = None,
    stock_glb_fetch_rel: str = "",
    stock_glb_url: str = "",
) -> str:
    """Three.js в components.html: GLB data URI + inline JS через blob (без fetch модулей)."""
    src = three_js_sources()
    three_js = json.dumps(src["three"])
    orbit_js = json.dumps(src["orbit"])
    gltf_js = json.dumps(src["gltf"])
    buf_js = json.dumps(src["bufutils"])
    roomenv_js = json.dumps(src["roomenv"])
    if glb_bytes and len(glb_bytes) <= GLB_INLINE_MAX_BYTES:
        glb_src = json.dumps(
            "data:model/gltf-binary;base64," + base64.b64encode(glb_bytes).decode("ascii")
        )
        glb_rel_js = json.dumps("")
        glb_abs_js = json.dumps("")
        glb_size_label_js = json.dumps("")
    else:
        glb_src = json.dumps(glb_fetch_rel or glb_url)
        glb_rel_js = json.dumps(glb_fetch_rel or "")
        glb_abs_js = json.dumps(glb_url)
        glb_size_label_js = json.dumps(_glb_size_label(glb_size, glb_bytes))

    casting_ctx_js = json.dumps(casting_ctx_for_html(casting_ctx))
    stock_glb_rel_js = json.dumps(stock_glb_fetch_rel or "")
    stock_glb_abs_js = json.dumps(stock_glb_url or "")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
html,body{{width:100%;height:100%;margin:0;overflow:hidden;background:#ffffff}}
#wrap{{position:relative;width:100%;height:{height}px;min-height:320px}}
#load{{position:absolute;inset:0;z-index:5;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;
  background:#ffffff;color:#333;text-align:center;padding:12px}}
#loadStage{{font:14px/1.4 sans-serif;color:#333}}
.spinner{{width:36px;height:36px;border:3px solid #ddd;border-top-color:#14b8a6;border-radius:50%;animation:viewerSpin .8s linear infinite}}
@keyframes viewerSpin{{to{{transform:rotate(360deg)}}}}
canvas{{display:block}}
#camBar{{position:absolute;left:0;right:0;bottom:0;z-index:6;display:none;flex-wrap:wrap;gap:4px;justify-content:flex-end;
  padding:5px 8px;background:rgba(255,255,255,0.92);pointer-events:auto}}
#camBar button{{font:11px/1.2 sans-serif;padding:3px 8px;border:1px solid #ccc;border-radius:4px;background:#fff;color:#333;cursor:pointer}}
#camBar button:hover{{background:#eefaf8;border-color:#14b8a6}}
#camBar button.active{{background:#14b8a6;color:#fff;border-color:#14b8a6}}
#castingHint{{display:none;position:absolute;top:6px;left:8px;z-index:6;font:11px/1.3 sans-serif;color:#0f766e;background:rgba(255,255,255,.88);padding:3px 8px;border-radius:4px;border:1px solid #99f6e4;max-width:90%}}
@media (max-width:480px){{#camBar{{justify-content:center;padding:4px 6px}}#camBar button{{font-size:10px;padding:2px 6px}}}}
</style></head>
<body>
<div id="wrap"><div id="castingHint"></div><div id="load"><div class="spinner"></div><div id="loadStage">Загрузка 3D-модели…</div></div>
<div id="camBar">
  <button type="button" data-view="reset">Сброс</button>
  <button type="button" data-view="top">Сверху</button>
  <button type="button" data-view="front">Спереди</button>
  <button type="button" data-view="iso">Изо</button>
  <button type="button" id="btnWireframe" data-action="wireframe">Каркас</button>
</div></div>
<script>
(function() {{
  const GLB = {glb_src};
  const GLB_REL = {glb_rel_js};
  const GLB_ABS = {glb_abs_js};
  const GLB_SIZE_LABEL = {glb_size_label_js};
  const CASTING_CTX = {casting_ctx_js};
  const STOCK_GLB_REL = {stock_glb_rel_js};
  const STOCK_GLB_ABS = {stock_glb_abs_js};
  const THREE_CODE = {three_js};
  const ORBIT_CODE = {orbit_js};
  const GLTF_CODE = {gltf_js};
  const BUFUTILS_CODE = {buf_js};
  const ROOM_ENV_CODE = {roomenv_js};
  const loadEl = document.getElementById('load');
  const loadStage = document.getElementById('loadStage');
  const wrap = document.getElementById('wrap');
  function mapError(msg) {{
    var m = String(msg || 'Ошибка загрузки');
    if (/404|GLB HTTP 404|GLB не загружен|не найден/i.test(m)) {{
      return 'Повторите загрузку STEP или дождитесь конвертации';
    }}
    if (/не GLB|Сервер вернул не GLB/i.test(m)) {{
      return 'Сервер вернул не GLB';
    }}
    if (/Пустая геометрия/.test(m)) return 'Пустая геометрия модели';
    if (/GLB HTTP \\d+/.test(m)) return 'Не удалось загрузить GLB с сервера';
    return m.replace(/^Error:\\s*/i, '').slice(0, 160);
  }}
  function setStage(text) {{
    if (loadStage) loadStage.textContent = text;
  }}
  function fail(msg) {{
    var userMsg = mapError(msg);
    loadEl.style.display = 'flex';
    loadEl.innerHTML = '<span style="color:#c00;font:14px sans-serif;padding:12px;text-align:center">3D: ' + userMsg + '</span>';
    try {{
      window.parent.postMessage({{ type: 'sinlex_viewer_error', message: userMsg }}, '*');
    }} catch (_e) {{}}
  }}
  window.addEventListener('error', function(e) {{
    fail(e.message || 'ошибка скрипта');
  }});
  window.addEventListener('unhandledrejection', function(e) {{
    fail(e.reason && e.reason.message ? e.reason.message : String(e.reason));
  }});
  function mkBlobUrl(code) {{
    return URL.createObjectURL(new Blob([code], {{ type: 'text/javascript' }}));
  }}
  function patchThreeImports(code, threeUrl, extra) {{
    let s = code.replace(/from\\s+(['"])three\\1/g, "from '" + threeUrl + "'");
    if (extra) {{
      for (let i = 0; i < extra.length; i++) s = s.replace(extra[i][0], extra[i][1]);
    }}
    return s;
  }}
  (async function() {{
    try {{
      setStage('Загрузка Three.js…');
      const threeUrl = mkBlobUrl(THREE_CODE);
      const utilsUrl = mkBlobUrl(patchThreeImports(BUFUTILS_CODE, threeUrl));
      const gltfUrl = mkBlobUrl(patchThreeImports(GLTF_CODE, threeUrl, [
        [/from\\s+['"]\\.\\.\\/utils\\/BufferGeometryUtils\\.js['"]/g, "from '" + utilsUrl + "'"]
      ]));
      const orbitUrl = mkBlobUrl(patchThreeImports(ORBIT_CODE, threeUrl));
      const roomEnvUrl = mkBlobUrl(patchThreeImports(ROOM_ENV_CODE, threeUrl));
      const THREE = await import(threeUrl);
      const {{ OrbitControls }} = await import(orbitUrl);
      const {{ GLTFLoader }} = await import(gltfUrl);
      const scene = new THREE.Scene();
      const isCastingView = !!(CASTING_CTX && CASTING_CTX.enabled);
      scene.background = new THREE.Color(0xffffff);
      document.documentElement.style.background = '#ffffff';
      document.body.style.background = '#ffffff';
      if (loadEl) loadEl.style.background = '#ffffff';
      var camBarEl = document.getElementById('camBar');
      if (camBarEl) camBarEl.style.background = 'rgba(255,255,255,0.92)';
      const camera = new THREE.PerspectiveCamera(45, 1, 0.0001, 100000);
      const renderer = new THREE.WebGLRenderer({{ antialias: true }});
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      wrap.appendChild(renderer.domElement);
      var ambientInt = isCastingView ? 0.5 : 0.3;
      var hemiInt = isCastingView ? 0.58 : 0.44;
      scene.add(new THREE.AmbientLight(0xffffff, ambientInt));
      scene.add(new THREE.HemisphereLight(0xf4f7fa, 0x9aa3ac, hemiInt));
      var keyInt = isCastingView ? 1.05 : 1.22;
      var fillInt = isCastingView ? 0.4 : 0.32;
      var rimInt = isCastingView ? 0.3 : 0.6;
      var keyLight = new THREE.DirectionalLight(0xffffff, keyInt);
      keyLight.position.set(2.4, 3.8, 2.2);
      scene.add(keyLight);
      var fillLight = new THREE.DirectionalLight(0xffffff, fillInt);
      fillLight.position.set(-2.8, 1.6, 1.2);
      scene.add(fillLight);
      var rimLight = new THREE.DirectionalLight(0xffffff, rimInt);
      rimLight.position.set(-0.5, 2.2, -3.5);
      scene.add(rimLight);
      var bottomInt = isCastingView ? 0.28 : 0.24;
      var bottomLight = new THREE.DirectionalLight(0xffffff, bottomInt);
      bottomLight.position.set(0, -3.6, 0.8);
      scene.add(bottomLight);
      var pmremGenerator = null;
      if (!isCastingView) {{
        var camLight = new THREE.PointLight(0xffffff, 0.14, 0, 1);
        camera.add(camLight);
        const {{ RoomEnvironment }} = await import(roomEnvUrl);
        pmremGenerator = new THREE.PMREMGenerator(renderer);
        pmremGenerator.compileEquirectangularShader();
        scene.environment = pmremGenerator.fromScene(new RoomEnvironment(), 0.04).texture;
      }}
      if (THREE.ACESFilmicToneMapping !== undefined) {{
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = isCastingView ? 1.08 : 1.1;
      }}
      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      function resize() {{
        const w = wrap.clientWidth || 640, h = wrap.clientHeight || {height};
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      }}
      window.addEventListener('resize', resize);
      resize();
      let buf;
      if (GLB.startsWith('data:')) {{
        setStage('Разбор модели…');
        const b64 = GLB.split(',')[1];
        const bin = atob(b64);
        buf = new ArrayBuffer(bin.length);
        const u8 = new Uint8Array(buf);
        for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      }} else {{
        var glbLabel = GLB_SIZE_LABEL ? ' (' + GLB_SIZE_LABEL + ')' : '';
        setStage('Загрузка GLB' + glbLabel + '…');
        const urls = [];
        try {{
          const origin = (window.top || window.parent).location.origin;
          if (origin && GLB_REL) urls.push(origin + GLB_REL);
        }} catch (_e) {{}}
        if (GLB_ABS) urls.push(GLB_ABS);
        if (GLB && !GLB.startsWith('data:')) urls.push(GLB);
        if (GLB_REL) urls.push(GLB_REL);
        let lastErr = null;
        for (let i = 0; i < urls.length; i++) {{
          try {{
            const res = await fetch(urls[i]);
            if (!res.ok) {{
              if (res.status === 404) throw new Error('GLB HTTP 404');
              throw new Error('GLB HTTP ' + res.status);
            }}
            const candidate = await res.arrayBuffer();
            const u8 = new Uint8Array(candidate);
            if (u8.length >= 4 && u8[0] === 0x67 && u8[1] === 0x6c && u8[2] === 0x54 && u8[3] === 0x46) {{
              buf = candidate;
              lastErr = null;
              break;
            }}
            throw new Error('Сервер вернул не GLB');
          }} catch (e) {{
            lastErr = e;
          }}
        }}
        if (!buf) throw lastErr || new Error('GLB не загружен');
        setStage('Разбор модели…');
      }}
      const loader = new GLTFLoader();
      const gltf = await new Promise(function(ok, no) {{
        loader.parse(buf, '', ok, no);
      }});
      const DEFAULT_GRAY = 0xb8b8b8;
      const PROJECT_PART_COLOR = 0x858a92;
      const CASTING_PART_COLOR = 0xb8c4c0;
      const partColor = isCastingView ? CASTING_PART_COLOR : PROJECT_PART_COLOR;
      const partMetalness = isCastingView ? 0.22 : 0.48;
      const partRoughness = isCastingView ? 0.38 : 0.24;
      const projectClearcoat = 0.28;
      const projectClearcoatRough = 0.08;
      const projectEnvIntensity = 0.95;
      const meshEntries = [];
      function makeProjectMaterial(color) {{
        return new THREE.MeshPhysicalMaterial({{
          color: color,
          metalness: partMetalness,
          roughness: partRoughness,
          clearcoat: projectClearcoat,
          clearcoatRoughness: projectClearcoatRough,
          envMapIntensity: projectEnvIntensity,
          side: THREE.DoubleSide
        }});
      }}
      function makeDefaultMaterial() {{
        if (isCastingView) {{
          return new THREE.MeshStandardMaterial({{
            color: partColor, metalness: partMetalness, roughness: partRoughness, side: THREE.DoubleSide
          }});
        }}
        return makeProjectMaterial(partColor);
      }}
      function resolveMeshMaterial(mat) {{
        if (isCastingView) {{
          return makeDefaultMaterial();
        }}
        if (mat && (mat.isMeshStandardMaterial || mat.isMeshPhysicalMaterial)) {{
          const hex = mat.color ? mat.color.getHex() : DEFAULT_GRAY;
          if (hex !== DEFAULT_GRAY) {{
            return makeProjectMaterial(mat.color);
          }}
        }}
        return makeDefaultMaterial();
      }}
      function normalizeMeshMaterials(mesh) {{
        if (Array.isArray(mesh.material)) {{
          mesh.material = mesh.material.map(resolveMeshMaterial);
        }} else {{
          mesh.material = resolveMeshMaterial(mesh.material);
        }}
      }}
      function setMeshWireframe(mesh, on) {{
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        for (let i = 0; i < mats.length; i++) if (mats[i]) mats[i].wireframe = on;
      }}
      const model = gltf.scene;
      model.traverse(function(n) {{
        if (n.isMesh) {{
          const geom = n.geometry;
          if (geom && !geom.attributes.normal) geom.computeVertexNormals();
          normalizeMeshMaterials(n);
          meshEntries.push({{ mesh: n, edgeLines: null }});
        }}
      }});
      const box = new THREE.Box3().setFromObject(model);
      if (box.isEmpty()) throw new Error('Пустая геометрия');
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const partCenterOffset = center.clone();
      model.position.sub(partCenterOffset);
      const maxDim = Math.max(size.x, size.y, size.z, 0.001);
      const homePos = new THREE.Vector3(maxDim * 2.2, maxDim * 1.6, maxDim * 2.2);
      const viewDist = maxDim * 2.2;
      camera.position.copy(homePos);
      controls.target.set(0, 0, 0);
      controls.update();
      scene.add(model);
      const partSize = {{ x: size.x, y: size.y, z: size.z }};
      if (isCastingView) {{
        var gridY = -size.y / 2;
        var fineSpan = Math.max(maxDim * 5, 1);
        var fineGrid = new THREE.GridHelper(fineSpan, 20, 0xaaaaaa, 0xd4d4d4);
        fineGrid.position.y = gridY;
        scene.add(fineGrid);
        var horizonSpan = Math.max(maxDim * 280, viewDist * 90, 60);
        var horizonDiv = 72;
        var horizonGrid = new THREE.GridHelper(horizonSpan, horizonDiv, 0xc8c8c8, 0xeaeaea);
        horizonGrid.position.y = gridY - 0.0002;
        scene.add(horizonGrid);
      }}
      let stockGroup = null;
      let stockOn = false;
      let shrinkOn = false;
      let castingViewOn = false;
      let stockLoadGen = 0;
      let stockFallback = false;
      const STOCK_COLOR = 0x14b8a6;
      const stockShellMat = new THREE.MeshBasicMaterial({{
        color: STOCK_COLOR, transparent: true, opacity: 0.21,
        depthWrite: false, side: THREE.DoubleSide
      }});
      const castingSolidMat = new THREE.MeshStandardMaterial({{
        color: STOCK_COLOR, metalness: 0.22, roughness: 0.38, side: THREE.DoubleSide
      }});
      function isSharedStockMaterial(mat) {{
        return mat === stockShellMat || mat === castingSolidMat;
      }}
      function prepareCastingSolidMesh(mesh) {{
        var geom = mesh.geometry;
        if (!geom || !geom.attributes.position) return;
        geom.computeVertexNormals();
      }}
      function applyStockMaterials() {{
        if (!stockGroup) return;
        var mat = castingViewOn ? castingSolidMat : stockShellMat;
        stockGroup.renderOrder = castingViewOn ? 0 : -1;
        stockGroup.traverse(function(n) {{
          if (n.isMesh) {{
            if (castingViewOn) prepareCastingSolidMesh(n);
            n.material = mat;
          }}
          if (n.isLineSegments) n.visible = !castingViewOn;
        }});
      }}
      function disposeStockGroup() {{
        if (!stockGroup) return;
        scene.remove(stockGroup);
        stockGroup.traverse(function(n) {{
          if (n.geometry) n.geometry.dispose();
          if (n.material) {{
            var mats = Array.isArray(n.material) ? n.material : [n.material];
            mats.forEach(function(m) {{
              if (m && !isSharedStockMaterial(m)) m.dispose();
            }});
          }}
        }});
        stockGroup = null;
      }}
      function allowanceSceneUnits(allowanceMm) {{
        var a = Math.max(0, Number(allowanceMm) || 0);
        if (a <= 0) return 0;
        if (partSize.x < 5 && partSize.y < 5 && partSize.z < 5) return a / 1000;
        return a;
      }}
      function rebuildStockBBoxFallback() {{
        disposeStockGroup();
        if (!stockOn || !CASTING_CTX.enabled) return;
        var allowance = Math.max(0, Number(CASTING_CTX.allowance_mm) || 0);
        if (allowance <= 0) return;
        stockFallback = true;
        var a = allowanceSceneUnits(allowance);
        var sx = partSize.x + 2 * a;
        var sy = partSize.y + 2 * a;
        var sz = partSize.z + 2 * a;
        var boxGeom = new THREE.BoxGeometry(sx, sy, sz);
        var edges = new THREE.EdgesGeometry(boxGeom);
        var lines = new THREE.LineSegments(
          edges,
          new THREE.LineBasicMaterial({{ color: STOCK_COLOR, transparent: true, opacity: 0.9 }})
        );
        var faces = new THREE.Mesh(boxGeom, stockShellMat);
        stockGroup = new THREE.Group();
        stockGroup.add(faces);
        stockGroup.add(lines);
        stockGroup.renderOrder = -1;
        scene.add(stockGroup);
        applyStockMaterials();
      }}
      async function fetchStockArrayBuffer() {{
        var urls = [];
        try {{
          var origin = (window.top || window.parent).location.origin;
          if (origin && STOCK_GLB_REL) urls.push(origin + STOCK_GLB_REL);
        }} catch (_e) {{}}
        if (STOCK_GLB_ABS) urls.push(STOCK_GLB_ABS);
        if (STOCK_GLB_REL) urls.push(STOCK_GLB_REL);
        var lastErr = null;
        for (var i = 0; i < urls.length; i++) {{
          try {{
            var sep = urls[i].indexOf('?') >= 0 ? '&' : '?';
            var u = urls[i].replace(/allowance_mm=[^&]*/, 'allowance_mm=' + encodeURIComponent(Number(CASTING_CTX.allowance_mm) || 0));
            if (u.indexOf('allowance_mm=') < 0) u += sep + 'allowance_mm=' + encodeURIComponent(Number(CASTING_CTX.allowance_mm) || 0);
            var res = await fetch(u);
            if (!res.ok) throw new Error('stock HTTP ' + res.status);
            var candidate = await res.arrayBuffer();
            var u8 = new Uint8Array(candidate);
            if (u8.length >= 4 && u8[0] === 0x67 && u8[1] === 0x6c && u8[2] === 0x54 && u8[3] === 0x46) return candidate;
            throw new Error('не GLB');
          }} catch (e) {{ lastErr = e; }}
        }}
        throw lastErr || new Error('stock GLB не загружен');
      }}
      async function loadStockGlb() {{
        if (!isCastingView) return;
        disposeStockGroup();
        stockFallback = false;
        if (!stockOn || !CASTING_CTX.enabled) return;
        var allowance = Math.max(0, Number(CASTING_CTX.allowance_mm) || 0);
        if (allowance <= 0) return;
        if (!STOCK_GLB_REL && !STOCK_GLB_ABS) {{ rebuildStockBBoxFallback(); return; }}
        var gen = ++stockLoadGen;
        var prevDisplay = loadEl.style.display;
        loadEl.style.display = 'flex';
        setStage('Припуск…');
        try {{
          var buf = await fetchStockArrayBuffer();
          if (gen !== stockLoadGen) return;
          var stockGltf = await new Promise(function(ok, no) {{ loader.parse(buf, '', ok, no); }});
          stockGroup = stockGltf.scene;
          stockGroup.position.copy(model.position);
          stockGroup.renderOrder = -1;
          scene.add(stockGroup);
          applyStockMaterials();
        }} catch (_e) {{
          if (gen !== stockLoadGen) return;
          rebuildStockBBoxFallback();
        }} finally {{
          if (gen === stockLoadGen) loadEl.style.display = 'none';
        }}
      }}
      function applyShrinkScale() {{
        if (!CASTING_CTX.enabled) {{
          model.scale.set(1, 1, 1);
          return;
        }}
        var shrinkPct = Math.max(0, Number(CASTING_CTX.shrink_pct) || 0);
        var s = shrinkOn ? Math.max(0.01, 1 - shrinkPct / 100) : 1;
        model.scale.set(s, s, s);
      }}
      function updateCastingHint() {{
        var el = document.getElementById('castingHint');
        if (!el || !CASTING_CTX.enabled) return;
        var parts = [];
        if (stockOn) {{
          var a = Number(CASTING_CTX.allowance_mm) || 0;
          parts.push('Припуск: +' + a.toFixed(1) + ' мм/стор. (заготовка, offset STEP)' + (stockFallback ? ', bbox' : ''));
        }}
        if (shrinkOn) parts.push('Усадка: scale ' + (Math.max(0.01, 1 - (Number(CASTING_CTX.shrink_pct) || 0) / 100)).toFixed(4));
        if (castingViewOn) parts.push('Отливка: солид');
        if (parts.length) {{ el.textContent = parts.join(' · '); el.style.display = 'block'; }}
        else {{ el.style.display = 'none'; }}
      }}
      function applyCastingViewMode() {{
        if (!CASTING_CTX.enabled) return;
        model.visible = !castingViewOn;
        applyStockMaterials();
        var cb = document.getElementById('btnCasting');
        if (cb) cb.classList.toggle('active', castingViewOn);
      }}
      function refreshCastingVisuals() {{
        if (isCastingView) {{
          if (castingViewOn) stockOn = true;
          loadStockGlb();
        }}
        applyShrinkScale();
        applyCastingViewMode();
        updateCastingHint();
      }}
      window.addEventListener('message', function(ev) {{
        if (!ev.data || ev.data.type !== 'sinlex_casting_ctx') return;
        if (ev.data.allowance_mm !== undefined) CASTING_CTX.allowance_mm = ev.data.allowance_mm;
        if (ev.data.shrink_pct !== undefined) CASTING_CTX.shrink_pct = ev.data.shrink_pct;
        if ((Number(CASTING_CTX.allowance_mm) || 0) > 0 && !stockOn) {{
          stockOn = true;
          var sb = document.getElementById('btnStock');
          if (sb) sb.classList.add('active');
        }}
        refreshCastingVisuals();
      }});

      loadEl.style.display = 'none';
      const camBar = document.getElementById('camBar');
      function applyCameraView(name) {{
        controls.target.set(0, 0, 0);
        if (name === 'reset') {{
          camera.position.copy(homePos);
        }} else if (name === 'top') {{
          camera.position.set(0, viewDist * 1.15, 0.0001);
        }} else if (name === 'front') {{
          camera.position.set(0, 0, viewDist * 1.15);
        }} else if (name === 'iso') {{
          const k = viewDist * 0.72;
          camera.position.set(k, k, k);
        }}
        controls.update();
      }}
      if (camBar) {{
        camBar.style.display = 'flex';
        camBar.querySelectorAll('button[data-view]').forEach(function(btn) {{
          btn.addEventListener('click', function(ev) {{
            ev.preventDefault();
            ev.stopPropagation();
            applyCameraView(btn.getAttribute('data-view'));
          }});
        }});
        let wireframeOn = false;
        function setWireframeMode(on) {{
          wireframeOn = !!on;
          for (let i = 0; i < meshEntries.length; i++) {{
            const entry = meshEntries[i];
            setMeshWireframe(entry.mesh, wireframeOn);
            if (wireframeOn) {{
              if (!entry.edgeLines && entry.mesh.geometry) {{
                const edges = new THREE.EdgesGeometry(entry.mesh.geometry, 15);
                entry.edgeLines = new THREE.LineSegments(
                  edges,
                  new THREE.LineBasicMaterial({{ color: 0x333333, transparent: true, opacity: 0.65 }})
                );
                entry.mesh.add(entry.edgeLines);
              }}
              if (entry.edgeLines) entry.edgeLines.visible = true;
            }} else if (entry.edgeLines) {{
              entry.edgeLines.visible = false;
            }}
          }}
          const wfBtn = document.getElementById('btnWireframe');
          if (wfBtn) {{
            wfBtn.textContent = wireframeOn ? 'Тело' : 'Каркас';
            wfBtn.classList.toggle('active', wireframeOn);
          }}
        }}
        const wfBtn = document.getElementById('btnWireframe');
        if (wfBtn) {{
          wfBtn.addEventListener('click', function(ev) {{
            ev.preventDefault();
            ev.stopPropagation();
            setWireframeMode(!wireframeOn);
          }});
        }}
        if (CASTING_CTX.enabled && camBar) {{
          function addCastingBtn(id, label, onToggle) {{
            var b = document.createElement('button');
            b.type = 'button';
            b.id = id;
            b.textContent = label;
            b.addEventListener('click', function(ev) {{
              ev.preventDefault();
              ev.stopPropagation();
              onToggle(b);
            }});
            camBar.insertBefore(b, camBar.firstChild);
          }}
          addCastingBtn('btnStock', 'Припуск', function(b) {{
            stockOn = !stockOn;
            if (!stockOn && castingViewOn) {{
              castingViewOn = false;
              var cb0 = document.getElementById('btnCasting');
              if (cb0) cb0.classList.remove('active');
            }}
            b.classList.toggle('active', stockOn);
            refreshCastingVisuals();
          }});
          addCastingBtn('btnShrink', 'Усадка', function(b) {{
            shrinkOn = !shrinkOn;
            b.classList.toggle('active', shrinkOn);
            refreshCastingVisuals();
          }});
          addCastingBtn('btnCasting', 'Отливка', function(b) {{
            var allowance = Math.max(0, Number(CASTING_CTX.allowance_mm) || 0);
            if (!castingViewOn && allowance <= 0) return;
            castingViewOn = !castingViewOn;
            if (castingViewOn) {{
              stockOn = true;
              var sb1 = document.getElementById('btnStock');
              if (sb1) sb1.classList.add('active');
            }}
            b.classList.toggle('active', castingViewOn);
            refreshCastingVisuals();
          }});
          if ((Number(CASTING_CTX.allowance_mm) || 0) > 0) {{
            stockOn = true;
            var sb0 = document.getElementById('btnStock');
            if (sb0) sb0.classList.add('active');
            refreshCastingVisuals();
          }}
        }}
      }}
      (function anim() {{
        requestAnimationFrame(anim);
        controls.update();
        renderer.render(scene, camera);
      }})();
    }} catch (e) {{
      fail(e.message || String(e));
      console.error(e);
    }}
  }})();
}})();
</script></body></html>"""


def render_3d_viewer(
    project_name: str,
    glb_base64: str = "",
    glb_size: int = 0,
    *,
    height: int = 420,
    mode: str = "default",
    show_streamlit_errors: bool = True,
    casting_ctx: dict | None = None,
) -> None:
    """3D: Three.js через embed iframe (/embed/3d-viewer)."""
    if st.session_state.get("guest_mode") and not st.session_state.get("user_email"):
        st.warning("Для 3D-модели войдите в аккаунт (демо-режим без входа не поддерживает просмотр).")
        return
    email = (st.session_state.get("user_email") or "").strip()
    folder = (st.session_state.get("user_folder") or "").strip()
    sid = (st.session_state.get("auth_sid") or "").strip()
    if not email and not sid:
        st.warning("Для 3D-модели войдите в аккаунт.")
        return

    glb_bytes = glb_bytes_for_viewer(project_name, glb_base64)
    if glb_bytes and folder:
        try:
            stage_glb_for_viewer(project_name, glb_bytes)
        except Exception:
            pass

    err_key = _viewer_error_session_key(project_name)
    streamlit_err = _detect_viewer_streamlit_error(project_name, glb_bytes, glb_base64)
    if streamlit_err:
        st.session_state[err_key] = streamlit_err
    else:
        st.session_state.pop(err_key, None)

    if show_streamlit_errors:
        shown_err = streamlit_err or st.session_state.get(err_key)
        if shown_err:
            st.error(f"3D: {shown_err}")

    storage = api_resource_prefix()
    embed_src = viewer_embed_src(
        project_name,
        height=height,
        storage=storage,
        email=email,
        sid=sid,
        folder=folder,
        embed_path="3d-casting" if mode == "casting" else "3d-viewer",
        casting_ctx=casting_ctx if mode == "casting" else None,
    )
    st.iframe(embed_src, height=height, width="stretch")
    if mode == "casting":
        st.caption(
            "ЛКМ — вращение, колесо — масштаб. "
            "«Припуск» — бирюзовая заготовка (OCC offset STEP, +мм/стор.); «Усадка» — масштаб модели."
        )
    else:
        st.caption("ЛКМ — вращение, колесо — масштаб")
    if (
        mode == "casting"
        and not st.session_state.get("guest_mode")
        and (email or sid)
    ):
        popup_src = casting_embed_popup_src(
            project_name,
            height=height,
            email=email,
            sid=sid,
            folder=folder,
            casting_ctx=casting_ctx,
        )
        st.markdown(
            f'<p style="margin:0.25rem 0 0"><a href="{popup_src}" target="_blank" '
            f'rel="noopener noreferrer">Открыть в новой вкладке</a></p>',
            unsafe_allow_html=True,
        )
