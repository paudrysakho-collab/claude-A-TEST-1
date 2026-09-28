#!/usr/bin/env python3
"""Sourcing de nouveaux contacts pros pour le Salon du Vin du 5 octobre 2026
(Château de la Rairie, Pont-Saint-Martin).

Étapes :
    python sourcing_salon_vin.py liste-noire      # charge et compte les exclusions
    python sourcing_salon_vin.py test-prenoms     # vérifie le formateur de la colonne Prenom
    python sourcing_salon_vin.py collecter --max 100
    python sourcing_salon_vin.py verifier         # contrôle indépendant du livrable

Les 4 fichiers sources sont lus dans donnees_sources/ (non versionné).
Des sites supplémentaires peuvent être fournis dans candidats_sites.csv
(colonnes : nom,ville,url,categorie).
"""
import argparse
import csv
import glob
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import unicodedata
import urllib.robotparser
from urllib.parse import urljoin, urlparse, quote_plus

ICI = os.path.dirname(os.path.abspath(__file__))
DOSSIER_SOURCES = os.path.join(ICI, "donnees_sources")
DOSSIER_CACHE = os.path.join(ICI, "cache")
SORTIE = os.path.join(ICI, "NOUVEAUX_CONTACTS_CLAUDE_CODE.csv")
SORTIE_DETAILS = os.path.join(ICI, "NOUVEAUX_CONTACTS_DETAILS.csv")
EXCLURE_EN_PLUS = []  # autres fichiers Email,Prenom déjà livrés (option --exclure)
CANDIDATS = os.path.join(ICI, "candidats_sites.csv")

USER_AGENT = "Mozilla/5.0 (compatible; SalonVinRairie-sourcing/1.0)"
PAUSE_PAR_SITE = 1.5
PONT_SAINT_MARTIN = (47.1239, -1.5836)
RAYON_KM = 100.5  # 100 km, Sarzeau (100,3 km) toléré à la limite

# --------------------------------------------------------------------------
# Règles métier
# --------------------------------------------------------------------------
SOUS_CHAINES_INTERDITES = ["le21pornic", "domainedeliziec", "camping", "gite",
                           "greta", "cfa", "chambre-hote"]
LOCAUX_TECHNIQUES = ("noreply", "no-reply", "nepasrepondre", "webmaster", "rgpd",
                     "dpo", "privacy", "postmaster", "abuse", "support", "wordpress",
                     "sentry", "example", "exemple", "votre", "your", "nom@", "email@",
                     "donneespersonnelles", "donnees-personnelles", "nomprenom", "prenom.nom",
                     "mairie", "economie", "presse")
EXTENSIONS_FICHIERS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")

WEBMAILS = {"gmail.com", "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr", "laposte.net",
            "hotmail.com", "hotmail.fr", "outlook.com", "outlook.fr", "yahoo.fr",
            "yahoo.com", "icloud.com", "bbox.fr", "live.fr", "live.com", "aol.com",
            "aol.fr", "neuf.fr", "club-internet.fr", "numericable.fr", "gmx.fr",
            "gmx.com", "me.com", "msn.com", "protonmail.com", "proton.me", "cegetel.net",
            "9online.fr", "aliceadsl.fr", "orange.com"}

# Réseaux multi-magasins : chaque magasin est un acheteur distinct, on ne bloque
# donc pas un nouveau magasin parce qu'un autre magasin du réseau est déjà connu.
RESEAUX = ("biocoop", "caba", "cavavin", "nicolas", "vandb", "v-and-b", "lavieclaire",
           "la-vie-claire", "satoriz", "naturalia", "biocbon", "bio-c-bon", "intercaves",
           "repairedebacchus", "cellier", "marchedesterroirs", "latourdepise", "maisondv",
           "bondici", "laperledesdieux", "beillevaire", "lacabaneafromages", "comptoirdesvignes",
           "cavesbourdin", "lesvinsdepaulo", "papillesetpapillotes", "vinovini", "marcheauxvins", "comptoirdesvins", "leopold", "hameauxbio", "cervoiserie", "chopeetcompagnie")

HOTES_AGENCES = ("wix", "ovh", "o2switch", "ionos", "1and1", "godaddy", "jimdo", "hostinger",
                 "gandi", "squarespace", "shopify", "webflow", "pagesjaunes", "solocal",
                 "petitfute", "tripadvisor", "facebook", "instagram", "google", "sentry", "mondomaine",
                 "wordpress", "e-monsite", "sitew", "webself", "local.fr", "duckduckgo")

MOTS_METIER = {
    "Caviste": ["caviste", "cave à vin", "cave a vin", "vins et spiritueux", "bar à vin",
                "bar a vin", "cave à manger", "vins naturels", "vigneron"],
    "Épicerie fine": ["épicerie fine", "epicerie fine", "comptoir gourmand", "produits du terroir",
                      "coffret", "épicerie", "epicerie", "délicatesse"],
    "Magasin bio": ["biocoop", "magasin bio", "produits bio", "agriculture biologique", "vrac"],
    "Fromagerie": ["fromagerie", "fromager", "crèmerie", "cremerie", "affineur"],
    "Torréfacteur": ["torréfacteur", "torrefacteur", "torréfaction", "brûlerie", "brulerie"],
    "Restaurant": ["bistronomi", "maître restaurateur", "maitre restaurateur", "bistrot",
                   "restaurant", "carte des vins", "fait maison", "cuisine de saison"],
    "Bar à vins / tapas": ["bar à vins", "bar a vins", "tapas"],
    "Cave à bières / spiritueux": ["bières", "bieres", "whisky", "rhum", "spiritueux"],
    "Traiteur": ["traiteur", "réception", "mariage"],
    "Hôtel-restaurant": ["hôtel-restaurant", "hotel-restaurant", "hôtel restaurant", "logis"],
}
MOTS_INTERDITS = ["camping", "gîte", "gite rural", "chambre d'hôte", "chambres d'hôtes",
                  "chambre d'hote", "lycée", "lycee", "école", "cfa ", "greta", "fast-food",
                  "fast food", "kebab", "tacos", "burger king", "mcdonald", "pizza à emporter",
                  "sandwicherie", "auto-école", "coiffure", "immobili", "pharmacie"]

