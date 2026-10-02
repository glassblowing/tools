// Makers map: one pin per town, linking to each maker there.
(function () {
  var el = document.getElementById("maker-map");
  if (!el || !window.L || !window.MAKERS || !window.MAKERS.length) {
    if (el) el.hidden = true;
    return;
  }

  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  var accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#c2571a";

  var map = L.map(el, { scrollWheelZoom: false, worldCopyJump: true });
  // OpenStreetMap's standard tiles (free for light use with attribution), shown in greyscale
  // by CSS to keep the page quiet; inverted in dark mode.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 12,
    className: dark ? "tiles tiles-dark" : "tiles",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  // Makers in the same town share one pin.
  var towns = {};
  window.MAKERS.forEach(function (m) {
    var key = m.lat + "," + m.lng;
    (towns[key] = towns[key] || []).push(m);
  });

  var esc = function (s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  };

  var points = [];
  Object.keys(towns).forEach(function (key) {
    var group = towns[key];
    var latlng = [group[0].lat, group[0].lng];
    points.push(latlng);
    var html = group.map(function (m) {
      return '<a href="' + esc(m.url) + '">' + esc(m.name) + "</a><br><span class=\"muted\">" +
        esc(m.location) + " · " + m.tools + " tool" + (m.tools === 1 ? "" : "s") + "</span>";
    }).join("<hr>");
    L.circleMarker(latlng, {
      radius: group.length > 1 ? 8 : 6, color: accent, weight: 2, fillColor: accent, fillOpacity: 0.85
    }).bindPopup(html).addTo(map);
  });

  map.fitBounds(points, { padding: [30, 30], maxZoom: 6 });
})();
