import Link from "next/link";
import { productionHref } from "@/lib/generation";

/** Lien « Voir la production » affiché après chaque mise en file (chapitre, page, case, Qualité). */
export function ProductionLink({ chapterId, pageId }: { chapterId: number; pageId?: number | null }) {
  return (
    <Link
      href={productionHref(chapterId, pageId)}
      className="whitespace-nowrap font-medium text-rose-300 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-rose-400"
      data-testid="see-production"
    >
      Voir la production →
    </Link>
  );
}
