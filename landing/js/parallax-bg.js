/**
 * Параллакс фона + появление по Z при загрузке (один контур transform, без рывка).
 */
(function () {
  "use strict";

  var PARALLAX = {
    perspective: "1200px",
    speedY: -0.042,
    translateZPerPx: 0,
    baseScale: 1,
    origin: "center bottom",
    baseOffsetY: -56,
    objectPosStart: 0,
    objectPosEnd: 82,
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
  var mountainImg = layer && layer.querySelector("img");
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
    var baseOffset = PARALLAX.baseOffsetY * (1 - scrollRatio);
    var ty = baseOffset + scroll * PARALLAX.speedY;
    var tz = scroll * PARALLAX.translateZPerPx + ENTRANCE.fromZ * (1 - e);
    var s = PARALLAX.baseScale * (ENTRANCE.fromScale + (1 - ENTRANCE.fromScale) * e);
    var objectPosY =
      PARALLAX.objectPosStart +
      (PARALLAX.objectPosEnd - PARALLAX.objectPosStart) * scrollRatio;

    layer.style.transform =
      "translate3d(0, " + ty + "px, " + tz + "px) scale(" + s + ")";

    if (mountainImg) {
      mountainImg.style.objectPosition = "center " + objectPosY.toFixed(2) + "%";
    }

    if (!entranceDone) {
      layer.style.opacity = String(ENTRANCE.fromOpacity + (1 - ENTRANCE.fromOpacity) * e);
    }

    var edgeFade = Math.max(0, 0.62 * (1 - scrollRatio));
    layer.style.setProperty("--mountain-edge-fade", edgeFade.toFixed(3));

    if (bgBlur) {
      var blurFade = Math.max(0, 1 - scrollRatio / 0.9);
      bgBlur.style.opacity = blurFade.toFixed(3);
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
    if (bgBlur) bgBlur.style.opacity = "1";
    layer.style.setProperty("--mountain-edge-fade", "0.55");
    if (mountainImg) {
      mountainImg.style.objectPosition = "center " + PARALLAX.objectPosStart + "%";
    }
    apply();
  } else {
    entranceLoop();
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
})();
