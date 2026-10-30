(function () {
  "use strict";

  var THEME_KEY = "plataforma-theme";

  function stored() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
    var btn = document.querySelector(".theme-toggle");
    if (btn) {
      // O botão anuncia a ação que vai fazer, não o estado atual. Os ícones
      // (lua/sol) trocam por CSS a partir de data-bs-theme.
      btn.setAttribute("aria-label", theme === "dark" ? "Usar tema claro" : "Usar tema escuro");
    }
    // O cookie deixa o servidor já mandar a página no tema certo, sem piscar.
    document.cookie = "theme=" + theme + "; path=/; max-age=" + 60 * 60 * 24 * 365 + "; SameSite=Lax";
  }

  document.addEventListener("DOMContentLoaded", function () {
    var saved = stored();
    apply(saved === "dark" || saved === "light" ? saved : currentTheme());
    var btn = document.querySelector(".theme-toggle");
    if (btn) {
      btn.addEventListener("click", function () {
        var next = currentTheme() === "dark" ? "light" : "dark";
        try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* sem armazenamento */ }
        apply(next);
      });
    }
  });
})();
