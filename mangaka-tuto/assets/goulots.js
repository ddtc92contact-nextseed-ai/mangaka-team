/* Goulots et faiblesses : vue mesurée (window.MESURES, écrit par mesurer.py), vue structurelle et faiblesses
 * classées (window.GOULOTS). Graphiques en SVG faits main, textes en HTML pour rester lisibles à 390 px. */
(function () {
  "use strict";
  var D = window.TUTO;
  var G = window.GOULOTS;
  var T = window.Tuto;
  var esc = T.esc;
  var rich = T.rich;

  // ------------------------------------------------------------------ formats
  var nf = typeof Intl !== "undefined" ? new Intl.NumberFormat("fr-FR") : null;
  function n(x) {
    return x == null ? "—" : nf ? nf.format(x) : String(x);
  }
  function ms(x) {
    if (x == null) return "—";
    if (x < 1000) return Math.round(x) + " ms";
    var s = x / 1000;
    if (s < 10) return s.toFixed(1).replace(".", ",") + " s";
    if (s < 60) return Math.round(s) + " s";
    var m = Math.floor(s / 60);
    if (m < 60) {
      var rs = Math.round(s - m * 60);
      return m + " min" + (rs ? " " + (rs < 10 ? "0" : "") + rs + " s" : "");
    }
    var h = Math.floor(m / 60);
    var rm = m - h * 60;
    return h + " h " + (rm < 10 ? "0" : "") + rm;
  }
  function pct(x, digits) {
    if (x == null) return "—";
    return (x * 100).toFixed(digits == null ? 0 : digits).replace(".", ",") + " %";
  }
  function dateFr(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return esc(iso);
    try {
      return d.toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" });
    } catch (e) {
      return d.toISOString();
    }
  }
  function stepById(id) {
    for (var i = 0; i < D.steps.length; i++) if (D.steps[i].id === id) return D.steps[i];
    return null;
  }
  function jobLabel(step) {
    return G.jobLabels[step] || step;
  }
  function srcCite(c) {
    return '<div class="src">' + esc(c.f) + ":" + esc(c.l) + "</div>";
  }

  // ------------------------------------------------------------------ infobulle commune
  var tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "tooltip");
  tip.hidden = true;
  document.body.appendChild(tip);
  function showTip(target, x, y) {
    tip.innerHTML = target.getAttribute("data-tip");
    tip.hidden = false;
    var w = tip.offsetWidth;
    var left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 12));
    tip.style.left = left + "px";
    tip.style.top = y + 14 + "px";
  }
  document.addEventListener("mouseover", function (e) {
    var t = e.target.closest && e.target.closest("[data-tip]");
    if (t) showTip(t, e.clientX, e.clientY);
  });
  document.addEventListener("mousemove", function (e) {
    if (!tip.hidden) {
      var t = e.target.closest && e.target.closest("[data-tip]");
      if (t) showTip(t, e.clientX, e.clientY);
      else tip.hidden = true;
    }
  });
  document.addEventListener("focusin", function (e) {
    var t = e.target.closest && e.target.closest("[data-tip]");
    if (t) {
      var r = t.getBoundingClientRect();
      showTip(t, r.left, r.bottom - 8);
    } else tip.hidden = true;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") tip.hidden = true;
  });
  window.addEventListener("scroll", function () {
    tip.hidden = true;
  }, { passive: true });

  // ------------------------------------------------------------------ bandeau
  function renderBanner(M) {
    var b = document.getElementById("banner");
    var cmd = "python3 mangaka-tuto/mesurer.py &lt;chemin-base&gt;";
    if (!M) {
      b.className = "banner warn";
      b.innerHTML =
        "<strong>Pas encore de mesures.</strong> Le fichier <code>data/mesures.js</code> n'existe pas. Pour le créer, depuis la racine du dépôt : <code>" +
        cmd + "</code>";
      return;
    }
    var parts = [];
    if (M.exemple) parts.push('<strong class="pill">Exemple factice</strong> Ces chiffres viennent d\'une base inventée, pas de ta production.');
    else if (M.vide) parts.push("<strong>Pas encore de données.</strong> " + esc(M.raison));
    parts.push("Mesures du <strong>" + dateFr(M.genere_le) + "</strong>" + (M.base && !M.exemple ? " · base <code>" + esc(M.base) + "</code>" : ""));
    if (M.periode && M.periode.debut) parts.push("Jobs du " + dateFr(M.periode.debut) + " au " + dateFr(M.periode.fin));
    parts.push("Rafraîchir : <code>" + (M.exemple ? cmd : esc(M.commande)) + "</code>");
    b.className = "banner" + (M.exemple || M.vide ? " warn" : "");
    b.innerHTML = parts.join("<br>");
  }

  function renderVide(M) {
    var el = document.getElementById("vide");
    el.hidden = false;
    var why = M ? "<p>" + esc(M.raison) + "</p>" : "<p>Le fichier <code>mangaka-tuto/data/mesures.js</code> n'a pas encore été généré.</p>";
    el.innerHTML =
      '<div class="card empty-state">' +
      "<h3>Pas encore de chiffres</h3>" + why +
      "<p>Lance, depuis la racine du dépôt :</p>" +
      '<pre class="cmd">python3 mangaka-tuto/mesurer.py data/mangaka.db</pre>' +
      '<p class="small muted">Sans chemin, le script prend la base du moteur (<code>MANGAKA_DATA_DIR</code> du <code>.env</code>, sinon <code>data/mangaka.db</code>). ' +
      "Il l'ouvre en lecture seule, n'écrit que <code>mangaka-tuto/data/mesures.js</code>, puis recharge cette page. " +
      "Les chiffres apparaissent dès qu'au moins un job a tourné.</p>" +
      '<p><button type="button" class="btn" id="voir-exemple">Voir l\'exemple factice</button></p>' +
      "</div>";
    document.getElementById("voir-exemple").addEventListener("click", function () {
      var s = document.createElement("script");
      s.src = "data/mesures.exemple.js";
      s.onload = function () {
        render(window.MESURES);
        var h = document.getElementById("h-mesure");
        h.setAttribute("tabindex", "-1");
        h.focus();
      };
      document.body.appendChild(s);
    });
  }

  // ------------------------------------------------------------------ indicateurs
  function renderKpis(M) {
    var exe = 0;
    var att = 0;
    M.etapes.forEach(function (e) {
      exe += e.duree_ms.total || 0;
      att += e.attente_ms.total || 0;
    });
    var g = M.goulot ? jobLabel(M.goulot) : "—";
    var items = [
      ["Jobs mesurés", n(M.totaux.jobs), M.totaux.chapitres + " chapitre(s)"],
      ["Échecs", n(M.totaux.echecs), pct(M.totaux.jobs ? M.totaux.echecs / M.totaux.jobs : null, 1) + " des jobs"],
      ["Temps d'exécution", ms(exe), "cumulé, jobs réussis"],
      ["Attente en file", ms(att), "cumulée, toutes étapes"],
      ["Goulot n°1", esc(g), "plus gros coût en temps"],
    ];
    document.getElementById("kpis").innerHTML = items
      .map(function (k, i) {
        return '<div class="kpi' + (i === 4 ? " top" : "") + '"><div class="k">' + k[0] + '</div><div class="v">' + k[1] + '</div><div class="small muted">' + k[2] + "</div></div>";
      })
      .join("");
  }

  // ------------------------------------------------------------------ carte en heatmap
  var HEAT = ["#3b2417", "#6b3418", "#a2461d", "#d95926", "#f59a6b"];
  var HEAT_INK = ["#e4e4e7", "#e4e4e7", "#fafafa", "#0b0b0b", "#0b0b0b"];

  function stepCosts(M) {
    var by = {};
    function slot(id) {
      return (by[id] = by[id] || { cost: 0, fail: null, jobs: [], logs: [] });
    }
    M.etapes.forEach(function (e) {
      var id = G.jobToStep[e.etape];
      if (!id) return;
      var s = slot(id);
      s.cost += e.cout_ms;
      s.jobs.push(e);
      if (e.taux_echec != null) s.fail = Math.max(s.fail || 0, e.taux_echec);
    });
    ((M.reparations && M.reparations.sortes) || []).forEach(function (k) {
      var id = G.logKindToStep[k.sorte];
      if (!id) return;
      var s = slot(id);
      s.cost += k.duree_ms.total || 0;
      s.logs.push(k);
      if (k.n) s.fail = Math.max(s.fail || 0, k.echecs / k.n);
    });
    return by;
  }

  function heatLevel(cost, max) {
    if (!max || !cost) return -1;
    var r = cost / max;
    return r >= 0.65 ? 4 : r >= 0.35 ? 3 : r >= 0.15 ? 2 : r >= 0.05 ? 1 : 0;
  }

  function renderHeat(M) {
    var costs = stepCosts(M);
    var max = 0;
    Object.keys(costs).forEach(function (k) {
      max = Math.max(max, costs[k].cost);
    });
    var top = M.goulot ? G.jobToStep[M.goulot] : null;
    var NS = "http://www.w3.org/2000/svg";
    var COL_W = 168, NODE_W = 148, NODE_H = 58, ROW_H = 84, TOP = 56, LEFT = 12;
    var pos = {};
    var rows = 0;
    D.phases.forEach(function (p, ci) {
      var col = D.steps.filter(function (s) {
        return s.phase === p.id;
      });
      rows = Math.max(rows, col.length);
      col.forEach(function (s, ri) {
        pos[s.id] = { x: LEFT + ci * COL_W, y: TOP + ri * ROW_H };
      });
    });
    var width = LEFT * 2 + D.phases.length * COL_W - (COL_W - NODE_W);
    var height = TOP + rows * ROW_H + 10;
    var h = '<svg viewBox="0 0 ' + width + " " + height + '" role="group" aria-label="Carte du pipeline colorée par coût en temps">';
    D.phases.forEach(function (p, ci) {
      var x = LEFT + ci * COL_W - 6;
      h += '<rect class="phase-bg" x="' + x + '" y="8" width="' + (NODE_W + 12) + '" height="' + (height - 14) + '" rx="10"></rect>';
      h += '<text class="phase-label" x="' + (x + 10) + '" y="30">' + esc(p.short) + "</text>";
    });
    D.steps.forEach(function (s) {
      var p = pos[s.id];
      var c = costs[s.id];
      var lvl = c ? heatLevel(c.cost, max) : -1;
      var fill = lvl >= 0 ? HEAT[lvl] : "#1f1f23";
      var ink = lvl >= 0 ? HEAT_INK[lvl] : "#71717a";
      var label = "Étape " + s.n + " : " + s.title + (c ? ", coût " + ms(c.cost) : ", pas de job mesuré") + (s.id === top ? ", goulot numéro 1" : "");
      h += '<g class="node hnode' + (s.id === top ? " top" : "") + '" tabindex="0" role="button" data-id="' + esc(s.id) + '" aria-label="' + esc(label) + '" transform="translate(' + p.x + "," + p.y + ')">';
      h += '<rect class="box" width="' + NODE_W + '" height="' + NODE_H + '" rx="8" style="fill:' + fill + '"></rect>';
      h += '<text class="n" x="10" y="16" style="fill:' + ink + '">' + esc(s.n) + "</text>";
      s.short.split("\n").forEach(function (line, li) {
        h += '<text x="10" y="' + (33 + li * 15) + '" style="fill:' + ink + '">' + esc(line) + "</text>";
      });
      if (c && c.fail) {
        h += '<text x="' + (NODE_W - 8) + '" y="16" text-anchor="end" class="fail" style="fill:' + ink + '">⚠ ' + esc(pct(c.fail)) + "</text>";
      }
      if (s.id === top) h += '<text x="' + (NODE_W - 8) + '" y="' + (NODE_H - 6) + '" text-anchor="end" class="badge-top">n°1</text>';
      h += "<title>" + esc(label) + "</title></g>";
    });
    h += "</svg>";
    var map = document.getElementById("heat");
    map.innerHTML = h;
    document.getElementById("heat-scale").innerHTML =
      '<span class="small muted">coût faible</span>' +
      HEAT.map(function (c) {
        return '<i style="background:' + c + '"></i>';
      }).join("") +
      '<span class="small muted">coût fort</span><span class="small muted" style="margin-left:12px"><i style="background:#1f1f23"></i> pas de job</span>';

    var nodes = Array.prototype.slice.call(map.querySelectorAll(".hnode"));
    function select(id) {
      nodes.forEach(function (n2) {
        n2.classList.toggle("active", n2.getAttribute("data-id") === id);
      });
      renderHeatPanel(stepById(id), costs[id], max, id === top);
    }
    nodes.forEach(function (node, i) {
      node.addEventListener("click", function () {
        select(node.getAttribute("data-id"));
      });
      node.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          select(node.getAttribute("data-id"));
        } else if (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === "ArrowLeft" || e.key === "ArrowUp") {
          e.preventDefault();
          var d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1;
          var nx = nodes[Math.max(0, Math.min(nodes.length - 1, i + d))];
          nx.focus();
          select(nx.getAttribute("data-id"));
        }
      });
    });
    select(top || (nodes[0] && nodes[0].getAttribute("data-id")));
  }

  function renderHeatPanel(step, c, max, isTop) {
    var p = document.getElementById("heat-panel");
    if (!step) {
      p.innerHTML = "";
      return;
    }
    var h = '<h2><span class="n">' + esc(step.n) + "</span>" + esc(step.title) + "</h2>";
    if (isTop) h += '<p><span class="pill">Goulot n°1</span> l\'étape qui coûte le plus de temps (exécution + attente).</p>';
    if (!c) {
      h += '<p class="empty">Pas de job pour cette étape : elle est faite par l\'auteur, ou par du code immédiat dans une requête. Son temps se lit dans le « temps humain » des chapitres.</p>';
    } else {
      h += "<p>Coût cumulé : <strong>" + ms(c.cost) + "</strong>" + (max ? " (" + pct(c.cost / max) + " du goulot n°1)" : "") + "</p>";
      c.jobs.forEach(function (e) {
        h += "<section><h3>Job <code>" + esc(e.etape) + "</code> · " + esc(jobLabel(e.etape)) + "</h3><ul class=\"small\">" +
          "<li>" + n(e.jobs) + " jobs, échecs : " + pct(e.taux_echec, 1) + "</li>" +
          (e.etape === "generation" ? '<li class="muted">Un seul type de job pour les cases, croquis, passages au propre et réparations.</li>' : "") +
          "<li>Exécution : médiane " + ms(e.duree_ms.mediane) + ", p90 " + ms(e.duree_ms.p90) + ", max " + ms(e.duree_ms.max) + "</li>" +
          "<li>Attente en file : médiane " + ms(e.attente_ms.mediane) + ", p90 " + ms(e.attente_ms.p90) + (e.file_comfy ? " (file ComfyUI)" : " (pool LLM)") + "</li>" +
          (e.erreurs.length ? "<li>Erreur la plus fréquente : « " + esc(e.erreurs[0].message) + " » (" + e.erreurs[0].n + ")</li>" : "") +
          "</ul></section>";
      });
      c.logs.forEach(function (k) {
        h += "<section><h3>Journal : " + esc(G.logKindLabels[k.sorte] || k.sorte) + "</h3><ul class=\"small\">" +
          "<li>" + n(k.n) + " générations, " + n(k.echecs) + " en échec</li>" +
          "<li>Durée : médiane " + ms(k.duree_ms.mediane) + ", p90 " + ms(k.duree_ms.p90) + "</li>" +
          '<li class="muted">Déjà compté dans le job <code>generation</code> (étape 13) : la table des jobs ne sépare pas les sortes.</li>' +
          "</ul></section>";
      });
    }
    h += '<p class="small" style="margin-top:12px"><a href="pipeline.html#' + esc(step.id) + '">Ce que fait cette étape, sur la carte</a></p>';
    p.innerHTML = h;
  }

  // ------------------------------------------------------------------ durées et attentes (échelle log)
  var TICKS = [
    [10, "10 ms"], [100, "100 ms"], [1000, "1 s"], [10000, "10 s"], [60000, "1 min"],
    [600000, "10 min"], [3600000, "1 h"], [36000000, "10 h"], [360000000, "100 h"],
  ];

  function renderDurees(M) {
    var vals = [];
    M.etapes.forEach(function (e) {
      [e.duree_ms, e.attente_ms].forEach(function (r) {
        if (r.max) vals.push(r.max);
        if (r.mediane) vals.push(r.mediane);
      });
    });
    var el = document.getElementById("chart-durees");
    if (!vals.length) {
      el.innerHTML = '<p class="muted">Aucune durée mesurée.</p>';
      return;
    }
    // Plancher à 100 ms : en dessous, une attente est nulle pour l'auteur (le pool démarre en quelques ms).
    var lo = Math.pow(10, Math.floor(Math.log10(Math.max(100, Math.min.apply(null, vals)))));
    var hi = Math.pow(10, Math.ceil(Math.log10(Math.max.apply(null, vals) * 1.05)));
    var L0 = Math.log10(lo), L1 = Math.log10(hi);
    function x(v) {
      return v == null || v <= 0 ? 0 : Math.max(0, Math.min(100, ((Math.log10(Math.max(v, lo)) - L0) / (L1 - L0)) * 100));
    }
    var ticks = TICKS.filter(function (t) {
      return t[0] >= lo && t[0] <= hi;
    });
    function track(r, cls, what, step) {
      if (!r.n) return '<div class="track none small muted">' + what + " : pas de mesure</div>";
      var tipTxt = "<strong>" + esc(jobLabel(step)) + "</strong> · " + what + "<br>médiane " + ms(r.mediane) + " · p90 " + ms(r.p90) + " · max " + ms(r.max) + "<br>" + n(r.n) + " jobs";
      var grid = ticks.map(function (t) {
        return '<line x1="' + x(t[0]) * 10 + '" x2="' + x(t[0]) * 10 + '" y1="0" y2="20" class="gridline"></line>';
      }).join("");
      return (
        '<svg class="track" viewBox="0 0 1000 20" preserveAspectRatio="none" tabindex="0" role="img" aria-label="' +
        esc(jobLabel(step) + ", " + what + " : médiane " + ms(r.mediane) + ", p90 " + ms(r.p90) + ", max " + ms(r.max)) +
        '" data-tip="' + esc(tipTxt) + '">' + grid +
        '<rect x="0" y="4" width="' + Math.max(2, x(r.mediane) * 10) + '" height="12" rx="3" class="' + cls + '"></rect>' +
        '<line x1="' + x(r.mediane) * 10 + '" x2="' + x(r.p90) * 10 + '" y1="10" y2="10" class="whisker ' + cls + '"></line>' +
        '<line x1="' + x(r.max) * 10 + '" x2="' + x(r.max) * 10 + '" y1="3" y2="17" class="maxtick ' + cls + '"></line>' +
        "</svg>"
      );
    }
    var h = '<div class="bars">';
    M.etapes.forEach(function (e) {
      h += '<div class="bar-row">' +
        '<div class="bar-label"><strong>' + esc(jobLabel(e.etape)) + "</strong>" +
        '<span class="small muted">' + n(e.jobs) + " jobs · " + (e.file_comfy ? "file ComfyUI" : "pool LLM") +
        (e.etape === M.goulot ? ' · <span class="pill">goulot n°1</span>' : "") + "</span></div>" +
        '<div class="bar-tracks">' + track(e.duree_ms, "exe", "exécution", e.etape) + track(e.attente_ms, "att", "attente en file", e.etape) +
        '<div class="bar-values small muted">exéc. ' + ms(e.duree_ms.mediane) + " · attente " + ms(e.attente_ms.mediane) + "</div></div></div>";
    });
    h += '<div class="bar-row axis"><div class="bar-label"></div><div class="bar-tracks axis-ticks">' +
      ticks.map(function (t) {
        return '<span style="left:' + x(t[0]) + '%">' + t[1] + "</span>";
      }).join("") + "</div></div></div>";
    el.innerHTML = h;

    var rows = M.etapes.map(function (e) {
      return "<tr><th scope=\"row\">" + esc(jobLabel(e.etape)) + ' <code class="small">' + esc(e.etape) + "</code></th>" +
        "<td>" + (e.file_comfy ? "ComfyUI" : "pool") + "</td><td>" + n(e.jobs) + "</td><td>" + pct(e.taux_echec, 1) + "</td>" +
        "<td>" + ms(e.duree_ms.mediane) + "</td><td>" + ms(e.duree_ms.p90) + "</td><td>" + ms(e.duree_ms.max) + "</td>" +
        "<td>" + ms(e.attente_ms.mediane) + "</td><td>" + ms(e.attente_ms.p90) + "</td><td>" + pct(e.part_attente) + "</td>" +
        "<td>" + (e.erreurs.length ? e.erreurs.map(function (x2) {
          return esc(x2.message) + " <span class=\"muted\">×" + x2.n + "</span>";
        }).join("<br>") : '<span class="muted">—</span>') + "</td></tr>";
    });
    document.getElementById("table-etapes").innerHTML =
      "<thead><tr><th scope=\"col\">Étape</th><th scope=\"col\">Voie</th><th scope=\"col\">Jobs</th><th scope=\"col\">Échecs</th>" +
      "<th scope=\"col\">Exéc. médiane</th><th scope=\"col\">Exéc. p90</th><th scope=\"col\">Exéc. max</th>" +
      "<th scope=\"col\">Attente médiane</th><th scope=\"col\">Attente p90</th><th scope=\"col\">Part d'attente</th><th scope=\"col\">Erreurs fréquentes</th></tr></thead><tbody>" +
      rows.join("") + "</tbody>";
  }

  // ------------------------------------------------------------------ chapitres
  var CH_SERIES = [
    { key: "generation", label: "Génération", color: "#3987e5" },
    { key: "qc", label: "Contrôle qualité", color: "#199e70" },
    { key: "finishing", label: "Finition", color: "#c98500" },
    { key: "_llm", label: "Écriture (LLM)", color: "#9085e9" },
    { key: "_autres", label: "Autres jobs", color: "#71717a" },
    { key: "_humain", label: "Temps humain présumé", color: "#fda4af" },
  ];
  var LLM_STEPS = ["scenes", "script", "art_direction"];

  function chapterParts(c) {
    var p = { generation: 0, qc: 0, finishing: 0, _llm: 0, _autres: 0, _humain: c.temps_humain_ms || 0 };
    Object.keys(c.temps_machine_ms).forEach(function (k) {
      var v = c.temps_machine_ms[k];
      if (k in p) p[k] += v;
      else if (LLM_STEPS.indexOf(k) >= 0) p._llm += v;
      else p._autres += v;
    });
    return p;
  }

  function renderChapitres(M) {
    var el = document.getElementById("chart-chapitres");
    var tbl = document.getElementById("table-chapitres");
    if (!M.chapitres.length) {
      el.innerHTML = '<p class="muted">Aucun job rattaché à un chapitre.</p>';
      tbl.innerHTML = "";
      return;
    }
    var parts = M.chapitres.map(chapterParts);
    var max = Math.max.apply(null, parts.map(function (p) {
      return CH_SERIES.reduce(function (s, x) {
        return s + p[x.key];
      }, 0);
    })) || 1;
    var h = '<div class="legend">' + CH_SERIES.map(function (s) {
      return '<span class="key"><i style="background:' + s.color + '"></i>' + s.label + "</span>";
    }).join("") + "</div><div class=\"bars\">";
    M.chapitres.forEach(function (c, i) {
      var p = parts[i];
      var total = CH_SERIES.reduce(function (s, x) {
        return s + p[x.key];
      }, 0);
      var x0 = 0;
      var segs = CH_SERIES.map(function (s) {
        var w = (p[s.key] / max) * 1000;
        if (w <= 0) return "";
        var r = '<rect x="' + x0 + '" y="2" width="' + Math.max(1, w - 2) + '" height="22" rx="3" style="fill:' + s.color + '"></rect>';
        x0 += w;
        return r;
      }).join("");
      var name = "Chapitre " + (c.numero == null ? "#" + c.chapitre_id : c.numero) + (c.titre ? " — " + c.titre : "");
      var tipTxt = "<strong>" + esc(name) + "</strong><br>" + CH_SERIES.map(function (s) {
        return p[s.key] ? esc(s.label) + " : " + ms(p[s.key]) : "";
      }).filter(Boolean).join("<br>");
      h += '<div class="bar-row"><div class="bar-label"><strong>' + esc(name) + '</strong><span class="small muted">' + n(c.jobs) + " jobs · " + ms(total) + "</span></div>" +
        '<div class="bar-tracks"><svg class="track tall" viewBox="0 0 1000 26" preserveAspectRatio="none" tabindex="0" role="img" aria-label="' +
        esc(name + " : temps machine " + ms(total - p._humain) + ", temps humain présumé " + ms(p._humain)) + '" data-tip="' + esc(tipTxt) + '">' + segs + "</svg></div></div>";
    });
    el.innerHTML = h + "</div>";
    tbl.innerHTML = "<thead><tr><th scope=\"col\">Chapitre</th><th scope=\"col\">Temps machine par étape</th><th scope=\"col\">Temps humain présumé</th><th scope=\"col\">Absences (&gt; 4 h)</th><th scope=\"col\">Passages les plus longs</th></tr></thead><tbody>" +
      M.chapitres.map(function (c) {
        return "<tr><th scope=\"row\">" + esc(c.numero == null ? "#" + c.chapitre_id : c.numero) + (c.titre ? " · " + esc(c.titre) : "") + "</th><td>" +
          Object.keys(c.temps_machine_ms).map(function (k) {
            return esc(jobLabel(k)) + " : " + ms(c.temps_machine_ms[k]);
          }).join("<br>") + "</td><td>" + ms(c.temps_humain_ms) + "</td><td>" + n(c.absences) + "</td><td>" +
          (c.transitions.length ? c.transitions.slice(0, 3).map(function (t) {
            return esc(t.passage.split(" → ").map(jobLabel).join(" → ")) + " : " + ms(t.mediane_ms);
          }).join("<br>") : '<span class="muted">—</span>') + "</td></tr>";
      }).join("") + "</tbody>";
  }

  // ------------------------------------------------------------------ cases, QC, réparations, signaux
  function renderRegen(M) {
    var c = M.cases;
    var el = document.getElementById("chart-regen");
    if (!c || !c.cases) {
      el.innerHTML = '<p class="muted">Aucune version de case en base.</p>';
      document.getElementById("regen-notes").innerHTML = "";
      return;
    }
    var labels = ["0", "1", "2", "3", "4", "5 et +"];
    var max = Math.max.apply(null, c.histogramme) || 1;
    var bw = 1000 / 6;
    var bars = c.histogramme.map(function (v, i) {
      var hgt = (v / max) * 100;
      return '<g tabindex="0" role="img" aria-label="' + labels[i] + " régénération(s) : " + v + ' case(s)" data-tip="<strong>' + labels[i] + " régénération(s)</strong><br>" + v + ' case(s)">' +
        '<rect x="' + (i * bw + 14) + '" y="' + (110 - hgt) + '" width="' + (bw - 28) + '" height="' + Math.max(hgt, v ? 2 : 0) + '" rx="4" class="exe"></rect>' +
        '<rect x="' + i * bw + '" y="0" width="' + bw + '" height="110" fill="transparent"></rect></g>';
    }).join("");
    el.innerHTML = '<svg class="hist" viewBox="0 0 1000 112" preserveAspectRatio="none">' + bars + '<line x1="0" x2="1000" y1="110.5" y2="110.5" class="gridline"></line></svg>' +
      '<div class="hist-labels">' + c.histogramme.map(function (v, i) {
        return "<span><strong>" + v + "</strong><br>" + labels[i] + "</span>";
      }).join("") + "</div>";
    var r = c.regenerations_par_case;
    document.getElementById("regen-notes").innerHTML =
      "<p>" + n(c.cases) + " cases · médiane <strong>" + n(r.mediane) + "</strong> régénération(s), p90 " + n(r.p90) + ", max " + n(r.max) +
      " · " + n(c.cases_3_regenerations_ou_plus) + " case(s) à 3 ou plus · " + n(c.croquis_presents) + " croquis en base.</p>";
  }

  function renderQc(M) {
    var q = M.qc;
    var el = document.getElementById("chart-qc");
    var STAT = [
      ["rejet", "Rejet", "#f87171"],
      ["a_revoir", "À revoir", "#fbbf24"],
      ["ok", "Ok", "#34d399"],
    ];
    var names = { detectors: "Détecteurs", identity: "Ressemblance", vision: "Vision" };
    if (!q || !q.images_controlees) {
      el.innerHTML = '<p class="muted">Aucune version contrôlée par le QC.</p>';
      document.getElementById("qc-notes").innerHTML = "";
      return;
    }
    var h = '<div class="legend">' + STAT.map(function (s) {
      return '<span class="key"><i style="background:' + s[2] + '"></i>' + s[1] + "</span>";
    }).join("") + '</div><div class="bars">';
    q.couches.forEach(function (c) {
      var ok = c.passees - c.rejet - c.a_revoir;
      var v = { rejet: c.rejet, a_revoir: c.a_revoir, ok: ok };
      var x0 = 0;
      var segs = c.passees ? STAT.map(function (s) {
        var w = (v[s[0]] / c.passees) * 1000;
        if (w <= 0) return "";
        var r = '<rect x="' + x0 + '" y="2" width="' + Math.max(1, w - 2) + '" height="18" rx="3" style="fill:' + s[2] + '"></rect>';
        x0 += w;
        return r;
      }).join("") : "";
      var label = names[c.couche] || c.couche;
      var txt = c.passees
        ? "rejet " + pct(c.taux_rejet) + " · à revoir " + pct(c.taux_a_revoir) + " · " + n(c.passees) + " passage(s)"
        : "jamais passée";
      h += '<div class="bar-row"><div class="bar-label"><strong>' + esc(label) + '</strong><span class="small muted">' + txt +
        (c.sautees ? " · sautée " + n(c.sautees) + " fois" : "") + (c.en_erreur ? " · en erreur " + n(c.en_erreur) : "") +
        (c.indisponibles ? " · indisponible " + n(c.indisponibles) : "") + "</span></div>" +
        '<div class="bar-tracks">' + (c.passees ? '<svg class="track" viewBox="0 0 1000 22" preserveAspectRatio="none" tabindex="0" role="img" aria-label="' + esc(label + " : " + txt) + '" data-tip="' + esc("<strong>" + label + "</strong><br>" + txt + "<br>durée médiane " + ms(c.duree_ms.mediane)) + '">' + segs + "</svg>" : '<div class="track none small muted">pas de passage</div>') + "</div></div>";
    });
    el.innerHTML = h + "</div>";
    document.getElementById("qc-notes").innerHTML = "<p>" + n(q.images_controlees) + " versions contrôlées · verdict final : rejet " + pct(q.taux_rejet) +
      ", à revoir " + pct(q.taux_a_revoir) + " · " + n(q.valides_quand_meme) + " validée(s) quand même par l'auteur.</p>";
  }

  function renderReparations(M) {
    var r = M.reparations;
    var h = "<ul>" +
      "<li><strong>" + n(r.reparations) + "</strong> réparation(s) ciblée(s) sur " + n(r.cases_reparees) + " case(s)" +
      (r.reparations ? " · " + n(r.reparations_statuts.failed || 0) + " en échec · durée médiane " + ms(r.reparations_duree_ms.mediane) : "") + "</li>" +
      "<li>" + n(r.generations_journalisees) + " générations au journal</li></ul>";
    if (r.sortes && r.sortes.length) {
      h += '<div class="table-wrap"><table class="steps"><thead><tr><th scope="col">Sorte</th><th scope="col">Nombre</th><th scope="col">Échecs</th><th scope="col">Médiane</th><th scope="col">p90</th></tr></thead><tbody>' +
        r.sortes.map(function (k) {
          return "<tr><th scope=\"row\">" + esc(G.logKindLabels[k.sorte] || k.sorte) + "</th><td>" + n(k.n) + "</td><td>" + n(k.echecs) + "</td><td>" + ms(k.duree_ms.mediane) + "</td><td>" + ms(k.duree_ms.p90) + "</td></tr>";
        }).join("") + "</tbody></table></div>";
    }
    document.getElementById("reparations").innerHTML = h;
  }

  var SIGNAUX = [
    ["interrompus_redemarrage", "Jobs perdus au redémarrage du moteur"],
    ["llm_sans_reponse", "Agents LLM sans réponse après leurs essais"],
    ["comfy_delai_depasse", "Générations abandonnées au délai"],
    ["comfy_injoignable", "ComfyUI injoignable"],
    ["vision_sautee_comfy_occupe", "Vision sautée : ComfyUI occupé"],
    ["vision_en_erreur", "Vision en erreur (Ollama)"],
    ["relances_auto_qc", "Relances automatiques après un rejet QC"],
    ["jobs_annules", "Jobs annulés"],
  ];
  function renderSignaux(M) {
    var s = M.signaux || {};
    document.getElementById("signaux").innerHTML = '<dl class="signals">' + SIGNAUX.map(function (x) {
      return "<dt>" + x[1] + "</dt><dd" + (s[x[0]] ? ' class="hot"' : "") + ">" + n(s[x[0]]) + "</dd>";
    }).join("") + "</dl>";
  }

  // ------------------------------------------------------------------ vue structurelle
  function renderStructure() {
    document.getElementById("structure-list").innerHTML = G.structure.map(function (b) {
      return '<div class="struct"><h3>' + esc(b.title) + '</h3><p class="muted small">' + esc(b.intro) + '</p><div class="grid cols-2">' +
        b.items.map(function (it) {
          return '<article class="card finding"><h4>' + esc(it.title) + "</h4><p>" + rich(it.text) + "</p>" + it.src.map(srcCite).join("") + "</article>";
        }).join("") + "</div></div>";
    }).join("");
  }

  // ------------------------------------------------------------------ faiblesses classées
  function sumBy(list, f) {
    return list.reduce(function (s, x) {
      return s + (f(x) || 0);
    }, 0);
  }
  function etape(M, id) {
    return M.etapes.filter(function (e) {
      return e.etape === id;
    })[0];
  }
  // Fréquence mesurée : { text, score (0-1, pour le tri) } ; null = pas mesurable avec cette base.
  var MESURES_FAIBLESSES = {
    attente_comfy: function (M) {
      var f = M.etapes.filter(function (e) {
        return e.file_comfy;
      });
      var att = sumBy(f, function (e) {
        return e.attente_ms.total;
      });
      var exe = sumBy(f, function (e) {
        return e.duree_ms.total;
      });
      if (!att && !exe) return null;
      var g = etape(M, "generation");
      return {
        score: att / (att + exe),
        text: pct(att / (att + exe)) + " du temps des jobs de la file passé à attendre" + (g && g.attente_ms.n ? " · attente médiane d'une génération : " + ms(g.attente_ms.mediane) : ""),
      };
    },
    attente_qc: function (M) {
      var q = etape(M, "qc");
      if (!q || !q.attente_ms.n) return null;
      return { score: q.part_attente || 0, text: "attente médiane d'un QC : " + ms(q.attente_ms.mediane) + " (p90 " + ms(q.attente_ms.p90) + ") pour " + ms(q.duree_ms.mediane) + " d'exécution" };
    },
    interrompus_redemarrage: function (M) {
      var k = M.signaux.interrompus_redemarrage;
      return { score: M.totaux.jobs ? k / M.totaux.jobs : 0, text: n(k) + " job(s) perdu(s) sur " + n(M.totaux.jobs) };
    },
    regenerations: function (M) {
      var c = M.cases;
      if (!c || !c.cases) return null;
      return { score: c.cases_3_regenerations_ou_plus / c.cases, text: "médiane " + n(c.regenerations_par_case.mediane) + " par case · " + pct(c.cases_3_regenerations_ou_plus / c.cases) + " des cases à 3 ou plus" };
    },
    vision_sautee: function (M) {
      var v = M.qc.couches.filter(function (c) {
        return c.couche === "vision";
      })[0];
      var k = M.signaux.vision_sautee_comfy_occupe;
      var base = v ? v.passees + v.sautees + v.en_erreur : 0;
      if (!base) return null;
      return { score: k / base, text: n(k) + " fois sur " + n(base) + " contrôles vision (" + pct(k / base) + ")" };
    },
    comfy_delai: function (M) {
      var g = etape(M, "generation");
      var k = M.signaux.comfy_delai_depasse;
      return { score: g && g.jobs ? k / g.jobs : 0, text: n(k) + " génération(s) abandonnée(s)" + (g && g.duree_ms.p90 ? " · p90 d'une génération : " + ms(g.duree_ms.p90) : "") };
    },
    llm_echecs: function (M) {
      var f = M.etapes.filter(function (e) {
        return LLM_STEPS.indexOf(e.etape) >= 0;
      });
      var jobs = sumBy(f, function (e) {
        return e.jobs;
      });
      if (!jobs) return null;
      var k = M.signaux.llm_sans_reponse;
      return { score: k / jobs, text: n(k) + " échec(s) sur " + n(jobs) + " jobs d'écriture (" + pct(k / jobs, 1) + ")" };
    },
    attente_pool: function (M) {
      var f = M.etapes.filter(function (e) {
        return !e.file_comfy && e.attente_ms.n;
      });
      if (!f.length) return null;
      var p90 = Math.max.apply(null, f.map(function (e) {
        return e.attente_ms.p90 || 0;
      }));
      return { score: p90 > 60000 ? 0.5 : 0, text: "attente p90 la plus haute dans le pool : " + ms(p90) };
    },
    temps_humain: function (M) {
      if (!M.chapitres.length) return null;
      var hu = sumBy(M.chapitres, function (c) {
        return c.temps_humain_ms;
      });
      var ma = sumBy(M.chapitres, function (c) {
        return sumBy(Object.keys(c.temps_machine_ms), function (k) {
          return c.temps_machine_ms[k];
        });
      });
      if (!hu && !ma) return null;
      return { score: hu / (hu + ma), text: pct(hu / (hu + ma)) + " du temps actif des chapitres est du temps humain (" + ms(hu) + ")" };
    },
  };

  function renderFaiblesses(M) {
    var ok = M && !M.vide;
    var rows = G.faiblesses.map(function (f) {
      var m = null;
      if (ok && f.mesure && MESURES_FAIBLESSES[f.mesure]) {
        try {
          m = MESURES_FAIBLESSES[f.mesure](M);
        } catch (e) {
          m = null;
        }
      }
      return { f: f, m: m };
    });
    rows.sort(function (a, b) {
      return b.f.impact - a.f.impact || (b.m ? b.m.score : -1) - (a.m ? a.m.score : -1);
    });
    var IMPACT = { 3: "Fort", 2: "Moyen", 1: "Faible" };
    document.getElementById("table-faiblesses").innerHTML =
      "<thead><tr><th scope=\"col\">#</th><th scope=\"col\">Faiblesse</th><th scope=\"col\">Impact</th><th scope=\"col\">Fréquence</th><th scope=\"col\">Cause dans le code</th><th scope=\"col\">Piste</th></tr></thead><tbody>" +
      rows.map(function (r, i) {
        var freq = r.m
          ? esc(r.m.text) + (M.exemple ? ' <span class="pill">factice</span>' : "")
          : '<span class="tag">à mesurer</span>' + ' <span class="small muted">' + (!r.f.mesure ? "pas de trace en base" : M ? "pas encore de données" : "lance mesurer.py") + "</span>";
        return "<tr><td class=\"mono\">" + (i + 1) + "</td><td><strong>" + esc(r.f.title) + "</strong></td>" +
          '<td><span class="impact i' + r.f.impact + '">' + IMPACT[r.f.impact] + "</span></td>" +
          '<td data-label="Fréquence">' + freq + "</td>" +
          '<td data-label="Cause">' + rich(r.f.cause) + r.f.src.map(srcCite).join("") + "</td>" +
          '<td data-label="Piste">' + rich(r.f.piste) + "</td></tr>";
      }).join("") + "</tbody>";
  }

  // ------------------------------------------------------------------ assemblage
  function render(M) {
    renderBanner(M);
    var hasData = M && !M.vide;
    document.getElementById("mesures").hidden = !hasData;
    if (!hasData) {
      renderVide(M);
    } else {
      document.getElementById("vide").hidden = true;
      renderKpis(M);
      renderHeat(M);
      renderDurees(M);
      renderChapitres(M);
      renderRegen(M);
      renderQc(M);
      renderReparations(M);
      renderSignaux(M);
    }
    renderFaiblesses(M);
  }

  renderStructure();
  render(window.MESURES || null);
})();
