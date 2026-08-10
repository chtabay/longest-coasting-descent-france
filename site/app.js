/*
 * Renders the regional results from window.PHASE3, which scripts/phase3_variants.py
 * generates from the engine's own outputs.
 *
 * Nothing numeric is written here. If a figure looks wrong on the page, it is
 * wrong in outputs/phase3/variants.json, and that is the only place to fix it.
 */

(function () {
  "use strict";

  var data = window.PHASE3;
  var root = document.body;

  if (!data || !Array.isArray(data.variants) || data.variants.length === 0) {
    root.innerHTML =
      '<p class="warn">Aucune donnée. Lancer <code>python scripts/phase3_variants.py</code> ' +
      "pour régénérer <code>site/data/phase3.js</code> à partir des sorties du moteur.</p>";
    return;
  }

  var STATUS_LABEL = {
    physical_stop: "PHYSICAL STOP",
    model_gap: "MODEL GAP",
    network_boundary: "NETWORK BOUNDARY",
    budget_limit: "BUDGET LIMIT",
  };

  function text(node, value) {
    node.textContent = value == null ? "" : String(value);
  }

  function el(tag, className, content) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (content != null) node.textContent = String(content);
    return node;
  }

  function badge(status) {
    var node = el("span", "badge " + status, STATUS_LABEL[status] || status);
    return node;
  }

  var GRAPH_LABEL = {
    reconstructed: "graphe courant",
    severed: "graphe périmé",
  };

  function variantName(variant) {
    return (
      (variant.scenario === "paved_reference" ? "Revêtu (référence)" : "VTC (référence)") +
      " · " +
      (variant.allow_cycles ? "répétition autorisée" : "une voie une seule fois")
    );
  }

  function graphTag(variant) {
    var kind = variant.graph || "severed";
    var node = el("span", "graph-tag " + kind, GRAPH_LABEL[kind] || kind);
    node.title = variant.graph_note || "";
    return node;
  }

  /* ---- header ---- */

  text(document.getElementById("question"), data.question);
  text(document.getElementById("phase"), data.phase);
  text(document.getElementById("scope"), data.scope);
  text(document.getElementById("commit"), (data.commit || "").slice(0, 12) || "inconnu");
  text(document.getElementById("v0"), data.initial_speed_km_h);
  text(document.getElementById("method"), data.elevation_method);

  var legend = document.getElementById("legend");
  Object.keys(data.termination_statuses || {}).forEach(function (status) {
    var term = el("dt");
    term.appendChild(badge(status));
    legend.appendChild(term);
    legend.appendChild(el("dd", null, data.termination_statuses[status]));
  });

  /* ---- variant tabs and summary cards ---- */

  var tabs = document.getElementById("variant-tabs");
  var summary = document.getElementById("variant-summary");
  var current = 0;

  data.variants.forEach(function (variant, index) {
    var button = el("button");
    button.type = "button";
    button.setAttribute("role", "tab");
    button.appendChild(document.createTextNode(variantName(variant)));
    var rule = el("span", "rule");
    rule.appendChild(document.createTextNode(variant.leader.distance_label + " "));
    rule.appendChild(graphTag(variant));
    button.appendChild(rule);
    button.addEventListener("click", function () {
      select(index);
    });
    tabs.appendChild(button);
  });

  function renderSummary() {
    summary.innerHTML = "";
    data.variants.forEach(function (variant, index) {
      var card = el("div", "summary-card" + (index === current ? " current" : ""));
      var heading = el("h3");
      heading.appendChild(document.createTextNode(variantName(variant) + " "));
      heading.appendChild(graphTag(variant));
      card.appendChild(heading);
      card.appendChild(el("div", "distance", variant.leader.distance_label));
      card.appendChild(badge(variant.leader.termination_status));
      summary.appendChild(card);
    });
  }

  /* ---- leader ---- */

  var METRICS = [
    ["Durée", function (r) { return r.elapsed_time_s + " s"; }],
    ["Vitesse moyenne", function (r) { return r.mean_speed_km_h + " km/h"; }],
    ["Vitesse maximale", function (r) { return r.max_speed_km_h + " km/h"; }],
    ["Vitesse finale", function (r) { return r.final_speed_km_h + " km/h"; }],
    ["Altitude départ", function (r) { return r.start_elevation_m + " m"; }],
    ["Altitude arrivée", function (r) { return r.end_elevation_m + " m"; }],
    ["Dénivelé net", function (r) { return r.net_dz_m + " m"; }],
    ["Descente cumulée", function (r) { return r.descent_m + " m"; }],
    ["Remontée cumulée", function (r) { return r.ascent_m + " m"; }],
    ["Énergie de freinage", function (r) { return r.braking_energy_kj + " kJ"; }],
    ["Virages contraignants", function (r) { return r.binding_bends; }],
    ["Arêtes parcourues", function (r) { return r.edges_used; }],
    ["Arêtes distinctes", function (r) { return r.distinct_edges; }],
    ["Voies OSM distinctes", function (r) { return r.distinct_osm_ways; }],
    ["Surface taguée", function (r) { return (r.surface_tagged_share * 100).toFixed(1) + " %"; }],
    ["Surface inférée", function (r) { return (r.surface_inferred_share * 100).toFixed(1) + " %"; }],
    ["Redémarrages", function (r) { return r.restart_count; }],
    ["Départ", function (r) { return r.start_lat + ", " + r.start_lon; }],
    ["Arrivée", function (r) { return r.end_lat + ", " + r.end_lon; }],
  ];

  function renderLeader(variant) {
    var host = document.getElementById("leader");
    host.innerHTML = "";
    var leader = variant.leader;

    var headline = el("div", "headline");
    headline.appendChild(el("span", "distance", leader.distance_label));
    headline.appendChild(badge(leader.termination_status));
    headline.appendChild(graphTag(variant));
    host.appendChild(headline);

    host.appendChild(el("p", "detail", leader.termination_detail));
    if (variant.graph_note) {
      host.appendChild(el("p", "detail", "Graphe : " + variant.graph_note));
    }

    var metrics = el("div", "metrics");
    METRICS.forEach(function (pair) {
      var row = el("div", "metric");
      row.appendChild(el("span", null, pair[0]));
      row.appendChild(el("span", null, pair[1](leader)));
      metrics.appendChild(row);
    });
    host.appendChild(metrics);

    if (leader.roads && leader.roads.length) {
      host.appendChild(
        el("p", "roads", "Itinéraire : " + leader.roads.join(" › ") +
          (leader.roads.length >= 12 ? " …" : ""))
      );
    }

    if (leader.repeated_edges && leader.repeated_edges.length) {
      var repeats = el("p", "repeats");
      repeats.appendChild(document.createTextNode("Tronçons répétés : "));
      repeats.appendChild(
        document.createTextNode(
          leader.repeated_edges
            .map(function (item) {
              return (item.name || "voie " + item.osm_way_id) + " ×" + item.traversals;
            })
            .join(", ")
        )
      );
      host.appendChild(repeats);
    }
  }

  /* ---- figures ---- */

  var FIGURES = [
    ["elevation_svg", "Profil d'altitude"],
    ["speed_svg", "Profil de vitesse"],
    ["kinetic_energy_svg", "Énergie cinétique"],
    ["map_svg", "Carte des meilleurs trajets"],
  ];

  function renderFigures(variant) {
    var host = document.getElementById("figures");
    host.innerHTML = "";
    var assets = variant.assets || {};
    FIGURES.forEach(function (pair) {
      if (!assets[pair[0]]) return;
      var figure = el("div", "figure");
      figure.appendChild(el("h3", null, pair[1]));
      var image = document.createElement("img");
      image.alt = pair[1];
      image.loading = "lazy";
      image.src = assets[pair[0]];
      image.addEventListener("error", function () {
        var note = el("p", "missing", "Figure non générée : " + assets[pair[0]]);
        figure.replaceChild(note, image);
      });
      figure.appendChild(image);
      host.appendChild(figure);
    });
    if (!host.children.length) {
      host.appendChild(el("p", "missing", "Aucune figure disponible pour cette variante."));
    }
  }

  /* ---- ranking ---- */

  function renderRanking(variant) {
    var body = document.querySelector("#ranking tbody");
    body.innerHTML = "";
    text(
      document.getElementById("ranking-note"),
      "Top " + variant.ranking_depth + " — " + variantName(variant) +
        ". Source : " + variant.source + "."
    );
    variant.ranking.forEach(function (route, index) {
      var row = document.createElement("tr");
      function cell(value, className) {
        var node = el("td", className || null, value);
        row.appendChild(node);
        return node;
      }
      cell(index + 1);
      cell(route.distance_label, "distance");
      var statusCell = el("td");
      statusCell.appendChild(badge(route.termination_status));
      row.appendChild(statusCell);
      cell(route.elapsed_time_s + " s");
      cell(route.mean_speed_km_h);
      cell(route.max_speed_km_h);
      cell(route.final_speed_km_h);
      cell(route.net_dz_m);
      cell(route.ascent_m);
      cell(route.braking_energy_kj + " kJ");
      cell(route.binding_bends);
      cell(route.edges_used + (route.repeated_traversals ? " (+" + route.repeated_traversals + ")" : ""));
      cell(route.distinct_osm_ways);
      cell((route.surface_inferred_share * 100).toFixed(1) + " %");
      cell((route.roads || []).slice(0, 4).join(" › "));
      body.appendChild(row);
    });
  }

  /* ---- wiring ---- */

  function select(index) {
    current = index;
    var variant = data.variants[index];
    Array.prototype.forEach.call(tabs.children, function (button, position) {
      button.setAttribute("aria-selected", position === index ? "true" : "false");
    });
    renderSummary();
    renderLeader(variant);
    renderFigures(variant);
    renderRanking(variant);
  }

  select(0);
})();
