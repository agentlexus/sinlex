import * as THREE from "../assets/vendor/three/three.module.js";
import { GLTFLoader } from "../assets/vendor/three/addons/loaders/GLTFLoader.js";

const MODEL_URL = "assets/models/compressor-wheel.glb";

function initThreeViewer() {
  const canvas = document.getElementById("three-viewer");

  if (!canvas) return;

  const scene = new THREE.Scene();
  scene.background = null;

  const rect = canvas.getBoundingClientRect();
  const width = rect.width || 1024;
  const height = rect.height || 627;

  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  camera.position.set(0, 0, 4);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);

  scene.add(new THREE.HemisphereLight(0xffffff, 0xe8eef5, 1.35));

  const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
  keyLight.position.set(5, 10, 7);
  scene.add(keyLight);

  const fillLight = new THREE.DirectionalLight(0xbfdbfe, 0.35);
  fillLight.position.set(-4, -2, 5);
  scene.add(fillLight);

  const viewGroup = new THREE.Group();
  const spinGroup = new THREE.Group();
  const grid = new THREE.GridHelper(3.2, 16, 0x64748b, 0x94a3b8);
  grid.rotation.z = Math.PI / 2;
  grid.position.x = 0;
  grid.material.transparent = true;
  grid.material.opacity = 0.28;
  viewGroup.rotation.x = 0.62;
  viewGroup.rotation.y = 0.38;
  viewGroup.rotation.z = -1.79;
  viewGroup.add(grid);
  viewGroup.add(spinGroup);
  scene.add(viewGroup);

  let isDragging = false;
  let prevX = 0;
  let prevY = 0;
  let model = null;
  let spinAxis = new THREE.Vector3(0, 0, 1);
  const screenXAxis = new THREE.Vector3(1, 0, 0);
  const screenYAxis = new THREE.Vector3(0, 1, 0);

  function fitModelToView(object) {
    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const scale = 1.65 / maxDim;

    object.position.sub(center);
    object.scale.setScalar(scale);
    spinAxis = findDetailAxis(size);

    const fittedBox = new THREE.Box3().setFromObject(object);
    const fittedSize = fittedBox.getSize(new THREE.Vector3());
    const cameraDistance = Math.max(fittedSize.x, fittedSize.y, fittedSize.z) * 1.55;
    camera.position.set(0, 0, Math.max(cameraDistance, 3));
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
  }

  function findDetailAxis(size) {
    const dimensions = [
      { axis: new THREE.Vector3(1, 0, 0), value: size.x },
      { axis: new THREE.Vector3(0, 1, 0), value: size.y },
      { axis: new THREE.Vector3(0, 0, 1), value: size.z }
    ];
    dimensions.sort(function (a, b) {
      return a.value - b.value;
    });
    return dimensions[0].axis;
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
      spinGroup.add(model);
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
    viewGroup.rotateOnWorldAxis(screenYAxis, (x - prevX) * 0.003);
    viewGroup.rotateOnWorldAxis(screenXAxis, (y - prevY) * 0.003);
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
    if (model && !isDragging) spinGroup.rotateOnAxis(spinAxis, -dt * 0.2);
    renderer.render(scene, camera);
  }
  requestAnimationFrame(animate);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initThreeViewer);
} else {
  initThreeViewer();
}
