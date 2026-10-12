"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Alert, ButtonLink } from "@/components/ui";
import { nextStep, stepHref } from "@/lib/next-step";
import { useChapter } from "./chapter-context";

/**
 * Erreur d'une étape du chapitre. Quand le moteur dit qu'il manque une étape (« découpe d'abord le chapitre »,
 * « page pas encore mise en page »), message aux couleurs de l'appli avec un bouton vers cette étape ;
 * sinon, alerte d'erreur ordinaire. `action` remplace le bouton (ex. « Écrire le synopsis » sur la même page).
 */
export function StepAlert({ message, action }: { message: string; action?: ReactNode }) {
  const { chapter } = useChapter();
  const pathname = usePathname();
  const next = nextStep(message);
  if (!next && !action) return <Alert>{message}</Alert>;
  const href = next ? stepHref(chapter.id, next.step) : null;
  return (
    <div
      role="alert"
      data-testid="step-alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-700/50 bg-amber-950/30 px-4 py-3 text-sm"
    >
      <div className="min-w-0">
        <p className="font-medium text-amber-100">Étape pas encore possible</p>
        <p className="mt-0.5 text-amber-200/80">{message.charAt(0).toUpperCase() + message.slice(1)}</p>
      </div>
      {action ??
        (next && href && href !== pathname && (
          <ButtonLink href={href} variant="secondary">
            {next.label}
          </ButtonLink>
        ))}
    </div>
  );
}
