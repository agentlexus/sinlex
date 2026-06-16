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

  if (!layer) {

    return;

  }



  var ticking = false;



  function getMaxScroll() {

    return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);

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


