import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Le badge de dev de Next masquerait les statuts moteur/ComfyUI en bas de la sidebar.
  devIndicators: { position: "bottom-right" },
  experimental: {
    // Le serveur MCP de dev recopie les logs du navigateur dans .next/dev/logs/ ; sur certaines
    // machines, ces écritures relançaient la compilation puis un rechargement complet, en boucle.
    mcpServer: false,
  },
  turbopack: {
    // Racine épinglée sur le monorepo (node_modules hoistés) : un lockfile dans un dossier parent
    // ne doit pas élargir la zone surveillée.
    root: path.join(__dirname, ".."),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
