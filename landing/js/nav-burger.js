/**
 * Бургер-меню навигации в top-bar и sticky bar (мобильные экраны).
 */
(function () {
  "use strict";

  var mobileMq = window.matchMedia("(max-width: 900px)");
  var burgers = document.querySelectorAll(".nav-burger");

  if (!burgers.length) {
    return;
  }

  function panelFor(btn) {
    var id = btn.getAttribute("aria-controls");
    return id ? document.getElementById(id) : null;
  }

  function closeAll() {
    burgers.forEach(function (btn) {
      var panel = panelFor(btn);
      btn.setAttribute("aria-expanded", "false");
      btn.classList.remove("is-open");
      if (panel) {
        panel.classList.remove("is-open");
      }
    });
    document.body.classList.remove("nav-menu-open");
  }

  function openMenu(btn) {
    var panel = panelFor(btn);
    if (!panel) {
      return;
    }
    closeAll();
    btn.setAttribute("aria-expanded", "true");
    btn.classList.add("is-open");
    panel.classList.add("is-open");
    document.body.classList.add("nav-menu-open");
  }

  function toggleMenu(btn) {
    if (btn.getAttribute("aria-expanded") === "true") {
      closeAll();
      return;
    }
    openMenu(btn);
  }

  burgers.forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!mobileMq.matches) {
        return;
      }
      toggleMenu(btn);
    });
  });

  document.addEventListener("click", function (e) {
    if (!mobileMq.matches) {
      return;
    }
    if (e.target.closest(".nav-burger") || e.target.closest(".section-nav.is-open")) {
      return;
    }
    closeAll();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeAll();
    }
  });

  document.addEventListener("click", function (e) {
    if (e.target.closest(".section-nav__link[data-section-target]")) {
      closeAll();
    }
  });

  if (mobileMq.addEventListener) {
    mobileMq.addEventListener("change", function () {
      if (!mobileMq.matches) {
        closeAll();
      }
    });
  }
})();
