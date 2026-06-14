// #region agent log
(function () {
  const ENDPOINT = "http://127.0.0.1:7444/ingest/7c6644a2-5a2c-4a98-9204-9341cbab9ed4";

  window.__sinlexThreeStatus = function (message) {
    const node = document.getElementById("three-debug-status");
    if (node) node.textContent = "3D debug: " + message;
  };

  window.__sinlexDebugLog = function (hypothesisId, message, data) {
    fetch(ENDPOINT, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Debug-Session-Id": "c43c14"},
      body: JSON.stringify({
        sessionId: "c43c14",
        runId: "post-csp-external-script",
        hypothesisId,
        location: "landing/js/three-viewer.js",
        message,
        data,
        timestamp: Date.now()
      })
    }).catch(function () {});
  };

  window.addEventListener("error", function (event) {
    window.__sinlexThreeStatus("window error: " + event.message);
    window.__sinlexDebugLog("H12,H13", "window error", {
      message: event.message,
      source: event.filename,
      lineno: event.lineno,
      colno: event.colno
    });
  }, true);

  window.__sinlexDebugLog("H12,H13,H14", "external viewer script reached", {
    href: window.location.href,
    hasThree: typeof window.THREE !== "undefined",
    threeRevision: window.THREE && window.THREE.REVISION,
    readyState: document.readyState
  });
  window.__sinlexThreeStatus("external script reached, THREE=" + (typeof window.THREE !== "undefined"));
})();
// #endregion

function initThreeViewer() {
  const canvas = document.getElementById("three-viewer");

  // #region agent log
  window.__sinlexDebugLog && window.__sinlexDebugLog("H13,H14", "initThreeViewer entry", {
    canvasFound: !!canvas,
    hasThree: typeof window.THREE !== "undefined",
    readyState: document.readyState
  });
  // #endregion

  if (!canvas) {
    window.__sinlexThreeStatus && window.__sinlexThreeStatus("canvas not found");
    return;
  }
  if (typeof THREE === "undefined") {
    window.__sinlexThreeStatus && window.__sinlexThreeStatus("THREE undefined");
    return;
  }

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xffffff);

  const rect = canvas.getBoundingClientRect();
  const width = rect.width || 1024;
  const height = rect.height || 627;

  // #region agent log
  window.__sinlexDebugLog && window.__sinlexDebugLog("H14", "canvas geometry", {
    rectWidth: rect.width,
    rectHeight: rect.height,
    clientWidth: canvas.clientWidth,
    clientHeight: canvas.clientHeight,
    cssWidth: getComputedStyle(canvas).width,
    cssHeight: getComputedStyle(canvas).height
  });
  // #endregion

  window.__sinlexThreeStatus && window.__sinlexThreeStatus("canvas " + rect.width + "x" + rect.height + ", THREE " + THREE.REVISION);
  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  camera.position.set(0, 0, 3);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    window.__sinlexThreeStatus && window.__sinlexThreeStatus("renderer created");
  } catch (error) {
    window.__sinlexThreeStatus && window.__sinlexThreeStatus("renderer error: " + error.message);
    throw error;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height, false);

  scene.add(new THREE.HemisphereLight(0xffffff, 0xb0b0b0, 1));

  const keyLight = new THREE.DirectionalLight(0xffffff, 0.8);
  keyLight.position.set(5, 10, 7);
  scene.add(keyLight);

  const model = new THREE.Mesh(
    new THREE.TorusKnotGeometry(0.72, 0.22, 160, 24),
    new THREE.MeshNormalMaterial()
  );

  // #region agent log
  window.__sinlexDebugLog && window.__sinlexDebugLog("H15", "model prepared", {
    geometryType: model.geometry.type,
    materialType: model.material.type,
    cameraZ: camera.position.z
  });
  // #endregion

  let isDragging = false;
  let prevX = 0;
  let prevY = 0;
  let rotY = 0;
  let rotX = 0.25;

  scene.add(model);

  function pointerPosition(event) {
    const touch = event.touches && event.touches[0];
    return {
      x: touch ? touch.clientX : event.clientX,
      y: touch ? touch.clientY : event.clientY
    };
  }

  function onPointerDown(event) {
    isDragging = true;
    const pos = pointerPosition(event);
    prevX = pos.x || 0;
    prevY = pos.y || 0;
  }

  function onPointerMove(event) {
    if (!isDragging) return;
    const pos = pointerPosition(event);
    const x = pos.x || 0;
    const y = pos.y || 0;
    rotY += (x - prevX) * 0.003;
    rotX += (y - prevY) * 0.003;
    rotX = Math.max(-1.2, Math.min(1.2, rotX));
    prevX = x;
    prevY = y;
  }

  function onPointerUp() {
    isDragging = false;
  }

  canvas.addEventListener("mousedown", onPointerDown);
  window.addEventListener("mousemove", onPointerMove);
  window.addEventListener("mouseup", onPointerUp);
  canvas.addEventListener("touchstart", onPointerDown, { passive: true });
  window.addEventListener("touchmove", onPointerMove, { passive: true });
  window.addEventListener("touchend", onPointerUp);

  function onResize() {
    const box = canvas.getBoundingClientRect();
    const nextWidth = box.width || width;
    const nextHeight = box.height || height;
    camera.aspect = nextWidth / nextHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(nextWidth, nextHeight, false);
  }
  window.addEventListener("resize", onResize);

  let lastTime = 0;
  let firstRenderLogged = false;
  function animate(time) {
    requestAnimationFrame(animate);
    const dt = (time - lastTime) / 1000;
    lastTime = time;
    if (model && !isDragging) rotY += dt * 0.15;
    if (model) {
      model.rotation.y = rotY;
      model.rotation.x = rotX;
    }
    renderer.render(scene, camera);
    if (!firstRenderLogged) {
      firstRenderLogged = true;
      // #region agent log
      window.__sinlexDebugLog && window.__sinlexDebugLog("H15", "first render", {
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
        sceneChildren: scene.children.length,
        rendererConnected: renderer.domElement.isConnected
      });
      // #endregion
      window.__sinlexThreeStatus && window.__sinlexThreeStatus("first render ok " + canvas.width + "x" + canvas.height);
    }
  }
  requestAnimationFrame(animate);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initThreeViewer);
} else {
  initThreeViewer();
}
