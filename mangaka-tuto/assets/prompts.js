/* La chaîne des prompts : graphe, fiches, traçage d'un prompt de case et constats.
   Données : prompts-gabarits.js (relevé automatique des presets) et prompts-data.js (annotations). */
(function () {
  "use strict";

  var T = window.Tuto;
  var G = window.TUTO_GABARITS;
  var D = window.TUTO_PROMPTS;
  var esc = T.esc;
  var rich = T.rich;

  var NODES = {};
  D.nodes.forEach(function (n) { NODES[n.id] = n; });
  var FICHES = {};
  D.fiches.forEach(function (f) { FICHES[f.id] = f; });
  var SOURCES = {};
  D.sources.forEach(function (s) { SOURCES[s.id] = s; });
  var DEST = {};
  D.destinations.forEach(function (d) { DEST[d.id] = d; });

  function agentOf(id) {
    for (var i = 0; i < G.agents.length; i++) if (G.agents[i].id === id) return G.agents[i];
    return null;
  }

  // « fichier:ligne » cité, en lien lisible (pas de lien réel : le tuto s'ouvre sans le dépôt).
  function srcHtml(list) {
    return (list || []).map(function (s) { return '<div class="src">' + esc(s) + "</div>"; }).join("");
  }

  function modelHtml(agentId) {
    var a = agentOf(agentId);
    if (!a) return "";
    if (!a.llm) {
      if (a.providers.indexOf("vision") >= 0) {
        return "Vision : <code>" + esc(G.providers.visionModel) + "</code> via Ollama";
      }
      return "Aucun modèle de langage";
    }
    var m = G.providers.defaultModel;
    var cls = G.providers.models[m] ? "classe raisonnement" : "classe rapide";
    return "<code>" + esc(m) + "</code> par défaut (" + cls + "), réglable par agent dans « L'équipe »";
  }

  /* ------------------------------------------------------------------ 1. graphe */
  var activeNode = null;

  function nodeLines(label) { return String(label).split("\n"); }

  function edgePath(a, b) {
    var W = D.graph.nodeW, H = D.graph.nodeH;
    var x1, y1, x2, y2;
    if (Math.abs(a.x - b.x) > W) {
      x1 = a.x + (b.x > a.x ? W : 0); y1 = a.y + H / 2;
      x2 = b.x + (b.x > a.x ? 0 : W); y2 = b.y + H / 2;
      var mx = (x1 + x2) / 2;
      // Flèche droite entre deux colonnes voisines : l'étiquette passe au-dessus des nœuds, pas sur eux.
      var flat = Math.abs(y1 - y2) < 4;
      return { d: "M" + x1 + "," + y1 + " C" + mx + "," + y1 + " " + mx + "," + y2 + " " + x2 + "," + y2, lx: mx, ly: flat ? Math.min(a.y, b.y) - 2 : (y1 + y2) / 2 };
    }
    x1 = a.x + W / 2; y1 = a.y + (b.y > a.y ? H : 0);
    x2 = b.x + W / 2; y2 = b.y + (b.y > a.y ? 0 : H);
    var my = (y1 + y2) / 2;
    return { d: "M" + x1 + "," + y1 + " C" + x1 + "," + my + " " + x2 + "," + my + " " + x2 + "," + y2, lx: (x1 + x2) / 2, ly: my };
  }

  function renderGraph() {
    var g = D.graph, W = g.nodeW, H = g.nodeH;
    var s = '<svg viewBox="0 0 ' + g.width + " " + g.height + '" role="group" aria-label="Graphe de la chaîne des prompts">';
    s += '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">' +
      '<path d="M0,0 L10,5 L0,10 z" fill="#71717a"/></marker>' +
      '<marker id="arrow-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">' +
      '<path d="M0,0 L10,5 L0,10 z" fill="#fb7185"/></marker></defs>';
    g.lanes.forEach(function (l) {
      s += '<text class="phase-label" x="' + l.x + '" y="' + l.y + '">' + esc(l.label) + "</text>";
    });
    D.edges.forEach(function (e, i) {
      var p = edgePath(NODES[e.from], NODES[e.to]);
      s += '<path class="edge chain-edge' + (e.main ? " main" : "") + '" data-edge="' + i + '" d="' + p.d + '" marker-end="url(#arrow)"/>';
    });
    D.edges.forEach(function (e, i) {
      var p = edgePath(NODES[e.from], NODES[e.to]);
      s += '<text class="edge-label' + (e.main && !e.quiet ? " main" : "") + '" data-edge-label="' + i + '" x="' + p.lx + '" y="' + (p.ly - 4) + '" text-anchor="middle">' + esc(e.label) + "</text>";
    });
    D.nodes.forEach(function (n) {
      var lines = nodeLines(n.label);
      s += '<g class="node k-' + esc(n.kind) + '" tabindex="0" role="button" data-node="' + esc(n.id) + '" aria-label="' +
        esc(lines.join(" ") + " — " + T.WHO_LABELS[n.kind]) + '" transform="translate(' + n.x + "," + n.y + ')">' +
        '<rect class="box" width="' + W + '" height="' + H + '" rx="9"/>' +
        '<rect class="bar" width="5" height="' + H + '" rx="2" fill="var(--' + esc(n.kind) + ')"/>';
      var y0 = H / 2 - (lines.length - 1) * 8 + 4;
      lines.forEach(function (line, k) {
        s += '<text x="14" y="' + (y0 + k * 16) + '">' + esc(line) + "</text>";
      });
      s += "</g>";
    });
    s += "</svg>";
    var map = document.getElementById("chain-map");
    map.innerHTML = s;
    map.addEventListener("click", function (ev) {
      var el = ev.target.closest("[data-node]");
      if (el) selectNode(el.getAttribute("data-node"));
    });
    map.addEventListener("keydown", function (ev) {
      var el = ev.target.closest("[data-node]");
      if (!el) return;
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selectNode(el.getAttribute("data-node")); }
      if (ev.key === "ArrowRight" || ev.key === "ArrowDown" || ev.key === "ArrowLeft" || ev.key === "ArrowUp") {
        ev.preventDefault();
        var ids = D.nodes.map(function (n) { return n.id; });
        var i = ids.indexOf(el.getAttribute("data-node"));
        var next = ids[(i + (ev.key === "ArrowRight" || ev.key === "ArrowDown" ? 1 : ids.length - 1)) % ids.length];
        map.querySelector('[data-node="' + next + '"]').focus();
      }
    });

    // Liste de repli (écrans étroits) : même contenu, au doigt.
    var lhtml = "";
    g.lanes.forEach(function (l) {
      lhtml += '<div class="phase">' + esc(l.label) + "</div>";
      D.nodes.filter(function (n) { return n.lane === l.id; }).sort(function (a, b) { return a.y - b.y; }).forEach(function (n) {
        lhtml += '<button type="button" data-node="' + esc(n.id) + '" aria-pressed="false"><span class="dot k-' + esc(n.kind) + '"></span>' +
          esc(nodeLines(n.label).join(" ")) + "</button>";
      });
    });
    var list = document.getElementById("chain-list");
    list.innerHTML = lhtml;
    list.addEventListener("click", function (ev) {
      var el = ev.target.closest("[data-node]");
      if (el) selectNode(el.getAttribute("data-node"));
    });

    var legend = ["human", "llm", "code", "comfy", "vision"].map(function (k) { return T.whoBadge(k); }).join("");
    document.getElementById("graph-legend").innerHTML = legend;
    document.getElementById("graph-intro").innerHTML = rich(D.graph.intro);
    renderNodePanel(null);
  }

  function edgeItem(e, dir) {
    var other = NODES[dir === "in" ? e.from : e.to];
    return '<li><button class="linkish" type="button" data-goto-node="' + esc(other.id) + '">' +
      esc(nodeLines(other.label).join(" ")) + "</button> — " + rich(e.label) + (e.note ? '<div class="muted small">' + rich(e.note) + "</div>" : "") + "</li>";
  }

  function renderNodePanel(id) {
    var panel = document.getElementById("node-panel");
    if (!id) {
      panel.innerHTML = '<h2>Choisis un auteur</h2><p class="empty">Clique un nœud (ou Tab puis Entrée) : tu verras son modèle, ce qu\'il reçoit, ce qu\'il transmet, et ses fiches de prompt.</p>' +
        '<section><h3>Lecture du graphe</h3><ul class="small">' + D.graph.reading.map(function (r) { return "<li>" + rich(r) + "</li>"; }).join("") + "</ul></section>" +
        '<section><h3>Agents sans prompt</h3><ul class="small">' + D.agentsWithoutPrompt.map(function (a) {
          var ag = agentOf(a.id);
          return "<li><strong>" + esc(ag ? ag.icon + " " + ag.name : a.id) + "</strong> : " + rich(a.why) + srcHtml(a.src) + "</li>";
        }).join("") + "</ul></section>";
      return;
    }
    var n = NODES[id];
    var ins = D.edges.filter(function (e) { return e.to === id; });
    var outs = D.edges.filter(function (e) { return e.from === id; });
    var html = "<h2>" + esc(nodeLines(n.label).join(" ")) + "</h2>" + '<p style="margin:4px 0 10px">' + T.whoBadge(n.kind) + "</p>" +
      "<p>" + rich(n.desc) + "</p>";
    if (n.agent) html += '<section><h3>Agent et modèle</h3><p class="small"><code>presets/agents/' + esc(n.agent) + ".yaml</code><br>" + modelHtml(n.agent) + "</p></section>";
    if (ins.length) html += '<section><h3>Reçoit</h3><ul class="small">' + ins.map(function (e) { return edgeItem(e, "in"); }).join("") + "</ul></section>";
    if (outs.length) html += '<section><h3>Transmet</h3><ul class="small">' + outs.map(function (e) { return edgeItem(e, "out"); }).join("") + "</ul></section>";
    if (n.fiches && n.fiches.length) {
      html += '<section><h3>Fiches</h3><div class="chips">' + n.fiches.map(function (f) {
        return '<button class="btn" type="button" data-goto-fiche="' + esc(f) + '">' + esc(FICHES[f].title) + "</button>";
      }).join("") + "</div></section>";
    }
    html += "<section><h3>Fichiers source</h3>" + srcHtml(n.src) + "</section>";
    panel.innerHTML = html;
  }

  function selectNode(id, scroll) {
    activeNode = id;
    document.querySelectorAll("#chain-map [data-node]").forEach(function (el) {
      el.classList.toggle("active", el.getAttribute("data-node") === id);
    });
    document.querySelectorAll("#chain-list [data-node]").forEach(function (el) {
      el.setAttribute("aria-pressed", el.getAttribute("data-node") === id ? "true" : "false");
    });
    D.edges.forEach(function (e, i) {
      var on = e.from === id || e.to === id;
      var path = document.querySelector('[data-edge="' + i + '"]');
      var label = document.querySelector('[data-edge-label="' + i + '"]');
      if (path) { path.classList.toggle("on", on); path.setAttribute("marker-end", on ? "url(#arrow-on)" : "url(#arrow)"); }
      if (label) label.classList.toggle("on", on);
    });
    renderNodePanel(id);
    var panel = document.getElementById("node-panel");
    var r = panel.getBoundingClientRect();
    if (!scroll && (r.top > window.innerHeight - 80 || r.bottom < 0)) panel.scrollIntoView({ behavior: T.reducedMotion() ? "auto" : "smooth", block: "nearest" });
    if (location.hash !== "#node-" + id) history.replaceState(null, "", "#node-" + id);
    if (scroll) document.getElementById("graphe").scrollIntoView({ behavior: T.reducedMotion() ? "auto" : "smooth" });
  }

  /* ------------------------------------------------------------------ 2. fiches */
  var activeFiche = null;

  function markVars(text) {
    return esc(text).replace(/\$(\w+)/g, '<mark class="var">$$$1</mark>');
  }

  function partLabel(key) {
    return { system: "Consignes système", user: "Message utilisateur (gabarit)", retry: "Relance après une réponse invalide" }[key] || key;
  }

  function declaredFor(fiche) {
    // Variables déclarées par l'agent (presets/agents/*.yaml) pour ce gabarit : réglage dont la source le désigne.
    var a = agentOf(fiche.agent);
    var out = {};
    if (!a || !fiche.gabarit) return out;
    a.settings.forEach(function (s) {
      if (s.source.indexOf("prompts/" + fiche.gabarit + ".yaml#") === 0) {
        s.variables.forEach(function (v) { (out[v] = out[v] || []).push(s.source.split("#")[1]); });
      }
    });
    return out;
  }

  function varsTable(fiche, used) {
    var declared = declaredFor(fiche);
    var names = [];
    Object.keys(fiche.vars || {}).forEach(function (v) { if (names.indexOf(v) < 0) names.push(v); });
    Object.keys(used).forEach(function (v) { if (names.indexOf(v) < 0) names.push(v); });
    Object.keys(declared).forEach(function (v) { if (names.indexOf(v) < 0) names.push(v); });
    if (!names.length) return '<p class="muted small">Aucune variable.</p>';
    var rows = names.map(function (v) {
      var info = (fiche.vars || {})[v] || D.commonVars[v] || {};
      var flags = [];
      if (fiche.gabarit && declared[v] && !used[v]) flags.push('<span class="flag warn">déclarée, absente du gabarit</span>');
      if (fiche.gabarit && used[v] && !declared[v] && Object.keys(declared).length) flags.push('<span class="flag warn">utilisée, non déclarée</span>');
      if (info.empty) flags.push('<span class="flag">' + rich(info.empty) + "</span>");
      if (info.verify) flags.push('<span class="flag verify">à vérifier</span>');
      var where = used[v] ? used[v].map(partLabel).join(", ") : "—";
      return "<tr><td><code>$" + esc(v) + "</code></td><td>" + (info.from ? rich(info.from) : '<span class="muted">non documentée</span>') +
        (info.src ? srcHtml([].concat(info.src)) : "") + flags.join(" ") + '</td><td class="small">' + esc(where) + "</td></tr>";
    }).join("");
    return '<div class="table-wrap"><table class="steps stack vars"><thead><tr><th>Variable</th><th>D\'où vient la valeur</th><th>Utilisée dans</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
  }

  function gabaritParts(fiche) {
    if (fiche.gabarit) {
      var p = G.prompts[fiche.gabarit];
      return p.parts.map(function (part) { return { label: partLabel(part.key), key: part.key, src: p.file + ":" + part.line, text: part.text, used: part.used }; });
    }
    if (fiche.special === "image_parts") {
      var ip = G.imagePrompt;
      return [{ label: "Morceaux du prompt par fragments (un par ligne)", key: "parts", src: ip.file + ":" + ip.parts[0].line,
        text: ip.parts.map(function (x) { return x.text; }).join("\n"), used: [].concat.apply([], ip.parts.map(function (x) { return x.used; })) }];
    }
    if (fiche.special === "qc") {
      return [{ label: "Consigne envoyée avec l'image", key: "prompt", src: G.qcVision.file + ":" + G.qcVision.line, text: G.qcVision.text, used: G.qcVision.used }];
    }
    return [];
  }

  function renderFiche(id, focus) {
    var f = FICHES[id];
    activeFiche = id;
    document.querySelectorAll("#fiche-picker [data-fiche]").forEach(function (b) {
      var on = b.getAttribute("data-fiche") === id;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.setAttribute("tabindex", on ? "0" : "-1");
    });
    var parts = gabaritParts(f);
    var used = {};
    parts.forEach(function (p) { p.used.forEach(function (v) { (used[v] = used[v] || []).push(p.key); }); });
    var p = f.gabarit ? G.prompts[f.gabarit] : null;
    var kv = [];
    kv.push(["Auteur", (f.agent ? "Agent <code>" + esc(f.agent) + "</code> — " : "") + rich(f.author)]);
    if (f.agent) kv.push(["Modèle", modelHtml(f.agent)]);
    if (p) {
      kv.push(["Température", p.temperature == null ? rich(f.temperatureNote || "non fixée dans ce gabarit") : String(p.temperature).replace(".", ",") +
        ' <span class="src inline">' + esc(p.file + ":" + p.temperatureLine) + "</span>"]);
      kv.push(["Tentatives", p.maxRetries == null ? rich(f.retriesNote || "non fixées dans ce gabarit") : (1 + p.maxRetries) + " au plus (1 + <code>max_retries: " + p.maxRetries + "</code>)" +
        ' <span class="src inline">' + esc(p.file + ":" + p.maxRetriesLine) + "</span>"]);
      var extra = Object.keys(p.extra).map(function (k) { return "<code>" + esc(k) + ": " + esc(JSON.stringify(p.extra[k])) + "</code>"; });
      if (extra.length) kv.push(["Réglages", extra.join(" ")]);
    }
    kv.push(["Appelé par", srcHtml(f.calledBy)]);

    var html = '<header class="fiche-head"><h3>' + esc(f.title) + "</h3>" + T.whoBadge(f.kind) +
      (f.node ? ' <button class="linkish small" type="button" data-goto-node="' + esc(f.node) + '">voir dans le graphe</button>' : "") + "</header>" +
      "<p>" + rich(f.role) + "</p>" +
      '<dl class="kv">' + kv.map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>"; }).join("") + "</dl>";

    html += "<h4>Ce qu'il contrôle en aval</h4>";
    html += '<div class="table-wrap"><table class="steps stack"><thead><tr><th>Champ produit</th><th>Où il finit</th><th>Comment</th></tr></thead><tbody>' +
      f.downstream.map(function (d) {
        var dest = DEST[d.dest];
        return "<tr><td><code>" + esc(d.field) + '</code></td><td><span class="dest d-' + esc(d.dest) + '">' + esc(dest.label) + "</span></td><td>" + rich(d.how) +
          (d.src ? srcHtml([].concat(d.src)) : "") + (d.verify ? ' <span class="flag verify">à vérifier</span>' : "") + "</td></tr>";
      }).join("") + "</tbody></table></div>";

    html += "<h4>Contrat de sortie</h4><p>" + rich(f.output.text) + "</p>" + srcHtml(f.output.src);

    html += "<h4>Variables et provenance</h4>" + varsTable(f, used);

    if (parts.length) {
      html += "<h4>Gabarit réel</h4>";
      html += parts.map(function (part, i) {
        return "<details" + (i === 0 && part.key !== "system" ? " open" : (part.key === "user" ? " open" : "")) + '><summary>' + esc(part.label) +
          ' <span class="src inline">' + esc(part.src) + '</span></summary><pre class="gabarit">' + markVars(part.text) + "</pre></details>";
      }).join("");
    }
    if (f.code) {
      html += "<h4>Assemblé par le code</h4><ol class=\"small code-steps\">" + f.code.map(function (c) {
        return "<li>" + rich(c.text) + srcHtml([].concat(c.src)) + "</li>";
      }).join("") + "</ol>";
    }
    if (f.findings && f.findings.length) {
      html += '<h4>Constats liés</h4><div class="chips">' + f.findings.map(function (fid) {
        var c = findingById(fid);
        return '<a class="btn" href="#constat-' + esc(fid) + '">' + esc(c.title) + "</a>";
      }).join("") + "</div>";
    }
    var el = document.getElementById("fiche");
    el.innerHTML = html;
    if (focus) el.focus();
  }

  function renderPicker() {
    var picker = document.getElementById("fiche-picker");
    var html = "";
    D.ficheGroups.forEach(function (g) {
      html += '<div class="fiche-group"><span class="muted small">' + esc(g.label) + "</span>";
      g.fiches.forEach(function (id) {
        var f = FICHES[id];
        html += '<button type="button" role="tab" class="chip k-' + esc(f.kind) + '" data-fiche="' + esc(id) + '" aria-controls="fiche" aria-selected="false" tabindex="-1">' +
          esc(f.short || f.title) + "</button>";
      });
      html += "</div>";
    });
    picker.innerHTML = html;
    picker.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-fiche]");
      if (b) { renderFiche(b.getAttribute("data-fiche")); history.replaceState(null, "", "#fiche-" + b.getAttribute("data-fiche")); }
    });
    picker.addEventListener("keydown", function (ev) {
      var keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
      if (!(ev.key in keys) && ev.key !== "Home" && ev.key !== "End") return;
      ev.preventDefault();
      var btns = Array.prototype.slice.call(picker.querySelectorAll("[data-fiche]"));
      var i = btns.indexOf(document.activeElement);
      var next = ev.key === "Home" ? 0 : ev.key === "End" ? btns.length - 1 : (i + keys[ev.key] + btns.length) % btns.length;
      btns[next].focus();
      renderFiche(btns[next].getAttribute("data-fiche"));
    });
  }

  function gotoFiche(id) {
    renderFiche(id, true);
    history.replaceState(null, "", "#fiche-" + id);
    document.getElementById("fiches").scrollIntoView({ behavior: T.reducedMotion() ? "auto" : "smooth" });
  }

  /* ------------------------------------------------------------------ 3. traçage */
  var traceTab = "stored";
  var TR = G.trace;

  function segInfo(seg) {
    if (seg.var && D.traceVars[seg.var]) return D.traceVars[seg.var];
    return D.traceKinds[seg.src] || { label: seg.src, how: "" };
  }

  function segmentsHtml(segs) {
    return segs.map(function (s, i) {
      if (s.src === "sep") return esc(s.t);
      var info = segInfo(s);
      var label = SOURCES[s.src] ? SOURCES[s.src].label : s.src;
      return '<button type="button" class="seg s-' + esc(s.src) + (s.removed ? " removed" : "") + '" data-seg="' + i + '" aria-label="' +
        esc(label + (s.var ? ", $" + s.var : "") + (s.removed ? ", retiré à l'envoi" : "") + " : " + s.t) + '" title="' + esc(label + (s.var ? " · $" + s.var : "")) + '">' +
        esc(s.t) + "</button>";
    }).join("");
  }

  var currentSegs = [];

  function renderTrace() {
    var box = document.getElementById("trace-text");
    var tab = D.traceTabs.filter(function (t) { return t.id === traceTab; })[0];
    var html = '<p class="muted small">' + rich(tab.intro) + "</p>";
    currentSegs = [];
    if (traceTab === "stored") {
      currentSegs = TR.segments;
      html += '<p class="prompt-line">' + segmentsHtml(currentSegs) + "</p>";
      html += '<p class="muted small">Morceaux omis, faute de valeur : ' + TR.skipped.map(function (s) {
        return "<code>" + esc(s.part) + "</code> (" + s.empty.map(function (v) { return "$" + v; }).join(", ") + " vide, ligne " + s.line + ")";
      }).join(" · ") + "</p>";
    } else if (traceTab === "sent") {
      currentSegs = TR.sentSegments;
      html += '<p class="prompt-line">' + segmentsHtml(currentSegs) + "</p>";
      html += '<details><summary>Texte exact envoyé à ComfyUI (après retrait des mots barrés)</summary><pre class="gabarit">' + esc(TR.sent) + "</pre></details>";
    } else if (traceTab === "negative") {
      currentSegs = TR.negative.map(function (n) { return n; });
      html += '<p class="prompt-line">' + currentSegs.map(function (s, i) {
        return (i ? '<span class="sep">, </span>' : "") + segmentsHtml([s]).replace('data-seg="0"', 'data-seg="' + i + '"');
      }).join("") + "</p>";
    } else if (traceTab === "writer") {
      html += '<pre class="gabarit">' + esc(TR.writerUser) + "</pre>";
    }
    box.innerHTML = html;
    renderSegInfo(null);
  }

  function renderSegInfo(i) {
    var panel = document.getElementById("trace-info");
    if (i == null || !currentSegs[i]) {
      var tab = D.traceTabs.filter(function (t) { return t.id === traceTab; })[0];
      panel.innerHTML = "<h2>" + esc(tab.label) + '</h2><p class="empty">' + (currentSegs.length ? "Clique un morceau surligné (ou Tab puis Entrée) pour remonter à son auteur." : "") + "</p>" +
        (tab.notes ? '<section><h3>À retenir</h3><ul class="small">' + tab.notes.map(function (n) { return "<li>" + rich(n) + "</li>"; }).join("") + "</ul></section>" : "");
      return;
    }
    var s = currentSegs[i];
    var info = segInfo(s);
    var src = SOURCES[s.src];
    var cited = [].concat(info.src || []);
    if (s.file) cited.unshift(s.file + (s.line ? ":" + s.line : ""));
    var html = '<h2><span class="swatch s-' + esc(s.src) + '"></span>' + esc(src ? src.label : s.src) + "</h2>" +
      '<p class="quote">« ' + esc(s.t) + " »" + (s.removed ? ' <span class="flag warn">retiré au moment de l\'envoi</span>' : "") + "</p>" +
      (s.var ? "<p>Variable <code>$" + esc(s.var) + "</code></p>" : "") +
      "<p>" + rich(info.how || "") + "</p>";
    if (s.removed) html += '<p class="small">' + rich(D.removedNote) + "</p>";
    if (info.node) {
      html += '<p><button class="btn" type="button" data-goto-node="' + esc(info.node) + '">Auteur : ' + esc(nodeLines(NODES[info.node].label).join(" ")) + "</button>" +
        (info.fiche ? ' <button class="btn" type="button" data-goto-fiche="' + esc(info.fiche) + '">Fiche</button>' : "") + "</p>";
    }
    html += "<section><h3>Fichiers source</h3>" + srcHtml(dedupe(cited)) + "</section>";
    panel.innerHTML = html;
  }

  function dedupe(list) {
    var out = [];
    list.forEach(function (x) { if (out.indexOf(x) < 0) out.push(x); });
    return out;
  }

  function setupTrace() {
    document.getElementById("trace-intro").innerHTML = rich(D.traceIntro);
    document.getElementById("trace-legend").innerHTML = D.sources.filter(function (s) { return !s.hidden; }).map(function (s) {
      return '<span class="legend-item"><span class="swatch s-' + esc(s.id) + '"></span>' + esc(s.label) + "</span>";
    }).join("");
    var tabs = document.getElementById("trace-tabs");
    tabs.innerHTML = D.traceTabs.map(function (t) {
      return '<button class="btn" type="button" role="tab" aria-controls="trace-text" data-tab="' + esc(t.id) + '" aria-selected="' + (t.id === traceTab) + '" aria-pressed="' + (t.id === traceTab) + '">' + esc(t.label) + "</button>";
    }).join("");
    tabs.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-tab]");
      if (!b) return;
      traceTab = b.getAttribute("data-tab");
      tabs.querySelectorAll("[data-tab]").forEach(function (x) {
        var on = x === b;
        x.setAttribute("aria-selected", on ? "true" : "false");
        x.setAttribute("aria-pressed", on ? "true" : "false");
      });
      renderTrace();
    });
    document.getElementById("trace-text").addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-seg]");
      if (!b) return;
      document.querySelectorAll("#trace-text .seg.on").forEach(function (x) { x.classList.remove("on"); });
      b.classList.add("on");
      renderSegInfo(+b.getAttribute("data-seg"));
    });
    renderTrace();
  }

  /* ------------------------------------------------------------------ 4. constats */
  var EFFECTS = { 1: "Effet fort", 2: "Effet moyen", 3: "Effet faible" };
  var filter = "all";

  function findingById(id) {
    for (var i = 0; i < D.findings.length; i++) if (D.findings[i].id === id) return D.findings[i];
    return null;
  }

  function renderFindings() {
    var list = D.findings.slice().sort(function (a, b) { return a.effect - b.effect; });
    var shown = list.filter(function (f) { return filter === "all" || f.cat === filter || String(f.effect) === filter; });
    document.getElementById("findings").innerHTML = shown.map(function (f) {
      var cat = D.findingCats.filter(function (c) { return c.id === f.cat; })[0];
      return '<li class="finding e' + f.effect + '" id="constat-' + esc(f.id) + '"><div class="finding-head"><span class="effect e' + f.effect + '">' + EFFECTS[f.effect] + "</span>" +
        '<span class="tag">' + esc(cat.label) + "</span>" + (f.verify ? '<span class="flag verify">à vérifier</span>' : "") + "</div>" +
        "<h3>" + esc(f.title) + "</h3><p>" + rich(f.body) + "</p>" + (f.measure ? measureHtml(f.measure) : "") +
        (f.fiches ? '<div class="chips">' + f.fiches.map(function (fid) { return '<button class="linkish small" type="button" data-goto-fiche="' + esc(fid) + '">fiche : ' + esc(FICHES[fid].title) + "</button>"; }).join("") + "</div>" : "") +
        srcHtml(f.src) + "</li>";
    }).join("") || '<li class="muted">Aucun constat pour ce filtre.</li>';
  }

  // Mesure relevée par extraire_prompts.py (G.styleCuts) : chiffres réels, pas recopiés à la main.
  function measureHtml(key) {
    if (key !== "styleCuts") return "";
    var m = G.styleCuts, w = m.worst;
    return '<p class="measure">Mesure : ' + m.truncated + " séries sur " + m.total + " perdent au moins un mot-clé (au plus " + m.maxCut + ")" +
      (m.truncated ? ", par exemple " + esc(w.genre + " · " + w.rendering + " · " + w.tone) + " perd « " + esc(w.cut.join(" », « ")) + " » (" + w.length + " signes gardés)" : "") +
      ". Case d'essai : " + G.trace.style.length + " signes sur " + G.trace.style.cap + ".</p>";
  }

  function setupFindings() {
    var buttons = [{ id: "all", label: "Tous (" + D.findings.length + ")" }];
    [1, 2, 3].forEach(function (e) {
      var n = D.findings.filter(function (f) { return f.effect === e; }).length;
      buttons.push({ id: String(e), label: EFFECTS[e] + " (" + n + ")" });
    });
    D.findingCats.forEach(function (c) {
      var n = D.findings.filter(function (f) { return f.cat === c.id; }).length;
      if (n) buttons.push({ id: c.id, label: c.label + " (" + n + ")" });
    });
    var el = document.getElementById("finding-filter");
    el.innerHTML = buttons.map(function (b) {
      return '<button class="btn" type="button" data-filter="' + esc(b.id) + '" aria-pressed="' + (b.id === filter) + '">' + esc(b.label) + "</button>";
    }).join("");
    el.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-filter]");
      if (!b) return;
      filter = b.getAttribute("data-filter");
      el.querySelectorAll("[data-filter]").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      renderFindings();
    });
    renderFindings();
  }

  /* ------------------------------------------------------------------ liens croisés */
  document.addEventListener("click", function (ev) {
    var n = ev.target.closest("[data-goto-node]");
    if (n) { selectNode(n.getAttribute("data-goto-node"), true); return; }
    var f = ev.target.closest("[data-goto-fiche]");
    if (f) gotoFiche(f.getAttribute("data-goto-fiche"));
  });

  renderGraph();
  renderPicker();
  setupTrace();
  setupFindings();

  // Ancre d'arrivée (#node-…, #fiche-…, #constat-…) : depuis la carte du pipeline ou un lien partagé.
  function applyHash(first) {
    var hash = decodeURIComponent(location.hash.slice(1));
    if (hash.indexOf("node-") === 0 && NODES[hash.slice(5)]) {
      selectNode(hash.slice(5));
      renderFiche((NODES[hash.slice(5)].fiches || [])[0] || D.ficheGroups[0].fiches[0]);
      document.getElementById("graphe").scrollIntoView();
    } else if (hash.indexOf("fiche-") === 0 && FICHES[hash.slice(6)]) {
      renderFiche(hash.slice(6));
      document.getElementById("fiches").scrollIntoView();
    } else if (first) {
      renderFiche(D.ficheGroups[0].fiches[0]);
      if (hash) { var t = document.getElementById(hash); if (t) t.scrollIntoView(); }
    }
  }
  applyHash(true);
  window.addEventListener("hashchange", function () { applyHash(false); });
})();
