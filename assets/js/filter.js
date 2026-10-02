// Client-side filtering for the /tools/ page. State lives in the URL
// (?q=&category=&maker=) so filtered views can be shared.
(function () {
  var q = document.getElementById("q");
  var category = document.getElementById("category");
  var maker = document.getElementById("maker");
  var rows = Array.prototype.slice.call(document.querySelectorAll("#tool-table .tool-row"));
  var count = document.getElementById("count");
  var empty = document.getElementById("empty");

  var params = new URLSearchParams(location.search);
  q.value = params.get("q") || "";
  category.value = params.get("category") || "";
  maker.value = params.get("maker") || "";

  function apply() {
    var terms = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    rows.forEach(function (row) {
      var hay = row.dataset.search;
      var ok = terms.every(function (t) { return hay.indexOf(t) !== -1; }) &&
        (!category.value || row.dataset.category === category.value) &&
        (!maker.value || row.dataset.maker === maker.value);
      row.hidden = !ok;
      if (ok) shown++;
    });
    count.textContent = shown === rows.length ? rows.length : shown + " of " + rows.length;
    empty.hidden = shown !== 0;

    var p = new URLSearchParams();
    if (q.value) p.set("q", q.value);
    if (category.value) p.set("category", category.value);
    if (maker.value) p.set("maker", maker.value);
    var qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  q.addEventListener("input", apply);
  category.addEventListener("change", apply);
  maker.addEventListener("change", apply);
  apply();
})();
