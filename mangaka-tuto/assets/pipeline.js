/* Carte du pipeline : SVG dessiné depuis TUTO.steps, panneau de détail, navigation au clavier. */
(function () {
  "use strict";
  var D = window.TUTO;
  var T = window.Tuto;
  var esc = T.esc;
  var rich = T.rich;
  var NS = "http://www.w3.org/2000/svg";

  var COL_W = 168;
  var NODE_W = 148;
  var NODE_H = 58;
  var ROW_H = 84;
  var TOP = 56;
  var LEFT = 12;

  var steps = D.steps;
  var phases = D.phases;
  var byId = {};
  steps.forEach(function (s) {
    byId[s.id] = s;
  });

  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }

  // --- Qui fait l'étape : agent LLM (modèle lu dans providers.yaml), flux ComfyUI, vision, code, humain. ---
  function whoHtml(w) {
    var label = w.label || T.WHO_LABELS[w.kind];
    var detail = w.detail ? rich(w.detail) : "";
    if (w.agent) {
      var a = T.agentById(w.agent);
      if (a) {
        label = a.icon + " " + a.name;
        var model = a.llm ? "Modèle par défaut : <code>" + esc(T.modelLabel(a)) + "</code>" : "";
        detail =
          (detail ? detail + "<br>" : "") +
          model +
          (a.llm ? " · " : "") +
          '<a href="equipe.html#agent-' + esc(a.id) + '">fiche de l\'agent</a>';
      }
    }
    if (w.workflows) {
      var wf = w.workflows
        .map(function (id) {
          var f = D.workflows[id];
          if (!f) return "<code>" + esc(id) + "</code>";
          var engine = D.engines[f.engine] || f.engine;
          // Le nom du flux commence souvent par son moteur : inutile de le répéter.
          var suffix = f.name.indexOf(engine) === 0 ? "" : " (" + esc(engine) + ")";
          return "<code>" + esc(id) + "</code> — " + esc(f.name) + suffix;
        })
        .join("<br>");
      detail = (detail ? detail + "<br>" : "") + wf;
    }
    if (w.vision) {
      detail =
        (detail ? detail + "<br>" : "") +
        "Modèle de vision : <code>" + esc(D.providers.visionModel) + "</code> (Ollama, chargé à la demande)";
    }
    return "<li>" + T.whoBadge(w.kind, label) + (detail ? '<div class="small" style="margin-top:4px">' + detail + "</div>" : "") + "</li>";
  }

  function listHtml(items, cls) {
    if (!items || !items.length) return '<p class="empty small">Aucune.</p>';
    return (
      "<ul>" +
      items
        .map(function (i) {
          return "<li" + (cls ? ' class="' + cls + '"' : "") + ">" + rich(i) + "</li>";
        })
        .join("") +
      "</ul>"
    );
  }

  function renderPanel(step) {
    var panel = document.getElementById("panel");
    if (!step) {
      panel.innerHTML =
        '<h2>Choisis une étape</h2><p class="empty">Clique sur une étape de la carte (ou utilise Tab puis Entrée, et les flèches pour passer d\'une étape à l\'autre).</p>' +
        '<section><h3>Lecture de la carte</h3><ul class="small">' +
        "<li>Les colonnes se lisent de gauche à droite, chaque colonne de haut en bas.</li>" +
        "<li>La barre de couleur à gauche d'une étape dit qui la fait (légende au-dessus).</li>" +
        '<li>Un point <span style="color:var(--human)">●</span> signale une porte : garde d\'étapes, validation manuelle ou refus « déjà en cours ».</li>' +
        '<li>Les flèches en pointillés roses sont les passages contrôlés par la garde d\'étapes (<code>stage_gate.py</code>).</li>' +
        "</ul></section>";
      return;
    }
    var phase = phases.filter(function (p) {
      return p.id === step.phase;
    })[0];
    panel.innerHTML =
      '<p class="small muted" style="margin:0 0 4px">' + esc(phase ? phase.label : "") + "</p>" +
      '<h2 id="panel-title" tabindex="-1"><span class="n">' + esc(step.n) + "</span>" + esc(step.title) + "</h2>" +
      "<p>" + rich(step.what) + "</p>" +
      "<section><h3>Qui la fait</h3><ul style=\"list-style:none;padding:0\">" + step.who.map(whoHtml).join("") + "</ul></section>" +
      '<section><h3>Entrées et sorties</h3><div class="io"><div><strong class="small">Entrées</strong>' +
      listHtml(step.inputs) + '</div><div><strong class="small">Sorties</strong>' + listHtml(step.outputs) + "</div></div></section>" +
      "<section><h3>Portes</h3>" + listHtml(step.gates, "gate-item") + "</section>" +
      (step.weak ? "<section><h3>À surveiller</h3>" + listHtml(step.weak) + "</section>" : "") +
      "<section><h3>Fichiers source</h3>" + T.srcList(step.src) + "</section>" + promptLink(step);
  }

  // Lien vers la chaîne des prompts (prompts.html) : l'auteur de prompt de l'étape, ou le graphe entier.
  function promptLink(step) {
    var node = (window.TUTO.stepPrompts || {})[step.id];
    return "<section><h3>Prompts</h3><p class=\"small\">" +
      (node
        ? '<a href="prompts.html#node-' + esc(node) + '">Voir les prompts de cette étape</a> : qui les écrit, leurs variables, leur effet sur l\'image.'
        : 'Aucun prompt à cette étape. <a href="prompts.html#graphe">Voir la chaîne des prompts</a>.') +
      "</p></section>";
  }

  // --- Disposition : une colonne par phase. ---
  var pos = {};
  var maxRows = 0;
  phases.forEach(function (p, ci) {
    var col = steps.filter(function (s) {
      return s.phase === p.id;
    });
    maxRows = Math.max(maxRows, col.length);
    col.forEach(function (s, ri) {
      pos[s.id] = { x: LEFT + ci * COL_W, y: TOP + ri * ROW_H };
    });
  });
  var width = LEFT * 2 + phases.length * COL_W - (COL_W - NODE_W);
  var height = TOP + maxRows * ROW_H + 10;

  var svg = el("svg", {
    viewBox: "0 0 " + width + " " + height,
    role: "group",
    "aria-label": "Carte du pipeline, " + steps.length + " étapes en " + phases.length + " phases",
  });
  var defs = el("defs", {}, svg);
  [["arrow", "#71717a"], ["arrow-gate", "#fda4af"]].forEach(function (m) {
    var mk = el("marker", { id: m[0], viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" }, defs);
    el("path", { d: "M0,0 L10,5 L0,10 z", fill: m[1] }, mk);
  });

  phases.forEach(function (p, ci) {
    var x = LEFT + ci * COL_W - 6;
    el("rect", { class: "phase-bg", x: x, y: 8, width: NODE_W + 12, height: height - 14, rx: 10 }, svg);
    var t = el("text", { class: "phase-label", x: x + 10, y: 30 }, svg);
    t.textContent = p.short;
    var t2 = el("text", { class: "phase-label", x: x + 10, y: 44, style: "text-transform:none;letter-spacing:0;font-size:11px;fill:#71717a" }, svg);
    t2.textContent = p.hint || "";
  });

  // Arêtes : l'ordre du pipeline (étape suivante), plus les liens explicites `next`.
  var edgeLayer = el("g", {}, svg);
  function edge(a, b, gate) {
    var pa = pos[a];
    var pb = pos[b];
    if (!pa || !pb) return;
    var d;
    if (pa.x === pb.x) {
      d = "M" + (pa.x + NODE_W / 2) + "," + (pa.y + NODE_H) + " L" + (pb.x + NODE_W / 2) + "," + (pb.y - 2);
    } else {
      var x1 = pa.x + NODE_W;
      var y1 = pa.y + NODE_H / 2;
      var x2 = pb.x - 2;
      var y2 = pb.y + NODE_H / 2;
      var mx = (x1 + x2) / 2;
      d = "M" + x1 + "," + y1 + " C" + mx + "," + y1 + " " + mx + "," + y2 + " " + x2 + "," + y2;
    }
    el("path", { class: "edge" + (gate ? " gate" : ""), d: d, "marker-end": gate ? "url(#arrow-gate)" : "url(#arrow)" }, edgeLayer);
  }
  steps.forEach(function (s) {
    (s.next || []).forEach(function (n) {
      var target = typeof n === "string" ? n : n.to;
      edge(s.id, target, typeof n === "object" && n.gate);
    });
  });

  var nodes = [];
  steps.forEach(function (s, i) {
    var p = pos[s.id];
    var g = el("g", {
      class: "node",
      tabindex: "0",
      role: "button",
      "aria-label": "Étape " + s.n + " : " + s.title,
      "data-id": s.id,
      transform: "translate(" + p.x + "," + p.y + ")",
    }, svg);
    el("rect", { class: "box", width: NODE_W, height: NODE_H, rx: 8 }, g);
    // Barre « qui » : un segment par famille.
    var kinds = [];
    s.who.forEach(function (w) {
      if (kinds.indexOf(w.kind) < 0) kinds.push(w.kind);
    });
    var segH = (NODE_H - 8) / kinds.length;
    kinds.forEach(function (k, ki) {
      el("rect", { class: "bar", x: 4, y: 4 + ki * segH, width: 4, height: segH - 1, rx: 2, fill: "var(--" + k + ")" }, g);
    });
    var tn = el("text", { class: "n", x: 14, y: 16 }, g);
    tn.textContent = s.n;
    s.short.split("\n").forEach(function (line, li) {
      var t = el("text", { x: 14, y: 33 + li * 15 }, g);
      t.textContent = line;
    });
    if (s.gates && s.gates.length) {
      el("circle", { class: "gate-dot", cx: NODE_W - 10, cy: 10, r: 4 }, g);
    }
    var title = el("title", {}, g);
    title.textContent = s.title;
    nodes.push(g);
  });

  document.getElementById("map").appendChild(svg);

  // --- Liste des étapes (écran étroit) ---
  var list = document.getElementById("step-list");
  var lhtml = "";
  phases.forEach(function (p) {
    lhtml += '<div class="phase">' + esc(p.label) + "</div>";
    steps
      .filter(function (s) {
        return s.phase === p.id;
      })
      .forEach(function (s) {
        lhtml += '<button type="button" data-id="' + esc(s.id) + '" aria-pressed="false"><span class="n">' + esc(s.n) + "</span>" + esc(s.title) + "</button>";
      });
  });
  list.innerHTML = lhtml;

  var current = null;
  function select(id, focusPanel) {
    current = byId[id] || null;
    nodes.forEach(function (n) {
      n.classList.toggle("active", n.getAttribute("data-id") === id);
    });
    Array.prototype.forEach.call(list.querySelectorAll("button"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-id") === id ? "true" : "false");
    });
    renderPanel(current);
    if (current) {
      try {
        history.replaceState(null, "", "#" + id);
      } catch (e) {
        /* file:// sur certains navigateurs : sans importance */
      }
      if (focusPanel) {
        var h = document.getElementById("panel-title");
        if (h) {
          h.focus({ preventScroll: true });
          document.getElementById("panel").scrollIntoView({ behavior: T.reducedMotion() ? "auto" : "smooth", block: "start" });
        }
      }
    }
  }

  nodes.forEach(function (n, i) {
    n.addEventListener("click", function () {
      select(n.getAttribute("data-id"), window.innerWidth <= 1100);
    });
    n.addEventListener("keydown", function (e) {
      var k = e.key;
      if (k === "Enter" || k === " ") {
        e.preventDefault();
        select(n.getAttribute("data-id"), true);
      } else if (k === "ArrowRight" || k === "ArrowDown") {
        e.preventDefault();
        var nx = nodes[Math.min(nodes.length - 1, i + 1)];
        nx.focus();
        select(nx.getAttribute("data-id"));
      } else if (k === "ArrowLeft" || k === "ArrowUp") {
        e.preventDefault();
        var pv = nodes[Math.max(0, i - 1)];
        pv.focus();
        select(pv.getAttribute("data-id"));
      }
    });
  });
  list.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (b) select(b.getAttribute("data-id"), true);
  });

  var hash = (location.hash || "").slice(1);
  select(byId[hash] ? hash : null);
})();
