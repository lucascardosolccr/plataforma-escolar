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
      btn.innerHTML = theme === "dark" ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-fill"></i>';
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