# Villes cibles (sous-exploitées d'abord), avec coordonnées de secours.
VILLES = [
    # (ville, code postal, lat, lon, département)
    ("Noirmoutier-en-l'Île", "85330", 47.0009, -2.2500, "85"),
    ("Savenay", "44260", 47.3606, -1.9428, "44"),
    ("Muzillac", "56190", 47.5542, -2.4800, "56"),
    ("Vallet", "44330", 47.1617, -1.2661, "44"),
    ("Châteaubriant", "44110", 47.7172, -1.3761, "44"),
    ("Challans", "85300", 46.8467, -1.8783, "85"),
    ("Saint-Brevin-les-Pins", "44250", 47.2464, -2.1667, "44"),
    ("Le Croisic", "44490", 47.2919, -2.5100, "44"),
    ("Pornichet", "44380", 47.2486, -2.3394, "44"),
    ("Fontenay-le-Comte", "85200", 46.4661, -0.8064, "85"),
    ("Clisson", "44190", 47.0869, -1.2819, "44"),
    ("Blain", "44130", 47.4764, -1.7625, "44"),
    ("Basse-Goulaine", "44115", 47.2117, -1.4675, "44"),
    ("Machecoul-Saint-Même", "44270", 46.9931, -1.8214, "44"),
    ("Vertou", "44120", 47.1689, -1.4697, "44"),
    ("Beaupréau-en-Mauges", "49600", 47.2036, -0.9886, "49"),
    ("Chemillé-en-Anjou", "49120", 47.2139, -0.7275, "49"),
    ("Guérande", "44350", 47.3283, -2.4294, "44"),
    ("La Baule-Escoublac", "44500", 47.2867, -2.3908, "44"),
    ("Saint-Nazaire", "44600", 47.2736, -2.2139, "44"),
    ("Ancenis-Saint-Géréon", "44150", 47.3656, -1.1775, "44"),
    ("Pornic", "44210", 47.1156, -2.1025, "44"),
    ("Saint-Jean-de-Monts", "85160", 46.7911, -2.0617, "85"),
    ("Saint-Gilles-Croix-de-Vie", "85800", 46.6975, -1.9456, "85"),
    ("Les Sables-d'Olonne", "85100", 46.4972, -1.7833, "85"),
    ("La Roche-sur-Yon", "85000", 46.6706, -1.4269, "85"),
    ("Montaigu-Vendée", "85600", 46.9731, -1.3094, "85"),
    ("Les Herbiers", "85500", 46.8711, -1.0136, "85"),
    ("Cholet", "49300", 47.0600, -0.8792, "49"),
    ("Saumur", "49400", 47.2600, -0.0769, "49"),
    ("Doué-en-Anjou", "49700", 47.1928, -0.2758, "49"),
    ("Vannes", "56000", 47.6586, -2.7600, "56"),
    ("Sarzeau", "56370", 47.5283, -2.7692, "56"),
    ("Auray", "56400", 47.6678, -2.9819, "56"),
    # Communes voisines (secours quand l'API géographique ne répond pas)
    ("Sèvremoine", "49450", 47.1230, -0.9920, "49"),
    ("Orée-d'Anjou", "49270", 47.3370, -1.2640, "49"),
    ("Mauges-sur-Loire", "49410", 47.3610, -1.0160, "49"),
    ("Montrevault-sur-Èvre", "49110", 47.2590, -1.0460, "49"),
    ("Chalonnes-sur-Loire", "49290", 47.3500, -0.7620, "49"),
    ("Lys-Haut-Layon", "49310", 47.1460, -0.5290, "49"),
    ("Mûrs-Érigné", "49610", 47.4000, -0.5510, "49"),
    ("Sèvremont", "85700", 46.8330, -0.8630, "85"),
    ("Pouzauges", "85700", 46.7810, -0.8370, "85"),
    ("Mortagne-sur-Sèvre", "85290", 46.9920, -0.9500, "85"),
    ("Chantonnay", "85110", 46.6870, -1.0500, "85"),
    ("Luçon", "85400", 46.4550, -1.1660, "85"),
    ("Mareuil-sur-Lay-Dissais", "85320", 46.5360, -1.2250, "85"),
    ("Essarts-en-Bocage", "85140", 46.7730, -1.2290, "85"),
    ("Aizenay", "85190", 46.7400, -1.6080, "85"),
    ("Saint-Hilaire-de-Riez", "85270", 46.7210, -1.9460, "85"),
    ("Talmont-Saint-Hilaire", "85440", 46.4660, -1.6170, "85"),
    ("La Barre-de-Monts", "85550", 46.8830, -2.1210, "85"),
    ("Beauvoir-sur-Mer", "85230", 46.9120, -2.0420, "85"),
    ("L'Île-d'Yeu", "85350", 46.7220, -2.3480, "85"),
    ("Mouzillon", "44330", 47.1400, -1.2810, "44"),
    ("Saint-Père-en-Retz", "44320", 47.2060, -2.0410, "44"),
    ("Le Pouliguen", "44510", 47.2700, -2.4310, "44"),
    ("La Turballe", "44420", 47.3470, -2.5080, "44"),
    ("Herbignac", "44410", 47.4480, -2.3180, "44"),
    ("Pontchâteau", "44160", 47.4370, -2.0890, "44"),
    ("Nort-sur-Erdre", "44390", 47.4380, -1.4980, "44"),
    ("Nozay", "44170", 47.5650, -1.6270, "44"),
    ("Derval", "44590", 47.6670, -1.6690, "44"),
    ("Loireauxence", "44370", 47.3850, -1.0290, "44"),
    ("Saint-Philbert-de-Grand-Lieu", "44310", 47.0360, -1.6400, "44"),
    ("Legé", "44650", 46.8850, -1.5980, "44"),
    ("Le Pellerin", "44640", 47.1990, -1.7550, "44"),
    ("Paimboeuf", "44560", 47.2880, -2.0300, "44"),
    ("Damgan", "56750", 47.5190, -2.5760, "56"),
    ("Arzal", "56190", 47.5180, -2.3780, "56"),
    ("La Roche-Bernard", "56130", 47.5190, -2.3000, "56"),
    ("Notre-Dame-de-Monts", "85690", 46.8310, -2.1310, "85"),
    ("Gétigné", "44190", 47.0770, -1.2480, "44"),
    ("Gorges", "44190", 47.1010, -1.3030, "44"),
    ("Saint-Lyphard", "44410", 47.3980, -2.3050, "44"),
    ("Saint-Michel-Chef-Chef", "44730", 47.1810, -2.1490, "44"),
    ("La Chapelle-Glain", "44670", 47.6200, -1.1950, "44"),
    ("Saint-Paul-Mont-Penit", "85670", 46.8030, -1.6700, "85"),
    ("Rocheservière", "85620", 46.9390, -1.5090, "85"),
    ("Le Poiré-sur-Vie", "85170", 46.7680, -1.5090, "85"),
    ("Chaumes-en-Retz", "44320", 47.1470, -1.9690, "44"),
    ("Port-Saint-Père", "44710", 47.1320, -1.7490, "44"),
    ("Préfailles", "44770", 47.1330, -2.2170, "44"),
    ("Billiers", "56190", 47.5330, -2.4830, "56"),
    ("Jard-sur-Mer", "85520", 46.4140, -1.5750, "85"),
    ("La Tranche-sur-Mer", "85360", 46.3440, -1.4390, "85"),
    ("Brétignolles-sur-Mer", "85470", 46.6320, -1.8630, "85"),
    ("Le Loroux-Bottereau", "44430", 47.2380, -1.3470, "44"),
    ("Saint-Julien-de-Concelles", "44450", 47.2530, -1.3850, "44"),
]
PROFILS_RECHERCHE = ["épicerie fine", "caviste", "magasin bio", "fromagerie",
                     "torréfacteur café", "restaurant bistronomique", "maître restaurateur",
                     "bar à vins", "traiteur", "cave à bières"]
PETIT_FUTE_DEPARTEMENTS = {
    "44": "https://www.petitfute.com/d55-loire-atlantique/",
    "85": "https://www.petitfute.com/d76-vendee/",
    "49": "https://www.petitfute.com/d73-maine-et-loire/",
}
MOTS_RUBRIQUES_PF = ("c650", "produits-gourmands", "epicerie", "cave", "vins", "fromag",
                     "gastronomie", "terroir", "c1165", "bistrot", "restaurant")

# --------------------------------------------------------------------------
# Outils texte
# --------------------------------------------------------------------------
def sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normaliser_email(e):
    from urllib.parse import unquote
    e = unquote((e or "").strip()).strip().lower().replace("[^@]", "@")
    e = re.sub(r"^mailto:", "", e).split("?")[0].strip()
    return e.strip(" .,;:()<>[]\"'")


def domaine(email):
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def cle_nom(nom):
    """Clé de comparaison d'un nom d'établissement : sans accents, articles ni formes juridiques."""
    s = sans_accents((nom or "").lower())
    s = re.sub(r"\b(sarl|sas|sasu|eurl|sa|snc|ets|etablissements?)\b", " ", s)
    s = re.sub(r"^(l'|la |le |les |au |aux |a la |chez )", "", s.strip())
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


MOTS_VIDES = {"restaurant", "brasserie", "bistrot", "bistro", "hotel", "cave", "chez", "maison", "cafe",
              "bar", "les", "des", "aux", "and", "the", "sarl", "traiteur", "epicerie", "fromagerie"}


def lien_nom_domaine(nom, dom):
    """Vrai si un mot significatif du nom (ou le nom sans articles) apparaît dans le domaine."""
    d = re.sub(r"[^a-z0-9]", "", sans_accents(dom.rsplit(".", 1)[0].lower()))
    if not nom:
        return True
    if cle_nom(nom)[:6] in d:
        return True
    mots = [w for w in re.findall(r"[a-z0-9]+", sans_accents(nom.lower())) if len(w) >= 4 and w not in MOTS_VIDES]
    return any(w in d for w in mots)


def est_reseau(texte):
    t = sans_accents((texte or "").lower()).replace(" ", "")
    return any(r.replace("-", "") in t for r in RESEAUX)


def distance_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


# --------------------------------------------------------------------------
# 1. Liste noire
# --------------------------------------------------------------------------
def _trouver(motif):
    fichiers = sorted(glob.glob(os.path.join(DOSSIER_SOURCES, motif)))
    if not fichiers:
        sys.exit(f"Fichier introuvable dans {DOSSIER_SOURCES} : {motif}")
    return fichiers[-1]


def _lire_xlsx(chemin, feuille=None):
    import openpyxl
    wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    ws = wb[feuille] if feuille else wb.worksheets[0]
    lignes = ws.iter_rows(values_only=True)
    entete = [str(c).strip() if c is not None else "" for c in next(lignes)]
    return [dict(zip(entete, ["" if v is None else str(v) for v in l])) for l in lignes]


def _col(ligne, nom):
    """Lecture tolérante d'une colonne (espaces finaux dans les en-têtes Google Forms)."""
    for k, v in ligne.items():
        if k.strip() == nom.strip():
            return v
    return ""


RE_FORMULE = re.compile(r"^à toute l'équipe (?:de la |du |des |de l'|d'|de )(.+)$")


