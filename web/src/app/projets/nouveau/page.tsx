"use client";

import { useRouter } from "next/navigation";
import { ProjectForm } from "@/components/project-form";
import { Card, PageHeader } from "@/components/ui";

export default function NewProjectPage() {
  const router = useRouter();
  return (
    <>
      <PageHeader title="Nouvelle série" subtitle="Les presets par défaut viennent de presets/defaults.yaml." />
      <Card className="max-w-3xl">
        <ProjectForm submitLabel="Créer la série" onSaved={(p) => router.push(`/projets/${p.id}`)} />
      </Card>
    </>
  );
}
