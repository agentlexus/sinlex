/**
 * Верхняя строка (логотип + Вход): появляется при прокрутке ниже «Технолог v.1.0.1».
 */
(function () {
  "use strict";

  var anchor = document.getElementById("hero-tag-anchor");
  var bar = document.querySelector(".site-sticky-bar");
  if (!anchor || !bar) {
    return;
  }

  function setVisible(show) {
    bar.classList.toggle("is-visible", show);
    bar.setAttribute("aria-hidden", show ? "false" : "true");
    document.body.classList.toggle("sticky-bar-visible", show);
  }

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var reducedObserver = new IntersectionObserver(
      function (entries) {
        setVisible(!entries[0].isIntersecting);
      },
      { threshold: 0 }
    );
    reducedObserver.observe(anchor);
    return;
  }

  var observer = new IntersectionObserver(
    function (entries) {
      setVisible(!entries[0].isIntersecting);
    },
    { threshold: 0, rootMargin: "0px 0px 0px 0px" }
  );

  observer.observe(anchor);
})();
