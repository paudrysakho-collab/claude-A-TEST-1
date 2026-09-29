#!/usr/bin/env python3
"""Prépare 4 lots de relance de 400 contacts (mercredi → samedi) pour le salon du 5 octobre.

Source unique : feuille « Tous les contacts » du fichier Master.

Exclusions : désabonnés, inscrits (statut, colonne Inscrit, fichier d'inscriptions), e-mails envoyés
lundi 28/09 et mardi 29/09, catégories hors cible, contacts jamais envoyés (Nb envois = 0).

Priorités (validées avec l'utilisateur le 30/09) :
  1 Cavistes, bars à vin, caves à manger, fromageries-caves, torréfacteurs
  2 Épiceries fines, coffrets gourmands, magasins de bouche fins
  3 Tables bistronomiques, restaurants gastronomiques, hôtels-restaurants
  4 Traiteurs réception, lieux de réception
  5 Autres restaurants et CHR (les moins sollicités d'abord)
Contacts sans catégorie : profil déduit du nom de l'établissement (formule « à toute l'équipe de… »)
et de la campagne (« Vague Cavistes »). PMU, pizzerias, crêperies, kebabs et restauration rapide exclus.

Usage : python generer_relances.py [chemin/vers/Master.xlsx]
"""
import csv
import glob
import os
import re
import sys
from collections import Counter

import openpyxl

ICI = os.path.dirname(os.path.abspath(__file__))
SOURCES = os.path.join(ICI, "donnees_sources")
TAILLE_LOT = 400
LOTS = ["RELANCE_LOT1_MERCREDI.csv", "RELANCE_LOT2_JEUDI.csv",
        "RELANCE_LOT3_VENDREDI.csv", "RELANCE_LOT4_SAMEDI.csv"]

CATEGORIES_EXCLUES = {
    # hors cible, 0 % de conversion
    "Producteur - Vente Directe", "Camping", "Camping Premium", "Gîte", "Gîte de Groupe",
    "Chambre d'hôtes", "Maison d'Hôtes",
    # producteurs et distributeurs
    "Brasserie Artisanale", "Œnotourisme", "Magasin de Producteurs", "Distributeur CHR",
    # entreprises, réseaux et événementiel (hors hiérarchie)
    "Réseau de Dirigeants", "Club d'Affaires", "Agence Événementielle", "Prestataire Événementiel",
    "Cadeaux d'Affaires", "Golf / Resort", "Conciergerie d'Entreprise", "CSE / Comité d'Entreprise",
    "Wedding Planner", "Salle de Séminaire", "Club Sportif / Partenaires", "Espace Coworking",
    "Organisateur de Congrès", "Autocariste", "Site de Loisirs", "École Hôtelière",
    "Agence de Développement", "Thalasso-Spa", "Chef à Domicile",
}
PRIO_CATEGORIE = {
    "Caviste": 1, "Bar à Vin": 1, "Bar à Vin / Bar-restaurant": 1, "Fromagerie-Cave": 1, "Torréfacteur": 1,
    "Épicerie Fine": 2, "Coffrets Gourmands": 2, "Chocolaterie-Coffrets": 2, "Poissonnerie-Écailler": 2,
    "Table Bistronomique": 3, "Restaurant Gastronomique": 3, "Hôtel-Restaurant": 3, "Hôtels-restaurants": 3,
    "Traiteur Réception": 4, "Lieu de Réception": 4, "Traiteur": 4, "Boucherie-Traiteur": 4,
    "Restaurant": 5, "Ferme-Auberge": 5, "Casino-Restaurant": 5,
}
# Profil déduit du nom (contacts sans catégorie), dans l'ordre de test.
REGLES_NOM = [
    (1, "Caviste / bar à vin (déduit)",
     r"\bcaves?\b|caviste|\bvins?\b|vinoth|\bchais?\b|cellier|tapas|fromag|torr[ée]f|\bbib[oe]"),
    (2, "Épicerie fine (déduit)", r"[ée]picer|comptoir gourmand|coffret|chocolat"),
    (4, "Traiteur (déduit)", r"traiteur|r[ée]ception"),
    (3, "Bistrot / gastronomique / hôtel-restaurant (déduit)",
     r"bistr|gastronom|\bh[oô]tel|auberge|relais|logis|\btable\b"),
]
RE_RAPIDE = re.compile(r"\bpmu\b|tabac|pizz|cr[eê]p|galette|kebab|burger|tacos|sushi|snack|friterie|"
                       r"fast.?food|restauration rapide|sandwich|bagel|wok|roi du poulet", re.I)
