/**
 * Плавающая кнопка Telegram — появляется после прокрутки 300px.
 */
(function () {
  "use strict";

  var tgBtn = document.getElementById("tg-float");
  if (!tgBtn) {
    return;
  }

  var threshold = 300;
  var ticking = false;

  function update() {
    ticking = false;
    tgBtn.hidden = window.scrollY <= threshold;
  }

  window.addEventListener(
    "scroll",
    function () {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(update);
      }
    },
    { passive: true }
  );

  update();
})();