def charger_liste_noire(verbeux=True):
    master = _lire_xlsx(_trouver("*Master_tous_les_contacts*.xlsx"), "Tous les contacts")
    inscr = _lire_xlsx(_trouver("*Inscription*.xlsx"))
    fusion = list(csv.DictReader(open(_trouver("*CSV_ENVOI_FUSION_NEUFS*.csv"), encoding="utf-8-sig")))
    lundi = list(csv.DictReader(open(_trouver("*CSV_ENVOI_LUNDI_4_LOTS_1*.csv"), encoding="utf-8-sig")))

    par_source = {
        "Master": {normaliser_email(r.get("Email")) for r in master},
        "Fusion": {normaliser_email(r.get("Email")) for r in fusion},
        "Lundi": {normaliser_email(r.get("Email")) for r in lundi},
        "Inscrits": {normaliser_email(_col(r, c)) for r in inscr
                     for c in ("Adresse e-mail à laquelle vous souhaitez communiquer", "Adresse e-mail")},
    }
    for chemin in EXCLURE_EN_PLUS:
        lignes = list(csv.DictReader(open(chemin, encoding="utf-8-sig")))
        par_source[os.path.basename(chemin)[:9]] = {normaliser_email(r.get("Email")) for r in lignes}
        fusion = fusion + lignes  # leurs formules « à toute l'équipe de X » alimentent aussi les noms connus
    noms_livres = set()
    for chemin in EXCLURE_EN_PLUS:
        details = chemin.replace(".csv", "_DETAILS.csv")
        if not os.path.exists(details) and chemin.endswith("CLAUDE_CODE.csv"):
            details = os.path.join(os.path.dirname(chemin), "NOUVEAUX_CONTACTS_DETAILS.csv")
        if os.path.exists(details):
            noms_livres |= {cle_nom(r.get("Etablissement")) for r in csv.DictReader(open(details, encoding="utf-8"))}
    emails = set().union(*par_source.values()) - {""}

    domaines = {domaine(e) for e in emails} - WEBMAILS - {""}
    noms = set()
    for r in master:
        noms.add(cle_nom(r.get("Établissement")))
    for r in inscr:
        noms.add(cle_nom(_col(r, "Nom de la société / Établissement")))
    for r in fusion + lundi:
        m = RE_FORMULE.match((r.get("Prenom") or "").strip())
        if m:
            noms.add(cle_nom(m.group(1)))
    noms |= noms_livres
    noms = {n for n in noms if len(n) >= 4}

    if verbeux:
        for k, v in par_source.items():
            print(f"  {k:9s}: {len(v - {''}):5d} e-mails")
        print(f"  TOTAL liste noire : {len(emails)} e-mails uniques, "
              f"{len(domaines)} domaines pros, {len(noms)} noms d'établissements")
    generiques = {"contact", "info", "infos", "bonjour", "hello", "accueil", "reservation", "reservations",
                  "resa", "commande", "commandes", "restaurant", "cave", "boutique", "magasin", "direction",
                  "gerance", "admin", "office", "mail", "email", "traiteur", "epicerie", "fromagerie"}
    locaux = {e.split("@")[0] for e in emails} - generiques
    locaux = {l for l in locaux if len(l) >= 6}
    return {"emails": emails, "domaines": domaines, "noms": noms, "locaux": locaux}


def motif_rejet(email, nom, ln):
    """Renvoie la raison du rejet, ou None si l'adresse est acceptable."""
    e = normaliser_email(email)
    if not re.fullmatch(r"[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}", e):
        return "format invalide"
    if e in ln["emails"]:
        return "doublon (déjà dans les 4 fichiers)"
    if any(x in e for x in EXCLUSIONS_VALIDEES):
        return "exclu après validation (chaîne, snack, cuisine étrangère)"
    for s in SOUS_CHAINES_INTERDITES:
        if s in e:
            return f"sous-chaîne interdite « {s} »"
    local, dom = e.split("@", 1)
    if local.startswith(LOCAUX_TECHNIQUES) or e.endswith(EXTENSIONS_FICHIERS):
        return "adresse technique"
    if any(h in dom for h in HOTES_AGENCES):
        return "adresse d'hébergeur ou d'annuaire"
    reseau = est_reseau(dom) or est_reseau(nom)
    if dom in ln["domaines"] and not reseau:
        return "établissement déjà connu (même domaine)"
    if local in ln.get("locaux", ()) and not reseau:
        return "établissement déjà connu (même adresse, autre fournisseur)"
    if "racines" not in ln:
        ln["racines"] = {d.rsplit(".", 1)[0] for d in ln["domaines"]}
    if dom.rsplit(".", 1)[0] in ln["racines"] and not reseau:
        return "établissement déjà connu (même nom de domaine, autre extension)"
    if nom and cle_nom(nom) in ln["noms"] and not reseau:
        return "établissement déjà connu (même nom)"
    return None


# --------------------------------------------------------------------------
# 2. Colonne Prenom
# --------------------------------------------------------------------------
PETITS_MOTS = {"de", "du", "des", "la", "le", "les", "et", "à", "a", "aux", "au", "en", "sur",
               "d'", "l'"}
GENRE = {  # nom commun en tête -> article contracté
    "de la": ["cave", "fromagerie", "maison", "table", "cremerie", "brasserie", "boutique",
              "cabane", "ferme", "halle", "taverne", "grange", "terrasse", "brulerie", "cuisine",
              "boite", "cantine", "guinguette", "petite", "belle", "villa", "coop", "cooperative",
              "torrefaction", "marmite", "fabrique", "bouteille", "vigne", "source", "bergerie"],
    "du": ["comptoir", "bistrot", "bistro", "restaurant", "cellier", "bar", "domaine", "marche",
           "moulin", "relais", "chai", "cafe", "petit", "grand", "jardin", "garde-manger",
           "panier", "caveau", "traiteur", "manoir", "chateau", "local", "zinc", "pub", "clos",
           "coin", "quai", "vieux", "resto", "salon", "fournil", "p'tit", "ptit"],
    "des": ["caves", "chais", "saveurs", "delices", "halles", "jardins", "terroirs", "vins",
            "gourmandises", "fromages", "celliers", "comptoirs", "tables", "copains", "bocaux"],
    "de l'": ["epicerie", "auberge", "hotel", "atelier", "estaminet", "echoppe", "entrepot",
              "ecurie", "herboristerie", "amphore", "ardoise", "escale", "etable", "annexe",
              "oustal", "instant", "ile", "orangerie", "abri"],
}
RE_FORME_JURIDIQUE = re.compile(r"\b(SARL|SAS|SASU|EURL|SA|SNC|SCEA|EARL|GAEC)\b\.?", re.I)
VOYELLES = "aeiouyhàâäéèêëîïôöùûüAEIOUYHÀÂÄÉÈÊËÎÏÔÖÙÛÜ"


def casse_propre(nom):
    """Remet en casse normale un nom tout en majuscules ou tout en minuscules."""
    if nom != nom.upper() and nom != nom.lower():
        # corrige « L'atelier » -> « L'Atelier » dans un nom par ailleurs bien écrit
        return re.sub(r"\b([LlDd])'([a-zà-ÿ])", lambda m: m.group(1) + "'" + m.group(2).upper(), nom)
    mots = []
    for i, m in enumerate(nom.lower().split()):
        if i > 0 and m in PETITS_MOTS:
            mots.append(m)
        elif "'" in m:
            a, b = m.split("'", 1)
            mots.append(a + "'" + b[:1].upper() + b[1:] if a in ("l", "d") and i > 0
                        else a[:1].upper() + a[1:] + "'" + b[:1].upper() + b[1:])
        else:
            mots.append("-".join(p[:1].upper() + p[1:] for p in m.split("-")))
    return " ".join(mots)


def formule_equipe(nom):
    """Construit « à toute l'équipe de la/du/des/de l'/de X » à partir d'un nom brut."""
    n = RE_FORME_JURIDIQUE.sub("", (nom or "").replace("’", "'")).strip(" -–,.")
    n = re.sub(r"\s+", " ", n)
    if not n or len(n) > 60 or len(n) < 2 or re.search(r"[@/|]|http", n):
        return "à toute l'équipe"
    n = casse_propre(n)
    bas = n.lower()
    if bas.startswith("la "):
        return f"à toute l'équipe de la {n[3:]}"
    if bas.startswith("le "):
        return f"à toute l'équipe du {n[3:]}"
    if bas.startswith("les "):
        return f"à toute l'équipe des {n[4:]}"
    if bas.startswith(("l'", "l’")):
        reste = n[2:]
        return f"à toute l'équipe de l'{reste[:1].upper()}{reste[1:]}"
    premier = sans_accents(bas.split()[0]).strip("'’").split("-")[0]  # « Hôtel-Restaurant » -> « hotel »
    for article, mots in GENRE.items():
        if premier in mots:
            return f"à toute l'équipe {article}{'' if article.endswith(chr(39)) else ' '}{n}"
    if n[0] in VOYELLES and not n.lower().startswith(("hu", "ha", "he", "ho", "hi")):
        return f"à toute l'équipe d'{n}"
    return f"à toute l'équipe de {n}"


