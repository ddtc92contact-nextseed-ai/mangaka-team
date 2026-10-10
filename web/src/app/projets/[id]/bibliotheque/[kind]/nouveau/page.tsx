"use client";

import { useParams } from "next/navigation";
import { NewLibraryEntryPage } from "@/components/library-entry-page";
import { Alert } from "@/components/ui";
import { kindFromSlug } from "@/lib/library";

export default function NewLibraryEntryRoute() {
  const params = useParams<{ id: string; kind: string }>();
  const kind = kindFromSlug(params.kind);
  if (!kind) return <Alert>Rubrique inconnue : « {params.kind} » (personnages, objets ou decors).</Alert>;
  return <NewLibraryEntryPage kind={kind} projectId={Number(params.id)} />;
}
