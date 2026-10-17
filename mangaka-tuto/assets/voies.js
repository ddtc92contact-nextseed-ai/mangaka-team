/* Les deux voies : chronogramme animé du pool de threads (JobRunner) et de la file ComfyUI (SerialJobQueue). */
(function () {
  "use strict";
  var D = window.TUTO;
  var T = window.Tuto;
  var demo = D.lanesDemo;
  var NS = "http://www.w3.org/2000/svg";

  var W = 1000;
  var LABEL_W = 150;
  var LANE_H = 34;
  var GAP = 6;
  var WAIT_H = 22;
  var workers = demo.workers;
  // Lignes : 4 workers du pool, un séparateur, la file ComfyUI, puis la salle d'attente de la file.
  var rows = [];
  for (var i = 0; i < workers; i++) rows.push({ key: "llm" + i, label: "Worker " + (i + 1), lane: "llm" });
  rows.push({ key: "sep" });
  rows.push({ key: "comfy", label: "En cours (1 seul)", lane: "comfy" });
  // Salle d'attente : une ligne par attente simultanée (les attentes se chevauchent), attribuée au plus tôt.
  var waitEnds = [];
  demo.jobs
    .filter(function (j) {
      return j.lane === "comfy" && j.start > j.enq;
    })
    .sort(function (a, b) {
      return a.enq - b.enq;
    })
    .forEach(function (j) {
      var k = 0;
      while (k < waitEnds.length && waitEnds[k] > j.enq) k++;
      waitEnds[k] = j.start;
      j.waitRow = k;
    });
  waitEnds.forEach(function (_, k) {
    rows.push({ key: "wait" + k, label: k === 0 ? "En attente (FIFO)" : "", lane: "wait", small: true });
  });
  var rowY = {};
  var y = 40;
  rows.forEach(function (r) {
    rowY[r.key] = y;
    y += r.key === "sep" ? 34 : r.small ? WAIT_H + 3 : LANE_H + GAP;
  });
  var H = y + 30;
  var scale = (W - LABEL_W - 16) / demo.duration;
  function X(t) {
    return LABEL_W + t * scale;
  }

  function el(name, attrs, parent) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-labelledby": "lanes-title lanes-desc" });
  var tt = el("title", { id: "lanes-title" }, svg);
  tt.textContent = "Chronogramme : pool de threads parallèle et file ComfyUI sérielle";
  var td = el("desc", { id: "lanes-desc" }, svg);
  td.textContent = demo.description;

  el("text", { class: "lane-label", x: 8, y: 26, style: "fill:var(--llm);font-weight:600" }, svg).textContent =
    "Pool JobRunner — 4 en parallèle";
  el("text", { class: "lane-label", x: 8, y: rowY.sep + 24, style: "fill:var(--comfy);font-weight:600" }, svg).textContent =
    "File ComfyUI — une seule tâche à la fois, partagée par toutes les étapes images";

  rows.forEach(function (r) {
    if (r.key === "sep") return;
    var h = r.small ? WAIT_H : LANE_H;
    el("rect", { class: "lane-bg", x: LABEL_W, y: rowY[r.key], width: W - LABEL_W - 16, height: h, rx: 6, opacity: r.small ? 0.45 : 1 }, svg);
    el("text", { class: "lane-label", x: 8, y: rowY[r.key] + (r.small ? 16 : 22) }, svg).textContent = r.label;
  });

  // Graduations.
  for (var t = 0; t <= demo.duration; t += demo.tick) {
    el("line", { x1: X(t), x2: X(t), y1: 34, y2: H - 24, stroke: "#27272a" }, svg);
    el("text", { x: X(t), y: H - 8, "text-anchor": "middle", style: "fill:#71717a;font-size:11px;font-family:var(--mono)" }, svg).textContent = t;
  }

  var COLORS = { A: "#fcd34d", B: "#7dd3fc", C: "#6ee7b7", R: "#c4b5fd" };
  var jobLayer = el("g", {}, svg);
  var defs = el("defs", {}, svg);
  var items = demo.jobs.map(function (j, idx) {
    var g = el("g", { class: "job" }, jobLayer);
    var row = j.lane === "llm" ? "llm" + j.worker : "comfy";
    var color = COLORS[j.chapter] || "#a1a1aa";
    // Partie « en attente » (file ComfyUI seulement) : de la mise en file au démarrage.
    var wait = null;
    if (j.lane === "comfy" && j.start > j.enq) {
      wait = el("g", { class: "job waiting" }, jobLayer);
      var wy = rowY["wait" + j.waitRow];
      el("rect", { x: X(j.enq), y: wy + 2, width: Math.max(2, (j.start - j.enq) * scale), height: WAIT_H - 4, fill: color, stroke: color }, wait);
      var wclip = el("clipPath", { id: "wclip-" + idx }, defs);
      el("rect", { x: X(j.enq), y: wy, width: Math.max(2, (j.start - j.enq) * scale - 4), height: WAIT_H }, wclip);
      var wt = el("text", { x: X(j.enq) + 6, y: wy + 15, "clip-path": "url(#wclip-" + idx + ")", style: "font-size:11px" }, wait);
      wt.textContent = j.short || j.label;
    }
    var rect = el("rect", { x: X(j.start), y: rowY[row] + 3, width: Math.max(2, (j.end - j.start) * scale - 2), height: LANE_H - 6, fill: color }, g);
    // Le libellé ne déborde jamais de sa boîte : coupé par un clip qui suit la largeur dessinée.
    var clip = el("clipPath", { id: "clip-" + idx }, defs);
    var clipRect = el("rect", { x: X(j.start), y: rowY[row], width: 0, height: LANE_H }, clip);
    var text = el("text", { x: X(j.start) + 6, y: rowY[row] + 21, "clip-path": "url(#clip-" + idx + ")" }, g);
    text.textContent = j.short || j.label;
    var title = el("title", {}, g);
    title.textContent = j.label + " — étape « " + j.step + " »";
    return { job: j, g: g, rect: rect, clip: clipRect, wait: wait };
  });

  var head = el("line", { x1: X(0), x2: X(0), y1: 30, y2: H - 22, stroke: "#fb7185", "stroke-width": 2 }, svg);

  document.getElementById("lanes").appendChild(svg);

  // --- Lecture ---
  var slider = document.getElementById("t");
  var clock = document.getElementById("clock");
  var narration = document.getElementById("narration");
  var playBtn = document.getElementById("play");
  slider.max = demo.duration;

  // Une boîte se dessine au fil du temps : rien avant sa mise en file, attente puis exécution.
  function render(now) {
    head.setAttribute("x1", X(now));
    head.setAttribute("x2", X(now));
    items.forEach(function (it) {
      var j = it.job;
      var shown = now >= j.start;
      var w = shown ? Math.max(2, (Math.min(now, j.end) - j.start) * scale - (now >= j.end ? 2 : 0)) : 0;
      it.rect.setAttribute("width", w);
      it.clip.setAttribute("width", Math.max(0, w - 4));
      it.g.style.opacity = shown ? 1 : 0;
      if (it.wait) {
        var r = it.wait.firstChild;
        var visible = now >= j.enq;
        it.wait.style.opacity = visible ? 1 : 0;
        r.setAttribute("width", visible ? Math.max(2, (Math.min(now, j.start) - j.enq) * scale) : 0);
      }
    });
    clock.textContent = "t = " + Math.round(now);
    var text = demo.events[0].text;
    demo.events.forEach(function (e) {
      if (now >= e.t) text = e.text;
    });
    if (narration.getAttribute("data-text") !== text) {
      narration.setAttribute("data-text", text);
      narration.innerHTML = T.rich(text);
    }
    slider.value = now;
    slider.setAttribute("aria-valuetext", "instant " + Math.round(now) + " sur " + demo.duration);
  }

  var now = 0;
  var playing = false;
  var last = 0;
  var SPEED = demo.duration / 40; // ~40 s pour toute l'histoire
  function frame(ts) {
    if (!playing) return;
    if (last) now = Math.min(demo.duration, now + ((ts - last) / 1000) * SPEED);
    last = ts;
    render(now);
    if (now >= demo.duration) {
      stop();
      return;
    }
    requestAnimationFrame(frame);
  }
  function play() {
    if (now >= demo.duration) now = 0;
    playing = true;
    last = 0;
    playBtn.textContent = "⏸ Pause";
    playBtn.setAttribute("aria-pressed", "true");
    requestAnimationFrame(frame);
  }
  function stop() {
    playing = false;
    playBtn.textContent = "▶ Lecture";
    playBtn.setAttribute("aria-pressed", "false");
  }
  playBtn.addEventListener("click", function () {
    if (playing) stop();
    else play();
  });
  document.getElementById("restart").addEventListener("click", function () {
    now = 0;
    render(now);
    if (!T.reducedMotion()) play();
  });
  document.getElementById("end").addEventListener("click", function () {
    stop();
    now = demo.duration;
    render(now);
  });
  slider.addEventListener("input", function () {
    stop();
    now = Number(slider.value);
    render(now);
  });

  // Pas d'animation automatique si l'utilisateur la refuse : on montre l'état final, le curseur reste utilisable.
  if (T.reducedMotion()) {
    now = demo.duration;
    render(now);
  } else {
    render(0);
    play();
  }

  // --- Tableaux des étapes de chaque voie ---
  function rowsHtml(list) {
    return list
      .map(function (s) {
        return (
          "<tr><td><code>" + T.esc(s.step) + "</code></td><td>" + T.rich(s.label) + "</td><td>" + T.rich(s.what) +
          "</td><td>" + T.srcList(s.src) + "</td></tr>"
        );
      })
      .join("");
  }
  var head2 = '<thead><tr><th scope="col">Étape du job</th><th scope="col">Nom</th><th scope="col">Ce qu\'elle fait</th><th scope="col">Source</th></tr></thead>';
  document.getElementById("queue-table").innerHTML = head2 + "<tbody>" + rowsHtml(D.queueSteps) + "</tbody>";
  document.getElementById("pool-table").innerHTML = head2 + "<tbody>" + rowsHtml(D.poolSteps) + "</tbody>";
})();
