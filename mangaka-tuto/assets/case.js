/* Vie d'une case : parcours pas à pas, fiche de la case qui se remplit et aperçu qui se dessine. */
(function () {
  "use strict";
  var D = window.TUTO;
  var T = window.Tuto;
  var esc = T.esc;
  var life = D.panelLife;
  var steps = life.steps;

  // --- Aperçu : calques SVG allumés au fil des étapes (dessin schématique, pas une vraie image générée). ---
  var LAYERS = {
    text:
      '<g id="L-text"><rect x="20" y="20" width="360" height="260" fill="#fafafa"/>' +
      '<text x="200" y="135" text-anchor="middle" font-size="15" fill="#3f3f46" font-family="system-ui">« Kaï découvre la lettre</text>' +
      '<text x="200" y="157" text-anchor="middle" font-size="15" fill="#3f3f46" font-family="system-ui">sous la porte. »</text></g>',
    guides:
      '<g id="L-guides" stroke="#7dd3fc" stroke-dasharray="6 5" fill="none" stroke-width="2">' +
      '<line x1="140" y1="20" x2="140" y2="280"/><line x1="260" y1="20" x2="260" y2="280"/>' +
      '<line x1="20" y1="107" x2="380" y2="107"/><line x1="20" y1="193" x2="380" y2="193"/>' +
      '<text x="30" y="40" fill="#0369a1" stroke="none" font-size="13" font-family="system-ui">plan rapproché · plongée</text></g>',
    zone: '<rect id="L-zone" x="250" y="28" width="120" height="70" fill="rgba(251,113,133,.18)" stroke="#fb7185" stroke-dasharray="4 3"/>',
    sketch:
      '<g id="L-sketch" stroke="#71717a" fill="none" stroke-width="2" stroke-linecap="round">' +
      '<path d="M60 270 Q120 150 175 140 Q230 150 260 270"/><circle cx="175" cy="105" r="34"/>' +
      '<path d="M150 180 L105 230 M200 180 L250 215"/><rect x="240" y="205" width="58" height="38" transform="rotate(-12 269 224)"/>' +
      '<path d="M20 250 L380 250" stroke-dasharray="3 6"/></g>',
    clean:
      '<g id="L-clean"><rect x="20" y="20" width="360" height="260" fill="#e4e4e7"/>' +
      '<path d="M20 250 L380 250 L380 280 L20 280 Z" fill="#a1a1aa"/>' +
      '<path d="M60 270 Q120 150 175 140 Q230 150 260 270 Z" fill="#27272a"/>' +
      '<circle cx="175" cy="105" r="34" fill="#f4f4f5" stroke="#18181b" stroke-width="3"/>' +
      '<path d="M150 98 q8 -6 14 0 M186 98 q8 -6 14 0" stroke="#18181b" stroke-width="3" fill="none"/>' +
      '<path d="M140 80 Q175 50 212 82 Q200 64 175 62 Q150 64 140 80Z" fill="#18181b"/>' +
      '<rect x="240" y="205" width="58" height="38" transform="rotate(-12 269 224)" fill="#fafafa" stroke="#18181b" stroke-width="3"/>' +
      '<path d="M150 180 L105 230 M200 180 L250 215" stroke="#18181b" stroke-width="7" stroke-linecap="round"/></g>',
    qc:
      '<g id="L-qc"><rect x="28" y="28" width="96" height="30" rx="15" fill="#065f46"/>' +
      '<text x="76" y="48" text-anchor="middle" fill="#d1fae5" font-size="14" font-family="system-ui" font-weight="700">QC 86 · ok</text></g>',
    hd: '<g id="L-hd"><rect x="300" y="250" width="72" height="22" rx="4" fill="#422006"/><text x="336" y="266" text-anchor="middle" fill="#fde68a" font-size="12" font-family="system-ui">300 dpi</text></g>',
    bubbles:
      '<g id="L-bubbles"><ellipse cx="300" cy="66" rx="76" ry="40" fill="#fff" stroke="#000" stroke-width="2.5"/>' +
      '<path d="M262 96 L232 122 L280 102" fill="#fff" stroke="#000" stroke-width="2.5" stroke-linejoin="round"/>' +
      '<rect x="258" y="94" width="28" height="7" fill="#fff"/>' +
      '<text x="300" y="61" text-anchor="middle" font-size="17" font-family="\'Comic Sans MS\', system-ui" font-weight="700">Qui a</text>' +
      '<text x="300" y="82" text-anchor="middle" font-size="17" font-family="\'Comic Sans MS\', system-ui" font-weight="700">écrit ça ?!</text></g>',
  };
  var ORDER = ["text", "clean", "guides", "sketch", "zone", "qc", "hd", "bubbles"];

  function preview(layers) {
    var on = {};
    layers.forEach(function (l) {
      on[l] = true;
    });
    // Le propre remplace le croquis et le texte ; les guides disparaissent une fois l'image là.
    if (on.clean) {
      delete on.sketch;
      delete on.text;
      delete on.guides;
    }
    return (
      '<svg viewBox="0 0 400 300" role="img" aria-label="Aperçu schématique de la case"><rect width="400" height="300" fill="#fafafa"/>' +
      ORDER.filter(function (k) {
        return on[k];
      })
        .map(function (k) {
          return LAYERS[k];
        })
        .join("") +
      '<rect x="20" y="20" width="360" height="260" fill="none" stroke="#000" stroke-width="4"/></svg>'
    );
  }

  // --- Fiche cumulative ---
  function record(idx) {
    var lines = [];
    for (var i = 0; i <= idx; i++) {
      var adds = steps[i].adds || [];
      adds.forEach(function (a) {
        lines.push({ k: a[0], v: a[1], fresh: i === idx });
      });
    }
    return lines
      .map(function (l) {
        return (
          '<div class="' + (l.fresh ? "add" : "") + '">' + (l.fresh ? "+ " : "  ") + '<span class="k">' + esc(l.k) + "</span> : " + esc(l.v) + "</div>"
        );
      })
      .join("");
  }

  var tl = document.getElementById("timeline");
  tl.innerHTML = steps
    .map(function (s, i) {
      return '<li><button type="button" data-i="' + i + '"><span class="k">' + (i + 1) + "</span>" + esc(s.title) + "</button></li>";
    })
    .join("");
  var buttons = tl.querySelectorAll("button");

  var idx = 0;
  function show(i, focus) {
    idx = Math.max(0, Math.min(steps.length - 1, i));
    var s = steps[idx];
    Array.prototype.forEach.call(buttons, function (b, bi) {
      if (bi === idx) b.setAttribute("aria-current", "step");
      else b.removeAttribute("aria-current");
      b.classList.toggle("done", bi < idx);
    });
    var who = s.who
      .map(function (w) {
        var a = w.agent ? T.agentById(w.agent) : null;
        return T.whoBadge(w.kind, a ? a.icon + " " + a.name : w.label);
      })
      .join(" ");
    document.getElementById("step-body").innerHTML =
      '<p class="small muted" style="margin:0">Étape ' + (idx + 1) + " sur " + steps.length + "</p>" +
      '<h2 id="step-title" tabindex="-1">' + esc(s.title) + "</h2>" +
      '<div style="margin-bottom:8px">' + who + "</div>" +
      "<p>" + T.rich(s.text) + "</p>" +
      (s.step ? '<p class="small"><a href="pipeline.html#' + esc(s.step) + '">Voir l\'étape sur la carte du pipeline →</a></p>' : "") +
      T.srcList(s.src);
    document.getElementById("preview").innerHTML = preview(s.layers || []);
    var rec = document.getElementById("record");
    rec.innerHTML = record(idx);
    var fresh = rec.querySelector(".add");
    if (fresh) rec.scrollTop = Math.max(0, fresh.offsetTop - 8);
    document.getElementById("prev").disabled = idx === 0;
    document.getElementById("next").disabled = idx === steps.length - 1;
    document.getElementById("counter").textContent = idx + 1 + " / " + steps.length;
    if (focus) document.getElementById("step-title").focus({ preventScroll: true });
    // Garder l'étape active visible dans la frise horizontale (écran étroit).
    if (buttons[idx].scrollIntoView && window.innerWidth <= 760) {
      buttons[idx].scrollIntoView({ block: "nearest", inline: "center", behavior: T.reducedMotion() ? "auto" : "smooth" });
    }
  }

  tl.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (b) show(Number(b.getAttribute("data-i")), true);
  });
  document.getElementById("prev").addEventListener("click", function () {
    show(idx - 1);
  });
  document.getElementById("next").addEventListener("click", function () {
    show(idx + 1);
  });
  document.addEventListener("keydown", function (e) {
    if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    if (e.key === "ArrowRight") show(idx + 1);
    else if (e.key === "ArrowLeft") show(idx - 1);
  });
  show(0);
})();
