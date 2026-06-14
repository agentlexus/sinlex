(function () {
  "use strict";

  var MODAL_ID = "register-modal";
  var OPEN_CLASS = "is-open";
  var BODY_CLASS = "register-modal-open";
  var API = "/api/auth";
  var MIN_PASSWORD = 8;
  var codeSent = false;

  function modalEl() {
    return document.getElementById(MODAL_ID);
  }

  function isOpen() {
    var m = modalEl();
    return !!(m && m.classList.contains(OPEN_CLASS));
  }

  function submitBtn() {
    return document.querySelector("[data-register-submit]");
  }

  function resetCodeStep() {
    codeSent = false;
    var wrap = document.getElementById("reg-code-wrap");
    var code = document.getElementById("reg-code");
    if (wrap) wrap.hidden = true;
    if (code) code.value = "";
    var btn = submitBtn();
    if (btn) btn.textContent = "Получить код";
  }

  function showCodeStep() {
    codeSent = true;
    var wrap = document.getElementById("reg-code-wrap");
    if (wrap) wrap.hidden = false;
    var code = document.getElementById("reg-code");
    if (code && code.focus) code.focus();
    var btn = submitBtn();
    if (btn) btn.textContent = "Подтвердить";
  }

  function clearFormState() {
    ["reg-first", "reg-last", "reg-email", "reg-company", "reg-phone", "reg-password", "reg-password2", "reg-code"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.classList.remove("reg-input--bad");
      if (id !== "reg-code") el.value = "";
    });
    resetCodeStep();
    setMsg("");
  }

  function focusFirstField() {
    var m = modalEl();
    if (!m) return;
    var first = m.querySelector("#reg-first, input, button");
    if (first && first.focus) first.focus();
  }

  function openModalFallback() {
    var m = modalEl();
    if (!m || isOpen()) return;
    clearFormState();
    m.setAttribute("aria-hidden", "false");
    m.classList.remove("is-closing");
    m.classList.add(OPEN_CLASS);
    document.body.classList.add(BODY_CLASS);
    focusFirstField();
  }

  function closeModalFallback() {
    var m = modalEl();
    if (!m || !isOpen()) return;
    m.setAttribute("aria-hidden", "true");
    m.classList.remove(OPEN_CLASS, "is-closing");
    document.body.classList.remove(BODY_CLASS);
    resetCodeStep();
  }

  function setMsg(text, isError) {
    var el = document.getElementById("reg-msg");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("reg-msg--visible", !!text);
    el.classList.toggle("reg-msg--error", !!isError);
  }

  function val(id) {
    var el = document.getElementById(id);
    return (el && el.value ? String(el.value) : "").trim();
  }

  function validatePassword() {
    var p1 = document.getElementById("reg-password");
    var p2 = document.getElementById("reg-password2");
    var pass = val("reg-password");
    var pass2 = val("reg-password2");
    var ok = true;

    if (p1) p1.classList.toggle("reg-input--bad", pass.length < MIN_PASSWORD);
    if (p2) p2.classList.toggle("reg-input--bad", pass2 !== pass || pass2.length < MIN_PASSWORD);

    if (pass.length < MIN_PASSWORD) {
      setMsg("Пароль не менее " + MIN_PASSWORD + " символов.", true);
      return false;
    }
    if (pass !== pass2) {
      setMsg("Пароли не совпадают.", true);
      return false;
    }
    return ok;
  }

  function validateBase() {
    var ok = true;
    ["reg-first", "reg-last", "reg-email", "reg-company", "reg-phone", "reg-password", "reg-password2"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      var v = val(id);
      el.classList.toggle("reg-input--bad", !v);
      ok = ok && !!v;
    });
    if (!ok) return false;
    return validatePassword();
  }

  function payload() {
    return {
      email: val("reg-email"),
      first_name: val("reg-first"),
      last_name: val("reg-last"),
      company_name: val("reg-company"),
      phone: val("reg-phone"),
      password: val("reg-password"),
    };
  }

  function apiPost(path, body) {
    return fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    }).then(function (res) {
      return res.json().catch(function () {
        return {};
      }).then(function (data) {
        if (!res.ok) {
          var detail = data && data.detail;
          if (Array.isArray(detail) && detail[0] && detail[0].msg) {
            detail = detail[0].msg;
          }
          var err = new Error(detail || "Ошибка запроса");
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }

  function setLoading(loading) {
    var btn = submitBtn();
    if (!btn) return;
    btn.disabled = !!loading;
  }

  function bindOpenTriggers(openFn) {
    document.querySelectorAll("[data-register-open]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        if (isOpen()) return;
        openFn();
      });
    });
  }

  function initMicroModal() {
    if (!window.MicroModal) return false;

    try {
      window.MicroModal.init({
        openTrigger: "data-micromodal-trigger",
        disableScroll: false,
        awaitOpenAnimation: true,
        awaitCloseAnimation: true,
        onShow: function () {
          clearFormState();
          focusFirstField();
          document.body.classList.add(BODY_CLASS);
        },
        onClose: function () {
          document.body.classList.remove(BODY_CLASS);
          resetCodeStep();
        },
      });
    } catch (e) {
      return false;
    }

    bindOpenTriggers(function () {
      window.MicroModal.show(MODAL_ID);
    });

    return true;
  }

  function initFallback() {
    bindOpenTriggers(openModalFallback);

    var m = modalEl();
    if (!m) return;

    m.querySelectorAll("[data-micromodal-close]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        closeModalFallback();
      });
    });

    var overlay = m.querySelector(".modal__overlay");
    if (overlay) {
      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) closeModalFallback();
      });
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && isOpen()) closeModalFallback();
    });
  }

  function bindSubmit() {
    var btn = submitBtn();
    if (!btn) return;

    btn.addEventListener("click", function () {
      setMsg("");

      if (!codeSent) {
        if (!validateBase()) {
          if (!document.getElementById("reg-msg").textContent) {
            setMsg("Заполните все поля.", true);
          }
          return;
        }
        setLoading(true);
        var startBody = payload();
        delete startBody.password;
        apiPost("/register-code/start", startBody)
          .then(function () {
            showCodeStep();
            setMsg("Код отправлен на " + val("reg-email") + ". Проверьте почту (и папку «Спам»).");
          })
          .catch(function (err) {
            if (err.status === 500) {
              setMsg("Не удалось отправить письмо. Попробуйте позже.", true);
            } else {
              setMsg(err.message || "Ошибка отправки.", true);
            }
          })
          .finally(function () {
            setLoading(false);
          });
        return;
      }

      var code = val("reg-code");
      var codeEl = document.getElementById("reg-code");
      if (!code || code.length < 4) {
        if (codeEl) codeEl.classList.add("reg-input--bad");
        setMsg("Введите код из письма.", true);
        return;
      }
      if (!validatePassword()) {
        return;
      }

      setLoading(true);
      var body = payload();
      body.code = code;
      apiPost("/register-code/confirm", body)
        .then(function (data) {
          setMsg("Регистрация успешна. Переходим в приложение…");
          window.location.href = (data && data.redirect) || "/app/";
        })
        .catch(function (err) {
          if (err.status === 400) {
            var msg = err.message || "";
            if (msg.indexOf("Пароль") >= 0) {
              setMsg(msg, true);
            } else {
              setMsg("Неверный или просроченный код.", true);
            }
          } else if (err.status === 429) {
            setMsg("Слишком много попыток. Запросите код заново.", true);
            resetCodeStep();
          } else if (err.status === 500) {
            setMsg("Ошибка сервера. Если аккаунт уже создан — откройте /app/ и войдите.", true);
          } else {
            setMsg(err.message || "Ошибка подтверждения.", true);
          }
        })
        .finally(function () {
          setLoading(false);
        });
    });
  }

  function boot() {
    if (!initMicroModal()) {
      initFallback();
    }
    bindSubmit();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
