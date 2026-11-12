// Light / dark theme. Loaded as a classic script in <head>, before the page paints,
// so a dark page never flashes white. Without a saved choice it follows the system.
(function () {
  var KEY = "citabot-theme";
  var root = document.documentElement;
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  function saved() {
    try {
      var value = localStorage.getItem(KEY);
      return value === "light" || value === "dark" ? value : null;
    } catch (error) {
      return null; // storage blocked (private mode, strict settings)
    }
  }

  function current() {
    return saved() || (media.matches ? "dark" : "light");
  }

  function label(button, theme) {
    var text = theme === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro";
    button.setAttribute("aria-label", text);
    button.title = text;
    button.setAttribute("aria-pressed", String(theme === "dark"));
  }

  function apply(theme) {
    root.dataset.theme = theme;
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < buttons.length; i++) label(buttons[i], theme);
  }

  apply(current());

  // The system setting changed and the person never picked a theme: follow it.
  media.addEventListener("change", function () {
    if (!saved()) apply(current());
  });

  document.addEventListener("DOMContentLoaded", function () {
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].hidden = false;
      buttons[i].addEventListener("click", function () {
        var next = current() === "dark" ? "light" : "dark";
        try {
          localStorage.setItem(KEY, next);
        } catch (error) {
          // Not saved: the choice still lasts until the page is reloaded.
        }
        apply(next);
      });
    }
    apply(current());
  });
})();
