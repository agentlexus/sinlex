/**
 * Навигация по секциям лендинга и кнопка «наверх» (без фиксированного snap-скролла).
 */
(function () {
  "use strict";

  var modules = Array.prototype.slice.call(document.querySelectorAll(".landing-module"));
  if (!modules.length) {
    return;
  }

  var navHosts = document.querySelectorAll("[data-section-nav-host]");
  var scrollTopBtn = document.getElementById("scroll-to-top");
  var activeId = "";
  var ticking = false;
  var reduced = false;

  try {
    reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {}

  function scrollBehavior() {
    return reduced ? "auto" : "smooth";
  }

  modules.forEach(function (mod, index) {
    if (!mod.id) {
      mod.id = "section-" + (index + 1);
    }
  });

  function buildNav() {
    navHosts.forEach(function (host) {
      var items = modules
        .map(function (mod) {
          var label =
            mod.getAttribute("data-section-label") ||
            mod.getAttribute("data-section-short") ||
            mod.id;
          return (
            '<li><a class="section-nav__link btn-login" href="#' +
            mod.id +
            '" data-section-target="' +
            mod.id +
            '">' +
            label +
            "</a></li>"
          );
        })
        .join("");
      host.innerHTML = '<ol class="section-nav__list">' + items + "</ol>";
    });
  }

  function scrollToModule(mod) {
    if (!mod) {
      return;
    }
    var top = mod.getBoundingClientRect().top + window.scrollY;
    var nextTop = Math.max(0, top);
    if (typeof window.sinlexScrollInertiaSync === "function") {
      window.sinlexScrollInertiaSync(nextTop);
    }
    window.scrollTo({
      top: nextTop,
      behavior: scrollBehavior(),
    });
  }

  function getActiveModule() {
    var marker = window.innerHeight * 0.35;
    var best = modules[0];
    var bestDist = Infinity;
    modules.forEach(function (mod) {
      var rect = mod.getBoundingClientRect();
      var dist = Math.abs(rect.top - marker);
      if (rect.top <= marker && rect.bottom > marker) {
        best = mod;
        bestDist = 0;
        return;
      }
      if (dist < bestDist) {
        bestDist = dist;
        best = mod;
      }
    });
    return best;
  }

  function updateUi() {
    var active = getActiveModule();
    var id = active ? active.id : "";
    if (id === activeId) {
      return;
    }
    activeId = id;
    document.querySelectorAll(".section-nav__link").forEach(function (link) {
      var isActive = link.getAttribute("data-section-target") === id;
      link.classList.toggle("is-active", isActive);
      link.setAttribute("aria-current", isActive ? "location" : "false");
    });
    if (scrollTopBtn) {
      scrollTopBtn.hidden = id === modules[0].id;
    }
  }

  function onScroll() {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(function () {
        ticking = false;
        updateUi();
      });
    }
  }

  buildNav();
  updateUi();

  document.addEventListener("click", function (e) {
    var link = e.target.closest(".section-nav__link[data-section-target]");
    if (!link) {
      return;
    }
    var target = document.getElementById(link.getAttribute("data-section-target"));
    if (!target) {
      return;
    }
    e.preventDefault();
    scrollToModule(target);
    if (history.replaceState) {
      history.replaceState(null, "", "#" + target.id);
    }
  });

  if (scrollTopBtn) {
    scrollTopBtn.addEventListener("click", function () {
      if (typeof window.sinlexScrollInertiaSync === "function") {
        window.sinlexScrollInertiaSync(0);
      }
      window.scrollTo({
        top: 0,
        behavior: scrollBehavior(),
      });
      if (history.replaceState) {
        history.replaceState(null, "", window.location.pathname);
      }
    });
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
})();