# Règles de rejet d'origine (brief initial) : écoles, campings, gîtes, chambres d'hôtes…
RE_HORS_CIBLE = re.compile(r"lyc[ée]e|[ée]cole|coll[èe]ge|\bcfa\b|greta|campus|camping|g[iî]tes?\b|"
                           r"chambres? d.h[oô]tes?|maison d.h[oô]tes|ehpad|scolaire", re.I)
SOUS_CHAINES_INTERDITES = ("le21pornic", "domainedeliziec", "camping", "gite", "greta", "cfa", "chambre-hote",
                           "ac-nantes.fr", "ac-rennes.fr")
RE_EMAIL = re.compile(r"[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}")


def norm(e):
    return (e or "").strip().lower().removeprefix("mailto:").strip(" ;,.")


def trouver(motif):
    for dossier in (SOURCES, ICI):
        f = sorted(glob.glob(os.path.join(dossier, motif)))
        if f:
            return f[-1]
    return None


def emails_csv(chemin):
    with open(chemin, encoding="utf-8-sig") as f:
        return {norm(r.get("Email")) for r in csv.DictReader(f)} - {""}


def emails_inscriptions(chemin):
    wb = openpyxl.load_workbook(chemin, read_only=True)
    sortie = set()
    for ws in wb.worksheets:
        lignes = list(ws.iter_rows(values_only=True))
        if not lignes:
            continue
        for j, titre in enumerate(lignes[0]):
            if titre and "mail" in str(titre).lower():
                sortie |= {norm(str(l[j])) for l in lignes[1:] if l[j]}
    return sortie


def profil(categorie, prenom, campagnes, email):
    """(priorité, libellé) ou (None, raison d'exclusion)."""
    if categorie:
        if RE_HORS_CIBLE.search(prenom if prenom.lower().startswith("à toute l'équipe") else "") or \
                any(x in email for x in SOUS_CHAINES_INTERDITES):
            return None, "école, camping, gîte ou chambre d'hôtes"
        if categorie in CATEGORIES_EXCLUES:
            return None, f"catégorie exclue : {categorie}"
        return PRIO_CATEGORIE.get(categorie, 5), categorie
    nom = prenom if prenom.lower().startswith("à toute l'équipe") else ""
    if RE_HORS_CIBLE.search(nom) or any(x in email for x in SOUS_CHAINES_INTERDITES):
        return None, "école, camping, gîte ou chambre d'hôtes"
    if RE_RAPIDE.search(nom) or RE_RAPIDE.search(email.split("@")[0]):
        return None, "PMU / pizzeria / restauration rapide"
    if "Vague Cavistes" in campagnes:
        return 1, "Caviste (campagne Cavistes)"
    for prio, libelle, motif in REGLES_NOM:
        if re.search(motif, nom + " " + email.split("@")[0], re.I):
            return prio, libelle
    return 5, "Restaurant / CHR (sans catégorie)"


