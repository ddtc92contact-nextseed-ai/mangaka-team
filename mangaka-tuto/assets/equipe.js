/* L'équipe : une fiche par agent de presets/agents/, étapes déduites de la carte du pipeline. */
(function () {
  "use strict";
  var D = window.TUTO;
  var T = window.Tuto;
  var esc = T.esc;

  function stepsOf(agentId) {
    return D.steps.filter(function (s) {
      return s.who.some(function (w) {
        return w.agent === agentId;
      });
    });
  }

  function card(a) {
    var steps = stepsOf(a.id);
    var model;
    if (a.llm) {
      model = "<code>" + esc(T.modelLabel(a)) + "</code><br><span class=\"small muted\">" + esc(D.providers.note) + "</span>";
    } else {
      model = T.rich(a.engine);
    }
    var prompts = (a.prompts || [])
      .map(function (p) {
        return (
          '<details><summary><code>' + esc(p.file) + "</code> — " + esc(p.label) + " (" + p.variables.length +
          ' variables)</summary><div class="tags">' +
          p.variables
            .map(function (v) {
              return '<span class="tag">$' + esc(v) + "</span>";
            })
            .join("") +
          "</div></details>"
        );
      })
      .join("");
    return (
      '<article class="agent" id="agent-' + esc(a.id) + '" data-kinds="' + esc(a.kinds.join(" ")) + '" tabindex="-1">' +
      '<header><div class="icon" aria-hidden="true">' + esc(a.icon) + "</div><div><h2>" + esc(a.name) + "</h2>" +
      '<div class="small muted">Étape ' + esc(a.step) + " · " + esc(a.stepLabel) + "</div></div></header>" +
      "<p>" + T.rich(a.role) + "</p>" +
      '<div>' + a.kinds.map(function (k) { return T.whoBadge(k); }).join(" ") + "</div>" +
      '<dl class="kv">' +
      "<dt>Modèle</dt><dd>" + model + "</dd>" +
      "<dt>Jobs</dt><dd>" + (a.jobSteps.length ? a.jobSteps.map(function (j) { return "<code>" + esc(j) + "</code>"; }).join(" ") : '<span class="muted">aucun job propre</span>') + "</dd>" +
      "<dt>Intervient</dt><dd>" +
      (steps.length
        ? steps.map(function (s) { return '<a href="pipeline.html#' + esc(s.id) + '">' + esc(s.n + " " + s.title) + "</a>"; }).join("<br>")
        : "—") +
      "</dd>" +
      (a.extra ? "<dt>À savoir</dt><dd>" + T.rich(a.extra) + "</dd>" : "") +
      "</dl>" +
      (prompts ? '<div><strong class="small">Variables de prompt</strong>' + prompts + "</div>" : '<p class="small muted">Pas de prompt LLM : réglages chiffrés seulement.</p>') +
      '<div>' + T.srcList(a.src) + "</div>" +
      "</article>"
    );
  }

  var root = document.getElementById("agents");
  root.innerHTML = D.agents.map(card).join("");

  var buttons = document.querySelectorAll(".filter button");
  Array.prototype.forEach.call(buttons, function (b) {
    b.addEventListener("click", function () {
      var k = b.getAttribute("data-kind");
      Array.prototype.forEach.call(buttons, function (o) {
        o.setAttribute("aria-pressed", o === b ? "true" : "false");
      });
      Array.prototype.forEach.call(root.children, function (c) {
        c.hidden = k !== "all" && c.getAttribute("data-kinds").split(" ").indexOf(k) < 0;
      });
    });
  });

  var hash = (location.hash || "").slice(1);
  var target = hash && document.getElementById(hash);
  if (target) {
    target.focus();
    target.style.borderColor = "var(--accent)";
  }
})();
