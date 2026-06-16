/**
 * Инерционная прокрутка лендинга (колёсико / трекпад на desktop).
 * INERTIA: 0 = только нативная прокрутка, выше = дольше «докат».
 */
(function () {
  "use strict";

  var INERTIA = 3.5;
  window.SINLEX_SCROLL_INERTIA = INERTIA;

  if (INERTIA <= 0) {
    return;
  }
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }
  if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    return;
  }

  var ease = Math.max(0.045, 0.11 - INERTIA * 0.015);
  var wheelGain = 0.42 + INERTIA * 0.09;
  var maxY = function () {
    return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  };

  var current = window.scrollY;
  var target = current;
  var rafId = 0;

  function clamp(v) {
    return Math.max(0, Math.min(maxY(), v));
  }

  function loop() {
    rafId = 0;
    var diff = target - current;
    if (Math.abs(diff) < 0.4) {
      current = target;
      window.scrollTo(0, current);
      return;
    }
    current += diff * ease;
    window.scrollTo(0, current);
    rafId = requestAnimationFrame(loop);
  }

  function kick() {
    if (!rafId) {
      rafId = requestAnimationFrame(loop);
    }
  }

  window.addEventListener(
    "scroll",
    function () {
      if (!rafId) {
        current = window.scrollY;
        target = current;
      }
    },
    { passive: true }
  );

  window.addEventListener(
    "wheel",
    function (e) {
      if (e.ctrlKey || e.metaKey) {
        return;
      }
      if (Math.abs(e.deltaY) < Math.abs(e.deltaX) * 0.6) {
        return;
      }
      target = clamp(target + e.deltaY * wheelGain);
      e.preventDefault();
      kick();
    },
    { passive: false }
  );

  window.addEventListener("resize", function () {
    target = clamp(target);
    current = clamp(current);
  });

  window.sinlexScrollInertiaSync = function (y) {
    var next = clamp(y !== undefined ? y : window.scrollY);
    current = next;
    target = next;
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
  };
})();
