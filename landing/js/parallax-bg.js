/**
 * Параллакс фона + появление по Z при загрузке (один контур transform, без рывка).
 */
(function () {
  "use strict";

  var PARALLAX = {
    perspective: "1200px",
    speedY: -0.052,
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
  var bgBlur = document.querySelector(".bg-blur");
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

  function getMaxScroll() {
    return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
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
    var maxScroll = getMaxScroll();
    var scroll = Math.min(window.scrollY, maxScroll);
    var scrollRatio = maxScroll > 0 ? scroll / maxScroll : 0;
    var ty = scroll * PARALLAX.speedY;
    var tz = scroll * PARALLAX.translateZPerPx + ENTRANCE.fromZ * (1 - e);
    var s = PARALLAX.baseScale * (ENTRANCE.fromScale + (1 - ENTRANCE.fromScale) * e);

    layer.style.transform =
      "translate3d(0, " + ty + "px, " + tz + "px) scale(" + s + ")";

    if (!entranceDone) {
      layer.style.opacity = String(ENTRANCE.fromOpacity + (1 - ENTRANCE.fromOpacity) * e);
    }

    var edgeFade = Math.min(1, Math.max(0.28, 0.28 + scrollRatio * 0.72));
    layer.style.setProperty("--mountain-edge-fade", edgeFade.toFixed(3));

    if (bgBlur) {
      var blurFade = Math.max(0, 1 - scrollRatio / 0.58);
      bgBlur.style.opacity = blurFade.toFixed(3);
    }

    var sceneFade =
      scrollRatio > 0.62 ? Math.max(0, 1 - (scrollRatio - 0.62) / 0.38) : 1;
    scene.style.opacity = sceneFade.toFixed(3);
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
    if (bgBlur) bgBlur.style.opacity = "1";
    scene.style.opacity = "1";
    layer.style.setProperty("--mountain-edge-fade", "0.55");
    apply();
  } else {
    entranceLoop();
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
})();
