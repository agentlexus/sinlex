/**
 * Модальные окна legal на лендинге (политика, условия).
 */
(function () {
  "use strict";

  var MODAL_ID = "legal-modal";
  var OPEN_CLASS = "is-open";

  var DOCS = {
    privacy: {
      title: "Политика конфиденциальности",
      asset: "/assets/legal/privacy.html",
      hashes: ["#privacy", "#legal-privacy"],
      fallback: "/app?legal=privacy",
    },
    terms: {
      title: "Условия использования",
      asset: "/assets/legal/terms.html",
      hashes: ["#terms", "#legal-terms"],
      fallback: "/app?legal=terms",
    },
  };

  var currentDoc = null;
  var loadedDocs = {};

  function getModal() {
    return document.getElementById(MODAL_ID);
  }

  function hashToDoc() {
    var h = (location.hash || "").toLowerCase();
    var key;
    for (key in DOCS) {
      if (DOCS.hasOwnProperty(key) && DOCS[key].hashes.indexOf(h) !== -1) {
        return key;
      }
    }
    return null;
  }

  function clearLegalHash() {
    if (hashToDoc()) {
      history.replaceState(null, "", location.pathname + location.search);
    }
  }

  function loadBody(docKey, done) {
    var modal = getModal();
    var cfg = DOCS[docKey];
    var body = modal && modal.querySelector("[data-legal-body]");
    if (!modal || !body || !cfg) {
      done();
      return;
    }
    if (loadedDocs[docKey]) {
      body.innerHTML = loadedDocs[docKey];
      done();
      return;
    }
    fetch(cfg.asset, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("load failed");
        return r.text();
      })
      .then(function (html) {
        loadedDocs[docKey] = html;
        body.innerHTML = html;
        done();
      })
      .catch(function () {
        body.innerHTML =
          '<p>Не удалось загрузить текст. <a href="' +
          cfg.fallback +
          '">Открыть в приложении</a>.</p>';
        done();
      });
  }

  function openModal(docKey) {
    var modal = getModal();
    var cfg = DOCS[docKey];
    if (!modal || !cfg) return;
    currentDoc = docKey;
    var titleEl = modal.querySelector("#legal-modal-title");
    if (titleEl) titleEl.textContent = cfg.title;
    loadBody(docKey, function () {
      modal.classList.add(OPEN_CLASS);
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("legal-modal-open");
      var closeBtn = modal.querySelector(".legal-modal__close");
      if (closeBtn) closeBtn.focus();
    });
  }

  function closeModal() {
    var modal = getModal();
    if (!modal) return;
    modal.classList.remove(OPEN_CLASS);
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("legal-modal-open");
    currentDoc = null;
    clearLegalHash();
  }

  function bindTriggers() {
    document.querySelectorAll("[data-legal-open]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        var docKey = el.getAttribute("data-legal-open");
        if (!DOCS[docKey]) return;
        e.preventDefault();
        openModal(docKey);
      });
    });
  }

  function bindModal() {
    var modal = getModal();
    if (!modal) return;

    modal.querySelectorAll("[data-legal-close]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        closeModal();
      });
    });

    modal.addEventListener("click", function (e) {
      if (e.target === modal || e.target.classList.contains("legal-modal__backdrop")) {
        closeModal();
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && modal.classList.contains(OPEN_CLASS)) {
        closeModal();
      }
    });
  }

  function maybeOpenFromHash() {
    var docKey = hashToDoc();
    if (docKey) openModal(docKey);
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindTriggers();
    bindModal();
    maybeOpenFromHash();
  });
})();
