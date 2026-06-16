/**
 * Параллакс фона + появление по Z (единый transform, без рывка на старте).
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
    fromZ: -56,
    fromScale: 0.97,
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
  var productPreview = document.querySelector(".product-preview-section");
  if (!scene || !layer) {
    return;
  }

  var entranceStart = 0;
  var entranceStarted = false;
  var entranceDone = reduced;
  var ticking = false;

  function easeOut(t) {
    return 1 - Math.pow(1 - t, 2.8);
  }

  function getMaxScroll() {
    return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  }

  function entranceMotion(e) {
    return {
      tz: ENTRANCE.fromZ * (1 - e),
      scale: PARALLAX.baseScale * (ENTRANCE.fromScale + (1 - ENTRANCE.fromScale) * e),
    };
  }

  function layerTransform(ty, tz, scale) {
    return "translate3d(0, " + ty + "px, " + tz + "px) scale(" + scale + ")";
  }

  function entranceProgress() {
    if (entranceDone) {
      return 1;
    }
    if (!entranceStarted) {
      return 0;
    }
    var t = (performance.now() - entranceStart) / ENTRANCE.durationMs;
    if (t >= 1) {
      entranceDone = true;
      layer.style.opacity = "1";
      layer.classList.remove("bg-enter-z");
      return 1;
    }
    return easeOut(t);
  }

  function getBlurFadeDistance() {
    if (!productPreview) {
      return window.innerHeight * 0.85;
    }
    var sectionTop = productPreview.getBoundingClientRect().top + window.scrollY;
    return Math.max(window.innerHeight * 0.5, sectionTop - window.innerHeight * 0.1);
  }

  function apply() {
    var e = entranceProgress();
    var motion = entranceMotion(e);
    var maxScroll = getMaxScroll();
    var scroll = Math.min(window.scrollY, maxScroll);
    var scrollRatio = maxScroll > 0 ? scroll / maxScroll : 0;
    var baseOffset = PARALLAX.baseOffsetY * (1 - scrollRatio);
    var ty = baseOffset + scroll * PARALLAX.speedY;
    var objectPosY =
      PARALLAX.objectPosStart +
      (PARALLAX.objectPosEnd - PARALLAX.objectPosStart) * scrollRatio;

    layer.style.transform = layerTransform(ty, motion.tz, motion.scale);

    if (mountainImg) {
      mountainImg.style.objectPosition = "center " + objectPosY.toFixed(2) + "%";
    }

    if (!entranceDone) {
      layer.style.opacity = String(ENTRANCE.fromOpacity + (1 - ENTRANCE.fromOpacity) * e);
    }

    layer.style.setProperty("--mountain-edge-fade", String(Math.max(0, 0.62 * (1 - scrollRatio))));

    if (bgBlur) {
      var blurFadeDistance = getBlurFadeDistance();
      var blurFade =
        blurFadeDistance > 0 ? Math.max(0, 1 - scroll / blurFadeDistance) : 0;
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
      requestAnimationFrame(entranceLoop);
    }
  }

  function beginEntrance() {
    if (entranceStarted || entranceDone) {
      return;
    }
    entranceStarted = true;
    entranceStart = performance.now();
    entranceLoop();
  }

  function onBackgroundReady() {
    apply();
  }

  function watchBackgroundReady() {
    if (!mountainImg) {
      return;
    }
    function done() {
      if (mountainImg.decode) {
        mountainImg.decode().then(onBackgroundReady).catch(onBackgroundReady);
        return;
      }
      onBackgroundReady();
    }
    if (mountainImg.complete && mountainImg.naturalWidth > 0) {
      done();
      return;
    }
    mountainImg.addEventListener("load", done, { once: true });
    mountainImg.addEventListener("error", done, { once: true });
  }

  scene.style.perspective = PARALLAX.perspective;
  scene.style.perspectiveOrigin = PARALLAX.origin;
  layer.style.transformOrigin = PARALLAX.origin;
  layer.style.willChange = "transform, opacity";
  layer.style.setProperty("--mountain-edge-fade", "0.62");

  var startMotion = entranceMotion(0);
  layer.style.transform = layerTransform(PARALLAX.baseOffsetY, startMotion.tz, startMotion.scale);
  if (!reduced) {
    layer.style.opacity = String(ENTRANCE.fromOpacity);
  }

  if (reduced) {
    layer.classList.remove("bg-enter-z");
    layer.style.opacity = "1";
    if (bgBlur) bgBlur.style.opacity = "1";
    apply();
  } else {
    apply();
    beginEntrance();
    watchBackgroundReady();
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
})();
