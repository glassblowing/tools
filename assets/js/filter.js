// Client-side filtering for the /tools/ page. State lives in the URL
// (?q=&category=&d=furnace,flameworking) so filtered views can be shared.
(function () {
  var q = document.getElementById("q");
  var category = document.getElementById("category");
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chips input"));
  var cards = Array.prototype.slice.call(document.querySelectorAll("#tool-grid .tool-card"));
  var count = document.getElementById("count");
  var empty = document.getElementById("empty");

  var params = new URLSearchParams(location.search);
  q.value = params.get("q") || "";
  category.value = params.get("category") || "";
  var ds = (params.get("d") || "").split(",").filter(Boolean);
  chips.forEach(function (c) { c.checked = ds.indexOf(c.value) !== -1; });

  function apply() {
    var terms = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    var cat = category.value;
    var disc = chips.filter(function (c) { return c.checked; }).map(function (c) { return c.value; });
    var shown = 0;

    cards.forEach(function (card) {
      var hay = card.dataset.search;
      var cardDisc = card.dataset.disciplines.split(" ");
      var ok = terms.every(function (t) { return hay.indexOf(t) !== -1; }) &&
        (!cat || card.dataset.category === cat) &&
        (disc.length === 0 || disc.some(function (d) { return cardDisc.indexOf(d) !== -1; }));
      card.hidden = !ok;
      if (ok) shown++;
    });

    count.textContent = shown + " of " + cards.length + " tools";
    empty.hidden = shown !== 0;

    var p = new URLSearchParams();
    if (q.value) p.set("q", q.value);
    if (cat) p.set("category", cat);
    if (disc.length) p.set("d", disc.join(","));
    var qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  q.addEventListener("input", apply);
  category.addEventListener("change", apply);
  chips.forEach(function (c) { c.addEventListener("change", apply); });
  apply();
})();
