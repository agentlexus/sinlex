/**
 * Параллакс фона + появление по Z при загрузке (один контур transform, без рывка).
 */
(function () {
  "use strict";

  var PARALLAX = {
    perspective: "1200px",
    speedY: -0.0684,
    maxScroll: 2400,
    translateZPerPx: 0,
    baseScale: 1,
    origin: "center bottom",
  };

  var ENTRANCE = {
    durationMs: 2700,
    fromZ: -80,
    fromScale: 0.95,
    fromOpacity: 0.2,
  };

  window.SINLEX_LANDING_PARALLAX = PARALLAX;

  var reduced = false;
  try {
    reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {}

  var scene = document.querySelector(".bg-scene");
  var layer = document.querySelector(".bg-mountains");
  if (!scene || !layer) {
    return;
  }

  scene.style.perspective = PARALLAX.perspective;
  scene.style.perspectiveOrigin = PARALLAX.origin;
  layer.style.transformOrigin = PARALLAX.origin;
  layer.style.willChange = "transform, opacity";

  var entranceStart = performance.now();
  var entranceDone = reduced;
  var ticking = false;
  var entranceFrame = 0;

  function easeOut(t) {
    return 1 - Math.pow(1 - t, 2.8);
  }

  function entranceProgress() {
    if (entranceDone) {
      return 1;
    }
    var t = (performance.now() - entranceStart) / ENTRANCE.durationMs;
    if (t >= 1) {
      entranceDone = true;
      layer.classList.remove("bg-enter-z");
      layer.style.opacity = "";
      return 1;
    }
    return easeOut(t);
  }

  function apply() {
    var e = entranceProgress();
    var scroll = Math.min(window.scrollY, PARALLAX.maxScroll);
    var ty = scroll * PARALLAX.speedY;
    var tz = scroll * PARALLAX.translateZPerPx + ENTRANCE.fromZ * (1 - e);
    var s = PARALLAX.baseScale * (ENTRANCE.fromScale + (1 - ENTRANCE.fromScale) * e);

    layer.style.transform =
      "translate3d(0, " + ty + "px, " + tz + "px) scale(" + s + ")";

    if (!entranceDone) {
      layer.style.opacity = String(ENTRANCE.fromOpacity + (1 - ENTRANCE.fromOpacity) * e);
    }
  }

  function onScroll() {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(function () {
        ticking = false;
        apply();
      });
    }
  }

  function entranceLoop() {
    apply();
    if (!entranceDone) {
      entranceFrame = requestAnimationFrame(entranceLoop);
    }
  }

  if (reduced) {
    layer.classList.remove("bg-enter-z");
    layer.style.opacity = "";
    apply();
  } else {
    entranceLoop();
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
})();
