"use client";

import { LetteringCanvas } from "@/app/chapitres/[id]/lettrage/lettering-canvas";
import { api, type PageData } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { Alert, Loading } from "./ui";

/** La page a-t-elle du texte à lettrer (bulles ou onomatopées) ? */
export function hasLettering(page: PageData): boolean {
  return page.panels.some((p) => p.dialogues.length > 0 || (p.sfx?.length ?? 0) > 0);
}

const noop = () => {};

/** Planche assemblée avec son lettrage (bulles, onomatopées), en lecture seule. */
export function LetteredPreview({ page, refreshKey }: { page: PageData; refreshKey?: unknown }) {
  const data = useEngineData(() => api.getLettering(page.id), [page.id, refreshKey]);
  const current = data.data && data.data.page_id === page.id ? data.data : null;
  if (data.error && !current) return <Alert>Lettrage indisponible : {data.error}</Alert>;
  if (!current) return <Loading />;
  return (
    <div role="img" aria-label={`Page ${page.number} assemblée, avec bulles et onomatopées`} data-testid="lettered-preview">
      <div inert className="pointer-events-none">
        <LetteringCanvas
          data={current}
          selectedId={null}
          showGuides={false}
          disabled
          onSelect={noop}
          onCommit={noop}
          onCommitSfx={noop}
        />
      </div>
    </div>
  );
}
