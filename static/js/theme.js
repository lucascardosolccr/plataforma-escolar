(function () {
  "use strict";

  var THEME_KEY = "plataforma-theme";

  function currentTheme() {
    var stored = localStorage.getItem(THEME_KEY);
    return stored === "dark" ? "dark" : "light";
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
    var btn = document.querySelector(".theme-toggle");
    if (btn) {
      // O botão anuncia a ação que vai fazer, não o estado atual.
      var icon = btn.querySelector(".theme-icon");
      if (icon) {
        icon.textContent = theme === "dark" ? "☀️" : "🌙";
      }
      btn.setAttribute(
        "aria-label",
        theme === "dark" ? "Usar tema claro" : "Usar tema escuro"
      );
    }
    document.cookie = "theme=" + theme + "; path=/; max-age=" + 60 * 60 * 24 * 365;
  }

  document.addEventListener("DOMContentLoaded", function () {
    apply(currentTheme());
    var btn = document.querySelector(".theme-toggle");
    if (btn) {
      btn.addEventListener("click", function () {
        var next = currentTheme() === "dark" ? "light" : "dark";
        localStorage.setItem(THEME_KEY, next);
        apply(next);
      });
    }
  });
})();