def main():
    master = sys.argv[1] if len(sys.argv) > 1 else trouver("*Master_tous_les_contacts*.xlsx")
    lundi = trouver("*CSV_ENVOI_LUNDI_4_LOTS_1*.csv")
    mardi = os.path.join(ICI, "NOUVEAUX_CONTACTS_CLAUDE_CODE_TOUS.csv")
    inscriptions = trouver("*Inscription*.xlsx")
    for nom, chemin in (("Master", master), ("Envoi lundi", lundi), ("Envoi mardi", mardi),
                        ("Inscriptions", inscriptions)):
        if not chemin or not os.path.exists(chemin):
            sys.exit(f"Fichier introuvable : {nom}")
    deja_envoyes = emails_csv(lundi) | emails_csv(mardi)
    inscrits = emails_inscriptions(inscriptions)

    ws = openpyxl.load_workbook(master, read_only=True)["Tous les contacts"]
    lignes = list(ws.iter_rows(values_only=True))
    ix = {k: i for i, k in enumerate(lignes[0])}
    rejets, candidats, vus = Counter(), [], set()
    for l in lignes[1:]:
        email = norm(l[ix["Email"]])
        statut = l[ix["Statut"]] or ""
        n = int(l[ix["Nb envois"]] or 0)
        prenom = (l[ix["Prénom"]] or "").strip() or "à toute l'équipe"
        if not RE_EMAIL.fullmatch(email):
            rejets["e-mail invalide"] += 1
        elif email in vus:
            rejets["doublon"] += 1
        elif "DÉSABONNÉ" in statut.upper():
            rejets["désabonné"] += 1
        elif "INSCRIT" in statut.upper() or l[ix["Inscrit"]] or email in inscrits:
            rejets["inscrit au salon"] += 1
        elif email in deja_envoyes:
            rejets["déjà envoyé lundi ou mardi"] += 1
        elif n < 1:
            rejets["jamais envoyé (Nb envois = 0)"] += 1
        else:
            prio, libelle = profil(l[ix["Catégorie"]], prenom, l[ix["Campagnes"]] or "", email)
            if prio is None:
                rejets[libelle if not libelle.startswith("catégorie") else "catégorie hors cible"] += 1
            else:
                candidats.append({"email": email, "prenom": prenom, "prio": prio, "profil": libelle,
                                  "envois": n})
        vus.add(email)

    # Meilleure priorité d'abord, puis les moins sollicités ; ordre du Master à égalité.
    candidats.sort(key=lambda c: (c["prio"], c["envois"]))
    total = TAILLE_LOT * len(LOTS)
    if len(candidats) < total:
        sys.exit(f"Seulement {len(candidats)} contacts éligibles pour {total} demandés.")
    retenus = candidats[:total]

    print(f"Master : {len(lignes) - 1} contacts · éligibles : {len(candidats)} · retenus : {total}")
    for raison, nb in rejets.most_common():
        print(f"  écartés — {raison} : {nb}")
    for i, fichier in enumerate(LOTS):
        lot = retenus[i * TAILLE_LOT:(i + 1) * TAILLE_LOT]
        with open(os.path.join(ICI, fichier), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["Email", "Prenom"])
            w.writerows((c["email"], c["prenom"]) for c in lot)
        print(f"\n## {fichier} — {len(lot)} contacts")
        print("  Priorités :", ", ".join(f"P{p} = {n}" for p, n in sorted(Counter(c['prio'] for c in lot).items())))
        print("  Envois précédents :", ", ".join(f"{e} envoi{'s' if e > 1 else ''} = {n}"
                                               for e, n in sorted(Counter(c['envois'] for c in lot).items())))
        for p, n in Counter(c["profil"] for c in lot).most_common():
            print(f"    {n:4d}  {p}")
    with open(os.path.join(ICI, "RELANCE_DETAILS.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Lot", "Email", "Prenom", "Priorite", "Profil", "Nb_envois_precedents"])
        for i, c in enumerate(retenus):
            w.writerow([LOTS[i // TAILLE_LOT], c["email"], c["prenom"], c["prio"], c["profil"], c["envois"]])


if __name__ == "__main__":
    main()