PRENOMS_FR = set("""
adele adrien agathe agnes alain alexandra alexandre alexis alice aline amandine amelie anais andre
angelique anne annick anthony antoine arnaud aude audrey aurelie aurelien axel baptiste benedicte
benjamin benoit bernard bertrand brigitte bruno camille carole caroline catherine cecile cedric celine
chantal charles charlotte christelle christian christine christophe claire clara claude clement
clemence corinne coralie cyril damien daniel david delphine denis didier dominique edouard elise
elodie emilie emeline emma emmanuel emmanuelle eric estelle etienne fabien fabienne fabrice fanny
florence florent florian francis franck francois francoise frederic gael gaelle gaetan gerard
gilles gregory guillaume guy helene herve hugo isabelle jacques jean jeanne jeremie jeremy jerome
joel johanna jonathan joseph julie julien juliette justine karine kevin laetitia laure laurence
laurent lea leo loic lucas lucie ludovic magali manon marc marie marine marion martine mathieu
mathilde matthieu maxime melanie michael michel mickael mylene nadine nathalie nicolas noemie olivier
pascal pascale patrice patricia patrick paul pauline philippe pierre quentin raphael regis remi
renaud richard robert romain sabrina sandrine sarah sebastien serge severine simon solene sophie
stephane stephanie sylvain sylvie thibault thierry thomas valentin valerie vanessa veronique
victor vincent virginie xavier yann yannick yves yvan zoe
""".split())


ACCENTS = {sans_accents(p).lower(): p for p in """
Adèle Agnès Amélie Anaïs André Angélique Aurélie Aurélien Bénédicte Benoît Cécile Cédric Céline Chloé
Clément Clémence Élodie Émilie Émeline Emmanuelle Étienne Françoise François Frédéric Gaël Gaëlle Gaëtan
Gérard Grégory Hélène Hervé Jérémie Jérémy Jérôme Joël Laëtitia Léa Léo Loïc Mélanie Mickaël Mylène Noémie
Pascale Raphaël Régis Rémi Sébastien Séverine Solène Stéphane Stéphanie Thibault Valérie Véronique Zoé
""".split()}


def joli_prenom(p):
    p = ACCENTS.get(sans_accents(p).lower(), p)
    return "-".join(x[:1].upper() + x[1:].lower() for x in p.split("-"))


def trouver_prenom(texte_mentions, email):
    """Prénom du gérant si on le trouve de façon fiable, sinon None."""
    if texte_mentions:
        m = re.search(r"(?i:directeur|directrice|responsable)\s+(?i:de)\s+(?i:la\s+)?(?i:publication)\s*:?\s*"
                      r"(?:M\.|Mme|Madame|Monsieur)?\s*([A-ZÉÈÂ][a-zéèêëàâîïôûüç]+(?:-[A-ZÉ][a-zéèêëç]+)?)\s+"
                      r"[A-ZÉ][A-Za-zÉéèêëàâîïôûüç-]+", texte_mentions)
        if m and sans_accents(m.group(1).lower()) in PRENOMS_FR:
            return joli_prenom(m.group(1))
        m = re.search(r"(?i:gérante|gérant|fondatrice|fondateur|sommelière|sommelier)\s*:?\s*"
                      r"([A-ZÉ][a-zéèêëàâîïôûüç]+)\s+[A-ZÉ][A-Za-zé-]+", texte_mentions)
        if m and sans_accents(m.group(1).lower()) in PRENOMS_FR:
            return joli_prenom(m.group(1))
    local = email.split("@")[0]
    tete = re.split(r"[._-]", local)[0]
    if "." in local or "_" in local or "-" in local:
        if sans_accents(tete.lower()) in PRENOMS_FR:
            return joli_prenom(tete)
    return None


def test_prenoms():
    cas = {
        "La Cave Sablaise": "à toute l'équipe de la Cave Sablaise",
        "Le Petit Tonneau": "à toute l'équipe du Petit Tonneau",
        "Les Caves du Granit Bleu": "à toute l'équipe des Caves du Granit Bleu",
        "L'Octave": "à toute l'équipe de l'Octave",
        "Chez Milo": "à toute l'équipe de Chez Milo",
        "Au Gourmet Vendéen": "à toute l'équipe d'Au Gourmet Vendéen",
        "Fromagerie Beillevaire": "à toute l'équipe de la Fromagerie Beillevaire",
        "Comptoir de la Bière": "à toute l'équipe du Comptoir de la Bière",
        "Épicerie Racynes": "à toute l'équipe de l'Épicerie Racynes",
        "Biocoop Les Herbiers": "à toute l'équipe de Biocoop Les Herbiers",
        "CAVE SABLAISE SARL": "à toute l'équipe de la Cave Sablaise",
        "Caves du Trégor": "à toute l'équipe des Caves du Trégor",
        "Auberge de Poupet": "à toute l'équipe de l'Auberge de Poupet",
        "Brasserie des Halles": "à toute l'équipe de la Brasserie des Halles",
        "EPICERIE DES MAINES": "à toute l'équipe de l'Epicerie des Maines",
        "Vinochio": "à toute l'équipe de Vinochio",
        "Une Bonne Bouteille": "à toute l'équipe d'Une Bonne Bouteille",
        "": "à toute l'équipe",
    }
    ok = 0
    for nom, attendu in cas.items():
        obtenu = formule_equipe(nom)
        statut = "OK " if obtenu == attendu else "KO "
        ok += obtenu == attendu
        print(f"  {statut} {nom!r:32s} -> {obtenu}" + ("" if obtenu == attendu else f"   (attendu : {attendu})"))
    for mentions, email, attendu in [
        ("Directeur de la publication : Julien Moreau", "contact@x.fr", "Julien"),
        ("", "sophie.martin@gmail.com", "Sophie"),
        ("", "cave.indigenes@gmail.com", None),
        ("Gérante : Hélène Durand", "info@y.fr", "Hélène"),
    ]:
        obtenu = trouver_prenom(mentions, email)
        ok += obtenu == attendu
        print(f"  {'OK ' if obtenu == attendu else 'KO '} prénom({email}) -> {obtenu}")
    total = len(cas) + 4
    print(f"  {ok}/{total} tests réussis")
    return ok == total


# --------------------------------------------------------------------------
# 3. Accès web poli (cache, robots.txt, pause par site)
# --------------------------------------------------------------------------
import threading
_VERROU_HOTES = threading.Lock()
_DERNIER_APPEL = {}  # hôte -> heure du dernier appel, partagé par tous les robots (politesse)


class Navigateur:
    def __init__(self):
        import requests
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"})
        self.dernier = {}
        self.robots = {}
        self.bloques = {}
        os.makedirs(DOSSIER_CACHE, exist_ok=True)

    def _autorise(self, url):
        hote = urlparse(url).scheme + "://" + urlparse(url).netloc
        if hote not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(hote + "/robots.txt", timeout=10)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:
                rp.parse([])
            self.robots[hote] = rp
        return self.robots[hote].can_fetch(USER_AGENT, url)

    def get(self, url):
        cache = os.path.join(DOSSIER_CACHE, hashlib.sha1(url.encode()).hexdigest() + ".html")
        echec = cache[:-5] + ".echec"
        if os.path.exists(cache):
            return open(cache, encoding="utf-8", errors="ignore").read()
        if os.path.exists(echec):  # page déjà tentée sans succès : on ne réessaie pas
            return None
        hote = urlparse(url).netloc
        if not self._autorise(url):
            return None
        while True:  # au plus une requête toutes les PAUSE_PAR_SITE secondes par site, tous robots confondus
            with _VERROU_HOTES:
                attente = PAUSE_PAR_SITE - (time.time() - _DERNIER_APPEL.get(hote, 0))
                if attente <= 0:
                    _DERNIER_APPEL[hote] = time.time()
                    break
            time.sleep(attente)
        try:
            r = self.s.get(url, timeout=15)
        except Exception as ex:
            self.bloques[hote] = str(ex)[:80]
            open(echec, "w").write(str(ex)[:200])
            return None
        if r.status_code in (403, 429, 503):
            self.bloques[hote] = f"HTTP {r.status_code}"
            return None
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
            open(echec, "w").write(str(r.status_code))
            return None
        r.encoding = r.encoding or r.apparent_encoding
        open(cache, "w", encoding="utf-8").write(r.text)
        return r.text

    def a_un_mx(self, dom):
        if dom in WEBMAILS:
            return True
        cle = os.path.join(DOSSIER_CACHE, "mx_" + dom)
        if os.path.exists(cle):
            return open(cle).read() == "1"
        for url in (f"https://dns.google/resolve?name={dom}&type=MX",
                    f"https://cloudflare-dns.com/dns-query?name={dom}&type=MX"):
            try:
                j = self.s.get(url, timeout=10, headers={"Accept": "application/dns-json"}).json()
                ok = any(a.get("type") == 15 for a in j.get("Answer", []))
                break
            except Exception:
                continue
        else:
            return True  # DNS indisponible : on ne rejette pas sur ce seul critère
        open(cle, "w").write("1" if ok else "0")
        return ok


