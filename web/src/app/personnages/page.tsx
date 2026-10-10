import { redirect } from "next/navigation";

/** Ancienne adresse de la liste des personnages : onglet « Personnages » de la bibliothèque. */
export default function CharactersPage() {
  redirect("/bibliotheque?onglet=personnages");
}
