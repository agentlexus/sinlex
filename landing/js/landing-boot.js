(function () {
  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  // If a cached Streamlit DOM is present, route to the app.
  onReady(function () {
    try {
      if (document.querySelector('[data-testid="stApp"]')) {
        location.replace("/app");
        return;
      }
    } catch (e) {}

    var reduced = false;
    try {
      reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) {}

    if (!reduced && "IntersectionObserver" in window) {
      var reveals = document.querySelectorAll(".reveal");
      var observer = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              entry.target.classList.add("visible");
              observer.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
      );
      reveals.forEach(function (el) {
        observer.observe(el);
      });
    } else {
      document.querySelectorAll(".reveal").forEach(function (el) {
        el.classList.add("visible");
      });
    }

    var avatarWrap = document.querySelector(".founder-avatar-wrap");
    if (avatarWrap) {
      avatarWrap.addEventListener("contextmenu", function (e) {
        e.preventDefault();
      });
      avatarWrap.addEventListener("dragstart", function (e) {
        e.preventDefault();
      });
    }

    document.querySelectorAll(".faq-item").forEach(function (item) {
      var btn = item.querySelector(".faq-question");
      if (!btn) return;
      btn.addEventListener("click", function () {
        var isOpen = item.classList.contains("open");
        document.querySelectorAll(".faq-item.open").forEach(function (other) {
          if (other !== item) {
            other.classList.remove("open");
            var ob = other.querySelector(".faq-question");
            if (ob) ob.setAttribute("aria-expanded", "false");
          }
        });
        item.classList.toggle("open", !isOpen);
        btn.setAttribute("aria-expanded", String(!isOpen));
      });
    });

    function goLogin() {
      window.location.href = "/app";
    }

    var btnLogin = document.getElementById("btn-login");
    if (btnLogin) btnLogin.addEventListener("click", goLogin);
    var stickyLogin = document.getElementById("btn-login-sticky");
    if (stickyLogin) stickyLogin.addEventListener("click", goLogin);
    var bgScene = document.querySelector(".bg-scene");
    var contrastTargets = document.querySelectorAll(".faq-contact, footer");
    if (bgScene && contrastTargets.length) {
      var contrastTicking = false;

      function rgbaAlpha(bg) {
        if (!bg || bg === "transparent") return 0;
        var m = bg.match(/rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([\d.]+)\s*\)/);
        return m ? parseFloat(m[1]) : 1;
      }

      function hasOpaqueBg(node) {
        var cur = node;
        while (cur && cur !== document.documentElement) {
          if (cur.nodeType !== 1) {
            cur = cur.parentElement;
            continue;
          }
          var style = window.getComputedStyle(cur);
          if (parseFloat(style.opacity) < 0.05) {
            cur = cur.parentElement;
            continue;
          }
          var bg = style.backgroundColor;
          if (rgbaAlpha(bg) > 0.12) return true;
          cur = cur.parentElement;
        }
        return false;
      }

      function mountainsBehindPoint(x, y, skipRoot) {
        x = Math.max(1, Math.min(x, window.innerWidth - 2));
        y = Math.max(1, Math.min(y, window.innerHeight - 2));
        var stack = document.elementsFromPoint(x, y);
        for (var i = 0; i < stack.length; i++) {
          var node = stack[i];
          if (!node || node.nodeType !== 1) continue;
          if (skipRoot && node.closest && node.closest(".faq-contact, footer") === skipRoot) {
            continue;
          }
          if (node.closest && node.closest(".site-sticky-bar, .modal, .micromodal-slide")) {
            return false;
          }
          if (node.closest && node.closest(".bg-mountains, .bg-scene")) {
            return true;
          }
          if (node.closest && node.closest(".page, main, section, article, .container")) {
            if (hasOpaqueBg(node)) return false;
          }
        }
        return false;
      }

      function inMountainBand(y) {
        var bg = bgScene.getBoundingClientRect();
        var top = bg.top + bg.height * 0.3;
        var bottom = bg.top + bg.height * 0.62;
        return y >= top && y <= bottom;
      }

      function overlapsMountains(el) {
        var rect = el.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > window.innerHeight) return false;
        var samples = [0.35, 0.55, 0.75];
        var hits = 0;
        for (var i = 0; i < samples.length; i++) {
          var y = rect.top + rect.height * samples[i];
          var x = rect.left + rect.width * 0.5;
          if (!inMountainBand(y)) continue;
          if (mountainsBehindPoint(x, y, el)) hits += 1;
        }
        return hits >= 1;
      }

      function updateFooterContrast() {
        contrastTicking = false;
        contrastTargets.forEach(function (el) {
          el.classList.toggle("over-mountains", overlapsMountains(el));
        });
      }

      function scheduleFooterContrast() {
        if (!contrastTicking) {
          contrastTicking = true;
          requestAnimationFrame(updateFooterContrast);
        }
      }

      updateFooterContrast();
      window.addEventListener("scroll", scheduleFooterContrast, { passive: true });
      window.addEventListener("resize", scheduleFooterContrast, { passive: true });
    }

  });
})();
