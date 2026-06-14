import * as THREE from "../assets/vendor/three/three.module.js";
import { GLTFLoader } from "../assets/vendor/three/addons/loaders/GLTFLoader.js";

const MODEL_URL = "assets/models/compressor-wheel.glb";

function initThreeViewer() {
  const canvas = document.getElementById("three-viewer");

  if (!canvas) return;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xffffff);

  const rect = canvas.getBoundingClientRect();
  const width = rect.width || 1024;
  const height = rect.height || 627;

  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  camera.position.set(0, 0, 4);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  scene.add(new THREE.HemisphereLight(0xffffff, 0xe8eef5, 1.35));

  const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
  keyLight.position.set(5, 10, 7);
  scene.add(keyLight);

  const fillLight = new THREE.DirectionalLight(0xbfdbfe, 0.35);
  fillLight.position.set(-4, -2, 5);
  scene.add(fillLight);

  let isDragging = false;
  let prevX = 0;
  let prevY = 0;
  let rotX = 0.25;
  let rotY = 0;
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
  }

  function applyDefaultMaterial(object) {
    const material = new THREE.MeshStandardMaterial({
      color: 0xb7c0ca,
      metalness: 0.52,
      roughness: 0.32,
      envMapIntensity: 0.85
    });

    object.traverse(function (child) {
      if (!child.isMesh) return;
      child.material = material;
      child.castShadow = false;
      child.receiveShadow = false;
    });
  }

  const loader = new GLTFLoader();
  loader.load(
    MODEL_URL,
    function (gltf) {
      model = gltf.scene;
      applyDefaultMaterial(model);
      fitModelToView(model);
      scene.add(model);
    },
    undefined,
    function (error) {
      console.error("Failed to load landing 3D model", error);
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
    rotX += (x - prevX) * 0.003;
    rotY += (y - prevY) * 0.003;
    rotY = Math.max(-1.2, Math.min(1.2, rotY));
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
    if (model && !isDragging) rotX += dt * 0.15;
    if (model) {
      model.rotation.x = rotX;
      model.rotation.y = rotY;
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
