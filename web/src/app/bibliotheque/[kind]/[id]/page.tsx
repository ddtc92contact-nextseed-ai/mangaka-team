"use client";

import { useParams } from "next/navigation";
import { LibraryEntryPage } from "@/components/library-entry-page";
import { Alert } from "@/components/ui";
import { kindFromSlug } from "@/lib/library";

/** Fiche d'un objet, d'un décor, d'un véhicule ou d'une créature : `/bibliotheque/objets/{id}`, `/bibliotheque/vehicules/{id}`… */
export default function LibraryEntryRoute() {
  const params = useParams<{ kind: string; id: string }>();
  const kind = kindFromSlug(params.kind);
  if (!kind) return <Alert>Rubrique inconnue : « {params.kind} » (personnages, objets, decors, vehicules ou creatures).</Alert>;
  return <LibraryEntryPage kind={kind} id={Number(params.id)} />;
}
