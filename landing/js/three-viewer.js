import * as THREE from "../assets/vendor/three/three.module.js";
import { GLTFLoader } from "../assets/vendor/three/addons/loaders/GLTFLoader.js";

const MODEL_URL = "assets/models/compressor-wheel.glb";
const DEBUG_ENDPOINT = "http://127.0.0.1:7444/ingest/7c6644a2-5a2c-4a98-9204-9341cbab9ed4";

function setStatus(message) {
  const node = document.getElementById("three-debug-status");
  if (node) node.textContent = "3D debug: " + message;
}

function debugLog(hypothesisId, message, data) {
  fetch(DEBUG_ENDPOINT, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Debug-Session-Id": "c43c14"},
    body: JSON.stringify({
      sessionId: "c43c14",
      runId: "glb-model-load",
      hypothesisId,
      location: "landing/js/three-viewer.js",
      message,
      data,
      timestamp: Date.now()
    })
  }).catch(function () {});
}

function initThreeViewer() {
  const canvas = document.getElementById("three-viewer");

  // #region agent log
  debugLog("H17,H20", "module viewer entry", {
    canvasFound: !!canvas,
    readyState: document.readyState,
    modelUrl: MODEL_URL
  });
  // #endregion

  if (!canvas) {
    setStatus("canvas not found");
    return;
  }

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xffffff);

  const rect = canvas.getBoundingClientRect();
  const width = rect.width || 1024;
  const height = rect.height || 627;

  // #region agent log
  debugLog("H20", "canvas geometry before GLB load", {
    rectWidth: rect.width,
    rectHeight: rect.height,
    clientWidth: canvas.clientWidth,
    clientHeight: canvas.clientHeight
  });
  // #endregion

  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  camera.position.set(0, 0, 4);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height, false);

  scene.add(new THREE.HemisphereLight(0xffffff, 0xb0b0b0, 1));

  const keyLight = new THREE.DirectionalLight(0xffffff, 0.8);
  keyLight.position.set(5, 10, 7);
  scene.add(keyLight);

  let isDragging = false;
  let prevX = 0;
  let prevY = 0;
  let rotY = 0;
  let rotX = 0.25;
  let model = null;

  function fitModelToView(object) {
    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const scale = 2.2 / maxDim;

    object.position.sub(center);
    object.scale.setScalar(scale);
    object.rotation.x = rotX;

    const fittedBox = new THREE.Box3().setFromObject(object);
    const fittedSize = fittedBox.getSize(new THREE.Vector3());
    const cameraDistance = Math.max(fittedSize.x, fittedSize.y, fittedSize.z) * 1.55;
    camera.position.set(0, 0, Math.max(cameraDistance, 3));
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();

    // #region agent log
    debugLog("H18,H19", "GLB model fitted", {
      sourceSize: {x: size.x, y: size.y, z: size.z},
      scale,
      cameraZ: camera.position.z,
      children: object.children.length
    });
    // #endregion
  }

  function applyDefaultMaterial(object) {
    object.traverse(function (child) {
      if (!child.isMesh) return;
      child.material = new THREE.MeshNormalMaterial();
      child.castShadow = false;
      child.receiveShadow = false;
    });
  }

  setStatus("loading GLB");
  const loader = new GLTFLoader();
  loader.load(
    MODEL_URL,
    function (gltf) {
      model = gltf.scene;
      applyDefaultMaterial(model);
      fitModelToView(model);
      scene.add(model);
      setStatus("GLB loaded");

      // #region agent log
      debugLog("H16,H18", "GLB loaded", {
        animations: gltf.animations.length,
        children: model.children.length
      });
      // #endregion
    },
    undefined,
    function (error) {
      setStatus("GLB error: " + error.message);

      // #region agent log
      debugLog("H16,H18", "GLB load error", {
        message: error.message,
        type: error.type,
        targetStatus: error.target && error.target.status
      });
      // #endregion
    }
  );

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
  }
  requestAnimationFrame(animate);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initThreeViewer);
} else {
  initThreeViewer();
}
