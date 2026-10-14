"use client";

import Link from "next/link";
import type { ReferenceAlerts } from "@/lib/api";

const MAX_LISTED = 8;

/** Alertes de l'écran de génération : case avec un personnage sans aucune image de référence (elle sera dessinée
 * au hasard), lieu sans décor (aucune référence de lieu : le décor dérive d'une case à l'autre), cases sans lieu. */
export function ReferenceAlertsBlock({
  alerts,
  projectId,
  onOpenPanel,
}: {
  alerts: ReferenceAlerts | null;
  projectId: number;
  onOpenPanel: (pageId: number, panelId: number) => void;
}) {
  if (!alerts) return null;
  const { panels_without_reference: bare, locations_without_decor: places, unattached } = alerts;
  if (!bare.length && !places.length && !unattached.length) return null;
  const lieux = `/projets/${projectId}/lieux`;
  return (
    <div
      role="status"
      className="space-y-2 rounded-md border border-amber-800/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-100"
      data-testid="reference-alerts"
    >
      {bare.length > 0 && (
        <div data-testid="alert-no-reference">
          <p>
            <strong>
              {bare.length} case{bare.length > 1 ? "s" : ""} avec un personnage sans aucune référence
            </strong>{" "}
            : ni image du personnage, ni décor, ni objet — le modèle dessinera sans modèle à suivre.
          </p>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {bare.slice(0, MAX_LISTED).map((p) => (
              <li key={p.panel_id}>
                <button
                  type="button"
                  className="rounded border border-amber-700/60 px-1.5 py-0.5 text-xs hover:bg-amber-900/40"
                  onClick={() => onOpenPanel(p.page_id, p.panel_id)}
                >
                  p. {p.page} case {p.panel}
                  {p.characters.length ? ` (${p.characters.join(", ")})` : ""}
                </button>
              </li>
            ))}
            {bare.length > MAX_LISTED && <li className="text-xs text-amber-300">… et {bare.length - MAX_LISTED} autres</li>}
          </ul>
        </div>
      )}
      {places.length > 0 && (
        <p data-testid="alert-location-without-decor">
          <strong>
            {places.length} lieu{places.length > 1 ? "x" : ""} sans décor
          </strong>{" "}
          :{" "}
          {places
            .map(
              (l) =>
                `${l.name} (${l.panels} case${l.panels > 1 ? "s" : ""}${l.reason === "decor_without_image" ? ", décor sans image" : ""})`,
            )
            .join(", ")}{" "}
          — pas de référence de lieu, le décor peut dériver d&apos;une case à l&apos;autre.{" "}
          <Link href={lieux} className="underline hover:text-white">
            Donner un décor aux lieux
          </Link>
        </p>
      )}
      {unattached.length > 0 && (
        <p data-testid="alert-unattached">
          <strong>
            {unattached.length} case{unattached.length > 1 ? "s" : ""} sans lieu
          </strong>{" "}
          : rattache-les à un lieu de la série (écran Scénario, ou regroupement des lieux).{" "}
          <Link href={lieux} className="underline hover:text-white">
            Regrouper les lieux
          </Link>
        </p>
      )}
    </div>
  );
}