# --------------------------------------------------------------------------
# 4. Extraction des e-mails d'un site
# --------------------------------------------------------------------------
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CHEMINS_FIXES = ("/contact", "/pages/contact", "/mentions-legales", "/policies/legal-notice")
PAGES_CONTACT = ("contact", "nous-contacter", "mentions", "legal", "qui-sommes", "a-propos",
                 "apropos", "about", "equipe", "infos-pratiques", "acces")


def texte_et_liens(html, base):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    mailtos = [a["href"] for a in soup.select("a[href^='mailto:']")]
    for el in soup.select("[data-cfemail]"):
        code = bytes.fromhex(el["data-cfemail"])
        mailtos.append("".join(chr(b ^ code[0]) for b in code[1:]))
    liens = [urljoin(base, a["href"]) for a in soup.select("a[href]")]
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    titre = soup.title.get_text(" ", strip=True) if soup.title else ""
    return soup.get_text(" ", strip=True), mailtos, liens, titre


def desobfusquer(texte):
    texte = texte.replace("[^@]", "@")  # masquage utilisé par certains sites de mairie
    t = re.sub(r"\s*[\[\(\{]\s*(?:at|arobase|@)\s*[\]\)\}]\s*", "@", texte, flags=re.I)
    t = re.sub(r"\s*[\[\(\{]\s*(?:dot|point)\s*[\]\)\}]\s*", ".", t, flags=re.I)
    return t


def explorer_site(nav, url):
    """Visite l'accueil et les pages contact/mentions ; renvoie emails (avec URL source) et textes."""
    accueil = nav.get(url)
    if not accueil:
        return None
    hote = urlparse(url).netloc.replace("www.", "")
    pages = [(url, accueil)]
    _, _, liens, titre = texte_et_liens(accueil, url)
    vus = {url}
    for l in liens:
        if urlparse(l).netloc.replace("www.", "") == hote and l not in vus \
                and any(k in l.lower() for k in PAGES_CONTACT) and len(pages) < 6:
            vus.add(l)
            h = nav.get(l)
            if h:
                pages.append((l, h))
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for chemin in CHEMINS_FIXES:
        if len(pages) >= 8:
            break
        l = base + chemin
        if l not in vus:
            vus.add(l)
            h = nav.get(l)
            if h:
                pages.append((l, h))
    trouves, textes, mentions = {}, [], ""
    for u, h in pages:
        texte, mailtos, _, _ = texte_et_liens(h, u)
        textes.append(texte)
        if any(k in u.lower() for k in ("mentions", "legal", "qui-sommes", "a-propos", "about")):
            mentions += " " + texte
        for e in [normaliser_email(m) for m in mailtos] + \
                 [normaliser_email(m) for m in RE_EMAIL.findall(desobfusquer(texte))]:
            if e and e not in trouves:
                trouves[e] = u
    return {"emails": trouves, "texte": " ".join(textes), "mentions": mentions,
            "titre": titre, "hote": hote}


