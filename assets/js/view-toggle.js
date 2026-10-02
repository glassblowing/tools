// List / grid switch for tool tables. The choice is a per-browser convenience,
// remembered in localStorage and applied in <head> before the page draws.
(function () {
  var root = document.documentElement;
  var buttons = document.querySelectorAll(".view-toggle button");

  function show(view) {
    if (view === "grid") root.dataset.view = "grid";
    else delete root.dataset.view;
    buttons.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.view === view)); });
  }

  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      show(b.dataset.view);
      try { localStorage.setItem("view", b.dataset.view); } catch (e) {}
    });
  });
  show(root.dataset.view === "grid" ? "grid" : "list");
})();
