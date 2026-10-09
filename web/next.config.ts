import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Le badge de dev de Next masquerait les statuts moteur/ComfyUI en bas de la sidebar.
  devIndicators: { position: "bottom-right" },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