# --------------------------------------------------------------------------
# 5. Qualification
# --------------------------------------------------------------------------
def blocs_annuaire(html):
    """Découpe une page d'annuaire : pour chaque e-mail, (email, nom, texte du bloc de l'établissement)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        t.decompose()
    sortie, vus = [], set()
    noeuds = [(a, normaliser_email(a.get("href", ""))) for a in soup.select("a[href^='mailto:']")]
    for el in soup.select("[data-cfemail]"):
        code = bytes.fromhex(el["data-cfemail"])
        noeuds.append((el, "".join(chr(b ^ code[0]) for b in code[1:]).lower()))
    for txt in soup.find_all(string=RE_EMAIL):
        for e in RE_EMAIL.findall(desobfusquer(str(txt))):
            noeuds.append((txt.parent, normaliser_email(e)))
    for noeud, email in noeuds:
        if not email or email in vus:
            continue
        vus.add(email)
        bloc = noeud
        while bloc.parent is not None:
            parent = bloc.parent
            emails_parent = {normaliser_email(x) for x in RE_EMAIL.findall(parent.get_text(" "))}
            emails_parent |= {normaliser_email(a.get("href", "")) for a in parent.select("a[href^='mailto:']")}
            if len(emails_parent - {email}) > 0 or len(parent.get_text(" ", strip=True)) > 1500:
                break
            bloc = parent
        titre = bloc.find(["h1", "h2", "h3", "h4", "h5", "strong", "b"])
        nom = titre.get_text(" ", strip=True) if titre else ""
        if not nom or "@" in nom or len(nom) > 70:
            lignes = [l.strip() for l in bloc.get_text("\n", strip=True).split("\n") if l.strip()]
            nom = next((l for l in lignes if "@" not in l and 2 < len(l) <= 70 and not re.search(r"\d{2}[ .]?\d{2}[ .]?\d{2}", l)), "")
        nom = re.split(r"\s[|•–]\s|\s×", nom)[0].strip(" ,-")
        sortie.append((email, nom, bloc.get_text(" ", strip=True)))
    return sortie


def qualifier(texte, titre, seuil=2):
    """(catégorie, raison_rejet). Catégorie None si le lieu ne parle pas de vin/bouche."""
    t = (titre + " " + texte).lower()
    tt = (titre or "").lower()
    for m in MOTS_INTERDITS:
        if m in tt or t.count(m) >= 3:
            return None, f"hors cible (« {m} »)"
    scores = {cat: sum(t.count(m) for m in mots) for cat, mots in MOTS_METIER.items()}
    cat, score = max(scores.items(), key=lambda x: x[1])
    if score < seuil:
        return None, "activité non liée au vin"
    if cat == "Restaurant" and not any(w in t for w in ("vin", "cave", "sommelier", "accord")):
        return None, "restaurant sans vin mis en avant"
    return cat, None


def localiser(texte, ville_hint=None):
    """Trouve un code postal de la zone dans la page ; renvoie (ville, cp, distance)."""
    cps = re.findall(r"\b(44|49|56|85)\s?(\d{3})\b", texte)
    table = {v[1]: v for v in VILLES}
    for a, b in cps:
        cp = a + b
        if cp in table:
            v = table[cp]
            return v[0], cp, distance_km(PONT_SAINT_MARTIN, (v[2], v[3]))
    if cps:
        cp = cps[0][0] + cps[0][1]
        return ville_hint or "", cp, None
    if ville_hint:
        for v in VILLES:
            if v[0] == ville_hint:
                return v[0], v[1], distance_km(PONT_SAINT_MARTIN, (v[2], v[3]))
    return None, None, None


def ville_connue(nom_ville, cp=None):
    """Distance via la table VILLES, à partir du nom de ville noté lors de la découverte."""
    cle = cle_nom(nom_ville)
    for v in VILLES:
        if cle and cle_nom(v[0]) == cle:
            return v[0], distance_km(PONT_SAINT_MARTIN, (v[2], v[3]))
    return nom_ville or "", None


def distance_par_cp(nav, cp):
    cle = os.path.join(DOSSIER_CACHE, "geo_" + cp)
    if os.path.exists(cle):
        d = json.load(open(cle))
    else:
        d = None
        try:
            d = nav.s.get(f"https://geo.api.gouv.fr/communes?codePostal={cp}&fields=nom,centre",
                          timeout=10).json()
            d = [{"nom": x["nom"], "lon": x["centre"]["coordinates"][0], "lat": x["centre"]["coordinates"][1]} for x in d]
        except Exception:
            try:
                j = nav.s.get(f"https://api-adresse.data.gouv.fr/search/?q={cp}&type=municipality&postcode={cp}&limit=1",
                              timeout=10).json()
                d = [{"nom": f["properties"]["city"], "lon": f["geometry"]["coordinates"][0],
                      "lat": f["geometry"]["coordinates"][1]} for f in j.get("features", [])]
            except Exception:
                return None, None
        json.dump(d, open(cle, "w"))
    if not d:
        return None, None
    x = d[0]
    if "centre" in x:  # ancien format du cache (geo.api.gouv.fr brut)
        x = {"nom": x["nom"], "lon": x["centre"]["coordinates"][0], "lat": x["centre"]["coordinates"][1]}
    return x["nom"], distance_km(PONT_SAINT_MARTIN, (x["lat"], x["lon"]))


# --------------------------------------------------------------------------
# 6. Découverte des sites à visiter
# --------------------------------------------------------------------------
def candidats_fichier():
    if not os.path.exists(CANDIDATS):
        return []
    return [dict(r, source="liste manuelle") for r in csv.DictReader(open(CANDIDATS, encoding="utf-8"))]


def candidats_petit_fute(nav, max_pages=60):
    """Parcourt les rubriques gourmandes du Petit Futé et récupère les liens vers les sites."""
    sortie, a_voir, vus = [], [], set()
    for dep, url in PETIT_FUTE_DEPARTEMENTS.items():
        a_voir.append((url, 0, dep))
    while a_voir and len(vus) < max_pages:
        url, prof, dep = a_voir.pop(0)
        if url in vus:
            continue
        vus.add(url)
        html = nav.get(url)
        if not html:
            continue
        texte, _, liens, titre = texte_et_liens(html, url)
        for l in liens:
            p = urlparse(l)
            if "petitfute" in p.netloc:
                if prof < 3 and any(k in l.lower() for k in MOTS_RUBRIQUES_PF) and l not in vus:
                    a_voir.append((l.split("#")[0], prof + 1, dep))
            elif p.scheme.startswith("http") and not any(h in p.netloc for h in HOTES_AGENCES):
                sortie.append({"nom": "", "ville": "", "url": f"{p.scheme}://{p.netloc}/",
                               "categorie": "", "source": url})
    bloque = [h for h in nav.bloques if "petitfute" in h]
    if bloque:
        print(f"  ⚠ Petit Futé refuse le robot : {nav.bloques[bloque[0]]}")
    return sortie


def candidats_recherche(nav, villes, profils, max_requetes=200):
    sortie, n = [], 0
    for v in villes:
        for p in profils:
            if n >= max_requetes:
                return sortie
            n += 1
            q = f"{p} {v[0]} {v[1]}"
            html = nav.get("https://html.duckduckgo.com/html/?q=" + quote_plus(q))
            if not html:
                if "html.duckduckgo.com" in nav.bloques:
                    print(f"  ⚠ Le moteur de recherche bloque le robot : {nav.bloques['html.duckduckgo.com']}")
                    return sortie
                continue
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.select("a.result__a"):
                href = a.get("href", "")
                m = re.search(r"uddg=([^&]+)", href)
                if m:
                    from urllib.parse import unquote
                    href = unquote(m.group(1))
                pu = urlparse(href)
                if pu.scheme.startswith("http") and not any(h in pu.netloc for h in HOTES_AGENCES + (
                        "tripadvisor", "thefork", "lafourchette", "mappy", "yelp", "wikipedia",
                        "bottin", "societe.com", "pappers", "ouest-france", "linternaute")):
                    sortie.append({"nom": a.get_text(" ", strip=True), "ville": v[0],
                                   "url": f"{pu.scheme}://{pu.netloc}/", "categorie": p,
                                   "source": "recherche : " + q})
    return sortie


VT_BASE = "https://www.vendee-tourisme.com/restaurants-en-vendee"
VT_FILTRES = ["/search_api_cluster_4/Maitre%20Restaurateur", "/search_api_cluster_3/Gastronomique",
              "/search_api_cluster_3/Traditionnel", "/search_api_cluster_3/Cuisine%20de%20la%20mer",
              "https://www.vendee-tourisme.com/hotels-en-vendee"]
RE_VT_FICHE = re.compile(r"https://www\.vendee-tourisme\.com/[a-z0-9-]+/[a-z0-9-]+/(?:respdl|hotpdl)\w+")
RE_HORS_PROFIL = re.compile(r"pizz|cr[eê]p|galette|bl[ée] noir|cuisine du monde|sur le pouce|restauration rapide|"
                            r"kebab|burger|sushi|asiat|snack|food.?truck|glacier|friterie|tacos|chinois|japonais|"
                            r"indien|vietnam|tha[iï]|wok|royal|misay|nhu|ristorante|trattoria|vesuvio|ibla|"
                            r"mie c[aâ]line|buffalo|fraiseraie|emportez|kyriad", re.I)


# Exclusions validées avec l'utilisateur (chaînes, snacks, cuisines étrangères) — 28/09/2026.
EXCLUSIONS_VALIDEES = ("les3brasseurs.com", "pankeming@", "frenzi.fr", "redzone-challans.fr",
                       "snack-a-manu@", "la-boucherie.fr",
                       "parthenay@")  # magasin du réseau situé à Parthenay (79), hors des 100 km


def candidats_vendee_tourisme(nav, max_pages=40):
    """Liste les fiches restaurants de Vendée Tourisme (Maître Restaurateur, gastronomique, traditionnel)."""
    fiches = []
    for filtre in VT_FILTRES:
        vues = set()
        for p in range(max_pages):
            base = filtre if filtre.startswith("http") else VT_BASE + filtre
            html = nav.get(base + (f"?page={p}" if p else "")) or ""
            nouvelles = [f for f in dict.fromkeys(RE_VT_FICHE.findall(html)) if f not in vues]
            if not nouvelles:
                break
            vues.update(nouvelles)
            fiches += [{"nom": "", "ville": "", "url": f, "categorie": "restaurant", "fiche": "tourinsoft",
                        "source": "Vendée Tourisme " + filtre.rsplit("/", 1)[-1].replace("%20", " ")}
                       for f in nouvelles]
    print(f"  Vendée Tourisme : {len(fiches)} fiches restaurants")
    return list({f["url"]: f for f in fiches}.values())


OT_LISTES = [  # (page de liste, profil)
    ("https://www.pornic.com/tous-les-restaurants.html", "restaurant"),
    ("https://www.pornic.com/boutiques-gourmandes-epiceries-fines.html", "commerce"),
    ("https://www.pornic.com/traiteur-destination-pornic-traiteurs.html", "traiteur"),
    ("https://www.pornic.com/commerces-services.html", "commerce"),
    ("https://www.saint-brevin.com/restaurants.html", "restaurant"),
    ("https://www.saint-brevin.com/commerces-services.html", "commerce"),
    ("https://www.saint-brevin.com/bars-discotheques.html", "bar"),
]


def candidats_offices_tourisme(nav, max_pages=40):
    """Fiches des offices de tourisme dont les pages exposent l'e-mail en données schema.org."""
    sortie = []
    for liste, profil in OT_LISTES:
        racine = liste.rsplit("/", 1)[0] + "/"
        vues = set()
        for p in range(1, max_pages + 1):
            html = nav.get(liste + (f"?page={p}" if p > 1 else "")) or ""
            fiches = [racine + f for f in dict.fromkeys(re.findall(r'href="([a-z0-9-]+\.html)\?origine_affinage', html))]
            nouvelles = [f for f in fiches if f not in vues]
            if not nouvelles:
                break
            vues.update(nouvelles)
            sortie += [{"nom": "", "ville": "", "url": f, "categorie": profil, "fiche": "ot",
                        "source": "Office de tourisme " + urlparse(liste).netloc} for f in nouvelles]
    sortie = list({x["url"]: x for x in sortie}.values())
    print(f"  Offices de tourisme (Pornic, Saint-Brevin) : {len(sortie)} fiches")
    return sortie


