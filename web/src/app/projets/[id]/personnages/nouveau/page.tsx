"use client";

import { useParams } from "next/navigation";
import { NewLibraryEntryPage } from "@/components/library-entry-page";

export default function NewCharacterPage() {
  return <NewLibraryEntryPage kind="character" projectId={Number(useParams<{ id: string }>().id)} />;
}
