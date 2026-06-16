/**
 * Параллакс фона по скроллу (только Y).
 */
(function () {
  "use strict";

  var PARALLAX = {
    speedY: -0.042,
    baseOffsetY: -56,
    objectPosStart: 0,
    objectPosEnd: 82,
  };

  window.SINLEX_LANDING_PARALLAX = PARALLAX;

  var layer = document.querySelector(".bg-mountains");
  var mountainImg = layer && layer.querySelector("img");
  var bgBlur = document.querySelector(".bg-blur");
  var productPreview = document.querySelector(".product-preview-section");
  if (!layer) {
    return;
  }

  var ticking = false;

  function getMaxScroll() {
    return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  }

  function getBlurFadeDistance() {
    if (!productPreview) {
      return window.innerHeight * 0.85;
    }
    var sectionTop = productPreview.getBoundingClientRect().top + window.scrollY;
    return Math.max(window.innerHeight * 0.5, sectionTop - window.innerHeight * 0.1);
  }

  function apply() {
    var maxScroll = getMaxScroll();
    var scroll = Math.min(window.scrollY, maxScroll);
    var scrollRatio = maxScroll > 0 ? scroll / maxScroll : 0;
    var baseOffset = PARALLAX.baseOffsetY * (1 - scrollRatio);
    var ty = baseOffset + scroll * PARALLAX.speedY;
    var objectPosY =
      PARALLAX.objectPosStart +
      (PARALLAX.objectPosEnd - PARALLAX.objectPosStart) * scrollRatio;

    layer.style.transform = "translateY(" + ty + "px)";

    if (mountainImg) {
      mountainImg.style.objectPosition = "center " + objectPosY.toFixed(2) + "%";
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

  layer.style.transformOrigin = "center bottom";
  layer.style.willChange = "transform";
  layer.style.setProperty("--mountain-edge-fade", "0.62");

  apply();

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
})();