def lire_fiche_schema(html):
    """(nom, email, cp, texte) depuis le bloc schema.org (JSON-LD) d'une fiche d'office de tourisme."""
    for m in re.finditer(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", html, re.S):
        t = m.group(1)
        em = re.findall(r'"email"\s*:\s*"([^"]+)"', t)
        if em:
            nm = re.findall(r'"name"\s*:\s*"([^"]+)"', t)
            cp = re.findall(r'"postalCode"\s*:\s*"([^"]+)"', t)
            try:
                nom = json.loads('"' + nm[0] + '"') if nm else ""
            except ValueError:
                nom = nm[0].replace("\\", "") if nm else ""
            texte = re.sub(r"<[^>]+>", " ", html)
            return nom, normaliser_email(em[0].replace("\\/", "/")), (cp[0] if cp else ""), texte
    return "", "", "", ""


def lire_fiche_tourinsoft(html):
    """(nom, email, cp, type, texte) d'une fiche Vendée Tourisme."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    nom = h1.get_text(" ", strip=True) if h1 else ""
    # « Les Dunes - Restaurant traditionnel » -> « Les Dunes »
    court = re.sub(r"\s+-\s+(Restaurant|Gastronomique|Traiteur|Resto|Bar|La Table|Brasserie|Cuisine)\b.*$", "",
                   nom, flags=re.I).strip()
    # « Bar - Restaurant Le Bon Androie » : on ne garde pas un simple « Bar »
    nom = court if court.lower() not in ("bar", "restaurant", "brasserie", "hôtel", "hotel", "") \
        else re.sub(r"\s+-\s+", " ", nom)
    texte = soup.get_text(" ", strip=True)
    m = re.search(r"Envoyer un e-mail\s+([A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", texte)
    email = normaliser_email(m.group(1)) if m else ""
    contact = texte[texte.find("Contact"):] if "Contact" in texte else texte
    mcp = re.search(r"\b(85\d{3}|44\d{3}|49\d{3}|79\d{3}|17\d{3})\b", contact)
    # Le type (« Cuisine traditionnelle », « Pizzeria »…) suit le nom dans le bandeau de la fiche,
    # avant « Voir sur la carte » ; on ignore le bloc « Vous aimerez aussi ».
    utile = texte.split("Vous aimerez aussi")[0]
    i = utile.find("Voir sur la carte")
    debut = utile[max(0, i - 160):i] if i > 0 else utile[:300]
    return nom, email, (mcp.group(1) if mcp else ""), debut, texte


def nom_depuis_titre(titre, hote):
    t = re.split(r"\s[|\-–—:•]\s", titre or "")[0].strip()
    if 2 <= len(t) <= 50 and not re.search(r"accueil|home|bienvenue|site officiel", t, re.I):
        return t
    base = hote.split(".")[0].replace("-", " ")
    return base


# --------------------------------------------------------------------------
# 7. Collecte principale
# --------------------------------------------------------------------------
def collecter(maximum, sources):
    ln = charger_liste_noire()
    nav = Navigateur()
    candidats = candidats_fichier()
    if "petitfute" in sources:
        print("→ Petit Futé…")
        candidats += candidats_petit_fute(nav)
    if "vendee" in sources:
        print("→ Vendée Tourisme…")
        candidats += candidats_vendee_tourisme(nav)
    if "ot" in sources:
        print("→ Offices de tourisme…")
        candidats += candidats_offices_tourisme(nav)
    if "recherche" in sources:
        print("→ Moteur de recherche…")
        candidats += candidats_recherche(nav, VILLES, PROFILS_RECHERCHE)
    print(f"  {len(candidats)} sites candidats")

    retenus, details, journal, sites_vus = {}, [], [], set()
    douteux = []

    def retenir(email, nom, ville, cp, dist, cat, url_source, c, mentions=""):
        """Derniers contrôles puis ajout du contact. Renvoie True si retenu."""
        dom = domaine(email)
        r = motif_rejet(email, nom, ln)
        hote_source = urlparse(c["url"]).netloc.replace("www.", "")
        if not r and c.get("fiche") and dom != hote_source and dom.split(".")[0] in hote_source:
            r = "adresse de l'annuaire lui-même"
        if not r and c.get("fiche") in ("ot", "tourinsoft") and RE_HORS_PROFIL.search(email):
            r = "hors profil d'après l'adresse (crêperie, pizzeria, chaîne…)"
        if not r and c.get("fiche") and re.search(r"tourisme|mairie|agglo|^ot-|ville-|commune|vignoble", dom):
            r = "adresse d'un office de tourisme ou d'une mairie"
        # Sur une fiche d'annuaire, l'adresse doit être un webmail ou porter le nom de l'établissement
        # (sinon c'est souvent l'agence web ou l'éditeur de l'annuaire).
        if not r and c.get("fiche") and dom not in WEBMAILS and not lien_nom_domaine(nom, dom):
            r = "adresse sans lien avec le nom de l'établissement"
        if r:
            journal.append((c["url"], email, r))
            return False
        if email in retenus:
            return False
        if not nav.a_un_mx(dom):
            journal.append((c["url"], email, "domaine sans serveur mail"))
            return False
        prenom = trouver_prenom(mentions, email) or formule_equipe(nom)
        retenus[email] = prenom
        ln["noms"].add(cle_nom(nom))
        if dom not in WEBMAILS:
            ln["domaines"].add(dom)
        details.append({"Email": email, "Prenom": prenom, "Etablissement": nom, "Ville": ville or "",
                        "CP": cp or "", "Distance_km": round(dist), "Categorie": cat,
                        "URL_preuve": url_source, "Source": c.get("source", ""),
                        "Date": time.strftime("%Y-%m-%d")})
        print(f"  ✔ {len(retenus):3d}  {email:42s} {prenom[:45]:45s} {ville} ({cat})")
        return True

    # Pré-visite en parallèle de sites différents (8 à la fois). Chaque site reste visité
    # page par page avec sa pause ; les pages sont mises en cache pour la boucle ci-dessous.
    from concurrent.futures import ThreadPoolExecutor
    import threading
    local = threading.local()

    def previsiter(c):
        if not hasattr(local, "nav"):
            local.nav = Navigateur()
        try:
            if c.get("fiche") == "annuaire":
                local.nav.get(c["url"])
            else:
                explorer_site(local.nav, c["url"])
        except Exception:
            pass

    a_voir, deja = [], set()
    for c in candidats:
        cle = c["url"] if c.get("fiche") else urlparse(c["url"]).netloc
        if cle not in deja:
            deja.add(cle)
            a_voir.append(c)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(previsiter, a_voir))

    for c in candidats:
        if len(retenus) >= maximum:
            break
        if c.get("fiche") == "annuaire":
            # Page d'annuaire (mairie, office de tourisme) : plusieurs établissements par page.
            if c["url"] in sites_vus:
                continue
            sites_vus.add(c["url"])
            html = nav.get(c["url"])
            if not html:
                journal.append((c["url"], "", "annuaire inaccessible"))
                continue
            for email, nom, bloc in blocs_annuaire(html):
                if len(retenus) >= maximum:
                    break
                # Nom introuvable : on garde l'adresse, la formule sera « à toute l'équipe ».
                cat, raison = qualifier(bloc, nom, seuil=1)
                if not cat and raison == "restaurant sans vin mis en avant":
                    # Validé avec l'utilisateur : restaurants traditionnels d'annuaire acceptés,
                    # sauf pizzerias, crêperies, restauration rapide et bars PMU/tabac.
                    if re.search(r"pizz|cr[eê]p|pmu|tabac|kebab|burger|snack|sushi|fast", nom.lower()) or \
                            re.search(r"pizzeria|kebab|fast.food|sushi|bar.tabac|restauration rapide", bloc.lower()):
                        journal.append((c["url"], email, f"{nom} : restauration rapide / crêperie"))
                        continue
                    cat = "Restaurant"
                if not cat:
                    journal.append((c["url"], email, f"{nom} : {raison}"))
                    continue
                ville, cp, dist = localiser(bloc, c.get("ville"))
                if dist is None:
                    ville, dist = ville_connue(c.get("ville"))
                if dist is None or dist > RAYON_KM:
                    journal.append((c["url"], email, f"hors zone ({cp or '?'})"))
                    continue
                retenir(email, nom, ville, cp, dist, cat, c["url"], c)
            continue
        if c.get("fiche") == "ot":
            if c["url"] in sites_vus:
                continue
            sites_vus.add(c["url"])
            html = nav.get(c["url"])
            nom, email, cp, texte = lire_fiche_schema(html or "")
            if not email:
                journal.append((c["url"], "", f"{nom} : pas d'e-mail sur la fiche"))
                continue
            if c["categorie"] in ("restaurant", "traiteur", "bar"):
                if RE_HORS_PROFIL.search(nom) or re.search(r"pizzeria|kebab|fast.food|cr[eê]perie|snack|servescuisine\W+(?:asian|italian|chinese|pizza)", texte[:8000].lower()):
                    journal.append((c["url"], email, f"{nom} : hors profil (pizzeria, crêperie, rapide…)"))
                    continue
                cat = {"restaurant": "Restaurant", "traiteur": "Traiteur", "bar": "Bar à vins / tapas"}[c["categorie"]]
                if c["categorie"] == "bar" and not re.search(r"\bvins?\b|cave|tapas", (nom + texte[:6000]).lower()):
                    journal.append((c["url"], email, f"{nom} : bar sans vin"))
                    continue
            else:
                cat, raison = qualifier(texte[:8000], nom)
                if not cat or cat in ("Restaurant", "Hôtel-restaurant"):
                    journal.append((c["url"], email, f"{nom} : {raison or 'commerce hors profil'}"))
                    continue
            ville, dist = distance_par_cp(nav, cp) if cp else (None, None)
            if dist is None or dist > RAYON_KM:
                journal.append((c["url"], email, f"{nom} : hors zone ({cp or '?'})"))
                continue
            retenir(email, nom, ville, cp, dist, cat, c["url"], c)
            continue
        if c.get("fiche") == "tourinsoft":
            if c["url"] in sites_vus:
                continue
            sites_vus.add(c["url"])
            html = nav.get(c["url"])
            if not html:
                journal.append((c["url"], "", "fiche inaccessible"))
                continue
            nom, email, cp, debut, texte = lire_fiche_tourinsoft(html)
            if not email:
                journal.append((c["url"], "", f"{nom} : pas d'e-mail sur la fiche"))
                continue
            if "hotpdl" in c["url"] and not re.search(r"\brestaurant\b", texte.split("Vous aimerez aussi")[0], re.I):
                journal.append((c["url"], email, f"{nom} : hôtel sans restaurant"))
                continue
            if RE_HORS_PROFIL.search(nom + " " + debut):
                journal.append((c["url"], email, f"{nom} : hors profil (pizzeria, crêperie, rapide…)"))
                continue
            if re.search("|".join(MOTS_INTERDITS), (nom + " " + debut).lower()):
                journal.append((c["url"], email, f"{nom} : hors cible"))
                continue
            ville, dist = distance_par_cp(nav, cp) if cp else (None, None)
            if dist is None or dist > RAYON_KM:
                journal.append((c["url"], email, f"{nom} : hors zone ({cp or '?'})"))
                continue
            retenir(email, nom, ville, cp, dist, "Restaurant", c["url"], c)
            continue
        hote = urlparse(c["url"]).netloc.replace("www.", "")
        cle_site = c["url"] if c.get("fiche") == "1" else hote
        if not hote or cle_site in sites_vus:
            continue
        sites_vus.add(cle_site)
        if (hote in ln["domaines"] or hote.rsplit(".", 1)[0] in {d.rsplit(".", 1)[0] for d in ln["domaines"]}) \
                and not est_reseau(hote):
            journal.append((c["url"], "", "site déjà connu"))
            continue
        info = explorer_site(nav, c["url"])
        if not info or not info["emails"]:
            journal.append((c["url"], "", "aucun e-mail public"))
            continue
        cat, raison = qualifier(info["texte"], info["titre"])
        if not cat and raison == "activité non liée au vin" and c.get("categorie"):
            cat = c["categorie"]
        if not cat:
            journal.append((c["url"], "", raison))
            continue
        ville, cp, dist = localiser(info["texte"], c.get("ville"))
        if cp and dist is None:
            v_api, d_api = distance_par_cp(nav, cp)
            if d_api is not None:
                ville, dist = v_api, d_api
            else:
                ville, dist = ville_connue(c.get("ville"), cp)
        if dist is None or dist > RAYON_KM:
            journal.append((c["url"], "", f"hors zone ({cp or '?'})"))
            continue
        nom = c.get("nom") or nom_depuis_titre(info["titre"], hote)
        # Un seul e-mail par établissement : on préfère celui du domaine du site.
        emails = sorted(info["emails"].items(),
                        key=lambda kv: (domaine(kv[0]) != hote, not kv[0].startswith(("contact", "info", "bonjour"))))
        for email, url_source in emails:
            dom = domaine(email)
            marque = dom.rsplit(".", 1)[0].split(".")[-1]
            if dom != hote and dom not in WEBMAILS and marque not in hote and c.get("fiche") != "1":
                journal.append((c["url"], email, "domaine étranger au site"))
                continue
            r = motif_rejet(email, nom, ln)
            if r and r.startswith("établissement"):
                journal.append((c["url"], email, r))
                break
            reseau = est_reseau(hote) or est_reseau(nom)
            local = email.split("@")[0]
            if reseau and (local in ("contact", "info", "bonjour", "hello", "commande", "service",
                                     "serviceclient", "service-client")
                           or any(x.replace("-", "") in local.replace("-", "") for x in RESEAUX)):
                journal.append((c["url"], email, "adresse du siège du réseau, pas du magasin"))
                continue
            if retenir(email, nom, ville, cp, dist, cat, url_source, c,
                       "" if reseau else info["mentions"]):
                break

    ecrire(retenus, details)
    with open(os.path.join(DOSSIER_CACHE, "journal_rejets.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url", "email", "raison"])
        w.writerows(journal)
    with open(os.path.join(DOSSIER_CACHE, "douteux.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["email", "nom", "ville", "url", "extrait"])
        w.writerows(douteux)
    if douteux:
        print(f"  {len(douteux)} restaurants d'annuaire à faire valider (cache/douteux.csv)")
    if nav.bloques:
        print("  Sites qui ont refusé le robot :", ", ".join(f"{h} ({r})" for h, r in list(nav.bloques.items())[:15]))
    print(f"→ {len(retenus)} contacts retenus, {len(journal)} rejets (cache/journal_rejets.csv)")


def ecrire(retenus, details):
    with open(SORTIE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Email", "Prenom"])
        for e, p in retenus.items():
            w.writerow([e, p])
    if details:
        with open(SORTIE_DETAILS, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(details[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(details)


# --------------------------------------------------------------------------
# 8. Contrôle indépendant du livrable
# --------------------------------------------------------------------------
def verifier():
    ln = charger_liste_noire(verbeux=False)
    lignes = list(csv.reader(open(SORTIE, encoding="utf-8")))
    erreurs = []
    if lignes[0] != ["Email", "Prenom"]:
        erreurs.append(f"en-tête incorrect : {lignes[0]}")
    vus = set()
    for i, l in enumerate(lignes[1:], start=2):
        if len(l) != 2:
            erreurs.append(f"ligne {i} : {len(l)} colonnes")
            continue
        e, p = l
        if e != normaliser_email(e):
            erreurs.append(f"ligne {i} : e-mail non normalisé {e}")
        if e in vus:
            erreurs.append(f"ligne {i} : doublon interne {e}")
        vus.add(e)
        if e in ln["emails"]:
            erreurs.append(f"ligne {i} : COLLISION liste noire {e}")
        if any(s in e for s in SOUS_CHAINES_INTERDITES):
            erreurs.append(f"ligne {i} : sous-chaîne interdite {e}")
        if not re.fullmatch(r"[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}", e):
            erreurs.append(f"ligne {i} : format {e}")
        if domaine(e) in ln["domaines"] and not est_reseau(domaine(e)):
            erreurs.append(f"ligne {i} : domaine déjà connu {e}")
        if not (p.startswith("à toute l'équipe") or re.fullmatch(r"[A-ZÉÈ][a-zéèêëïîôç]+(-[A-ZÉ][a-zéèêëç]+)?", p)):
            erreurs.append(f"ligne {i} : Prenom mal formé « {p} »")
    print(f"  {len(lignes) - 1} contacts contrôlés, {len(erreurs)} anomalie(s)")
    for e in erreurs:
        print("   ✘", e)
    if os.path.exists(SORTIE_DETAILS):
        det = list(csv.DictReader(open(SORTIE_DETAILS, encoding="utf-8")))
        sans_preuve = vus - {d["Email"] for d in det if d.get("URL_preuve")}
        print(f"  preuves : {len(vus) - len(sans_preuve)}/{len(vus)} contacts ont une URL source")
        for d in random.sample(det, min(10, len(det))):
            print(f"   · {d['Email']:40s} ← {d['URL_preuve']}")
    return not erreurs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("etape", choices=["liste-noire", "test-prenoms", "collecter", "verifier"])
    ap.add_argument("--max", type=int, default=100)
    ap.add_argument("--sortie", help="nom du fichier CSV à produire (défaut : NOUVEAUX_CONTACTS_CLAUDE_CODE.csv)")
    ap.add_argument("--exclure", nargs="*", default=[], help="fichiers déjà livrés à ajouter à la liste noire")
    ap.add_argument("--sources", default="fichier",
                    help="sources à utiliser, séparées par des virgules")
    a = ap.parse_args()
    global SORTIE, SORTIE_DETAILS
    if a.sortie:
        SORTIE = os.path.join(ICI, a.sortie)
        SORTIE_DETAILS = SORTIE.replace(".csv", "_DETAILS.csv")
    EXCLURE_EN_PLUS.extend(os.path.join(ICI, f) for f in a.exclure)
    if a.etape == "liste-noire":
        charger_liste_noire()
    elif a.etape == "test-prenoms":
        sys.exit(0 if test_prenoms() else 1)
    elif a.etape == "collecter":
        collecter(a.max, a.sources.split(","))
    else:
        sys.exit(0 if verifier() else 1)


if __name__ == "__main__":
    main()
