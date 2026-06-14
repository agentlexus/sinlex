/**
 * Модальное окно с описанием тарифа на лендинге.
 */
(function () {
  "use strict";

  var MODAL_ID = "pricing-modal";
  var OPEN_CLASS = "is-open";

  var TARIFFS = {
    start: {
      name: "Старт",
      amount: "15 000 ₽",
      period: "/ мес",
      summary: "10 расчётов в месяц",
      lead:
        "Для небольшого цеха или пилотного внедрения: быстрые ответы на КП без CAM и Excel.",
      features: [
        "До 10 проектов (расчётов) в месяц",
        "Загрузка CAD и чертежей, базовый ИИ-анализ",
        "Себестоимость: материал, операции, заготовка",
        "Режим «Поток» — пополнение по мере использования",
        "Поддержка по email",
        "1 пользователь в аккаунте",
      ],
    },
    basic: {
      name: "Базовый",
      amount: "40 000 ₽",
      period: "/ мес",
      summary: "30 расчётов в месяц",
      lead:
        "Оптимален для активного отдела с регулярным потоком запросов от заказчиков.",
      features: [
        "До 30 проектов в месяц",
        "Расширенный анализ деталей и операций",
        "Приоритетная обработка в очереди",
        "Несколько пользователей в одной компании",
        "Приоритетная поддержка",
        "Все возможности тарифа «Старт»",
      ],
    },
    enterprise: {
      name: "Предприятие",
      amount: "60 000 ₽",
      period: "/ мес",
      summary: "Безлимитные расчёты",
      lead:
        "Для производства с высокой нагрузкой: без лимита проектов и с максимальным функционалом.",
      features: [
        "Безлимитное число проектов в месяц",
        "Полный функционал Sinlex, включая «Поток»",
        "Персональное сопровождение и настройка",
        "Интеграции и API (по согласованию)",
        "Гибкие условия для команды",
        "Приоритет по всем обращениям",
      ],
    },
  };

  var lastTrigger = null;

  function getModal() {
    return document.getElementById(MODAL_ID);
  }

  function renderBody(key) {
    var t = TARIFFS[key];
    if (!t) return "";
    var items = t.features
      .map(function (f) {
        return "<li>" + f + "</li>";
      })
      .join("");
    return (
      '<p class="pricing-modal__price-line">' +
      '<span class="pricing-modal__amount">' +
      t.amount +
      "</span>" +
      '<span class="pricing-modal__period">' +
      t.period +
      "</span>" +
      "</p>" +
      '<p class="pricing-modal__summary">' +
      t.summary +
      "</p>" +
      '<p class="pricing-modal__lead">' +
      t.lead +
      "</p>" +
      '<ul class="pricing-modal__features">' +
      items +
      "</ul>"
    );
  }

  function openModal(key, trigger) {
    var modal = getModal();
    var t = TARIFFS[key];
    if (!modal || !t) return;
    lastTrigger = trigger || null;
    var titleEl = modal.querySelector("#pricing-modal-title");
    var bodyEl = modal.querySelector("[data-tariff-body]");
    if (titleEl) titleEl.textContent = "Тариф «" + t.name + "»";
    if (bodyEl) bodyEl.innerHTML = renderBody(key);
    modal.classList.add(OPEN_CLASS);
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("pricing-modal-open");
    var closeBtn = modal.querySelector(".pricing-modal__close");
    if (closeBtn) closeBtn.focus();
  }

  function closeModal() {
    var modal = getModal();
    if (!modal) return;
    modal.classList.remove(OPEN_CLASS);
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("pricing-modal-open");
    if (lastTrigger && typeof lastTrigger.focus === "function") {
      lastTrigger.focus();
    }
    lastTrigger = null;
  }

  function onCardActivate(el) {
    var key = el.getAttribute("data-tariff-open");
    if (!key || !TARIFFS[key]) return;
    openModal(key, el);
  }

  function bindCards() {
    document.querySelectorAll("[data-tariff-open]").forEach(function (card) {
      card.addEventListener("click", function () {
        onCardActivate(card);
      });
      card.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onCardActivate(card);
        }
      });
    });
  }

  function bindModal() {
    var modal = getModal();
    if (!modal) return;

    modal.querySelectorAll("[data-tariff-close]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        closeModal();
      });
    });

    modal.addEventListener("click", function (e) {
      if (
        e.target === modal ||
        e.target.classList.contains("pricing-modal__backdrop")
      ) {
        closeModal();
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && modal.classList.contains(OPEN_CLASS)) {
        closeModal();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindCards();
    bindModal();
  });
})();
