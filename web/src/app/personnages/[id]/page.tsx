"use client";

import { useParams } from "next/navigation";
import { LibraryEntryPage } from "@/components/library-entry-page";

export default function CharacterPage() {
  const id = Number(useParams<{ id: string }>().id);
  return <LibraryEntryPage kind="character" id={id} />;
}
