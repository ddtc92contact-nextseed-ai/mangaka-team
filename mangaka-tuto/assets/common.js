/* Petits outils partagés par les vues (scripts classiques : pas de modules, qui ne marchent pas en file://). */
(function () {
  "use strict";

  var WHO_LABELS = {
    llm: "Agent LLM",
    comfy: "ComfyUI",
    code: "Code déterministe",
    human: "Humain",
    vision: "Vision (Ollama)",
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // `texte` peut contenir des `extraits de code` entre accents graves (rendus en <code>) et du **gras**.
  function rich(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  function whoBadge(kind, label) {
    return '<span class="who ' + esc(kind) + '">' + esc(label || WHO_LABELS[kind] || kind) + "</span>";
  }

  function srcList(files) {
    return (files || [])
      .map(function (f) {
        return '<div class="src">' + esc(f) + "</div>";
      })
      .join("");
  }

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function agentById(id) {
    var list = (window.TUTO && window.TUTO.agents) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  // Modèle d'un agent LLM : celui de providers.yaml (deepseek.model) tant que l'agent ne le change pas.
  function modelLabel(agent) {
    var P = window.TUTO.providers;
    if (!agent || !agent.llm) return "";
    var m = P.models[P.defaultModel] || {};
    return P.defaultModel + " (" + (m.reasoning ? "classe raisonnement" : "classe rapide") + ")";
  }

  window.Tuto = {
    WHO_LABELS: WHO_LABELS,
    esc: esc,
    rich: rich,
    whoBadge: whoBadge,
    srcList: srcList,
    reducedMotion: reducedMotion,
    agentById: agentById,
    modelLabel: modelLabel,
  };
})();
