"use client";

import { useParams } from "next/navigation";
import { LibraryEntryPage } from "@/components/library-entry-page";
import { Alert } from "@/components/ui";
import { kindFromSlug } from "@/lib/library";

/** Fiche d'un objet ou d'un décor : `/bibliotheque/objets/{id}`, `/bibliotheque/decors/{id}`. */
export default function LibraryEntryRoute() {
  const params = useParams<{ kind: string; id: string }>();
  const kind = kindFromSlug(params.kind);
  if (!kind) return <Alert>Rubrique inconnue : « {params.kind} » (personnages, objets ou decors).</Alert>;
  return <LibraryEntryPage kind={kind} id={Number(params.id)} />;
}
