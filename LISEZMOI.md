# Sourcing Salon du Vin – 5 octobre 2026

Script qui cherche de nouveaux contacts pros (cavistes, épiceries fines, bio, fromageries,
restaurants…) autour de Pont-Saint-Martin, sans jamais recontacter une adresse déjà connue.

## Préparer
1. `pip install -r requirements.txt`
2. Déposer les 4 fichiers sources dans `donnees_sources/` (ce dossier n'est pas envoyé sur GitHub) :
   Master_tous_les_contacts*.xlsx, CSV_ENVOI_FUSION_NEUFS*.csv, CSV_ENVOI_LUNDI_4_LOTS_1*.csv,
   Inscription*.xlsx.
3. Il faut un accès internet complet : l'environnement doit être réglé sur « Network access : Full ».

## Lancer
```
python sourcing_salon_vin.py liste-noire     # compte les adresses exclues (5 476 attendues)
python sourcing_salon_vin.py test-prenoms    # teste les formules « à toute l'équipe de… »
python sourcing_salon_vin.py collecter --max 124 --sources fichier,vendee
python sourcing_salon_vin.py verifier        # contrôle 0 doublon, 0 collision, format Email,Prenom
# Lot 3 (exclut aussi les lots déjà livrés) :
python sourcing_salon_vin.py collecter --max 500 --sources fichier,vendee,ot,mairie \
  --sortie NOUVEAUX_CONTACTS_CLAUDE_CODE_LOT3.csv \
  --exclure NOUVEAUX_CONTACTS_CLAUDE_CODE.csv NOUVEAUX_CONTACTS_CLAUDE_CODE_LOT2.csv
```

## Sources utilisées
- `candidats_sites.csv` : sites trouvés par recherche web (colonne `fiche` : vide = site de
  l'établissement, `1` = fiche d'un seul établissement, `annuaire` = page listant plusieurs
  établissements, comme les mairies ou annuher.com).
- `vendee` : fiches publiques de Vendée Tourisme (Maître Restaurateur, gastronomique,
  traditionnel), où l'e-mail est affiché ; pizzerias, crêperies et restauration rapide exclues.
- `ot` : fiches des offices de tourisme de Pornic et Saint-Brevin (e-mail en données schema.org).
- `mairie` : annuaires des commerces des sites de mairies (78 communes des 44, 49, 56 et 85 listées
  dans `mairies_annuaires.json`, repérées via l'annuaire officiel service-public).
- Petit Futé, PagesJaunes et les moteurs de recherche bloquent les robots : ils ne sont pas utilisés.

## Résultats
- `NOUVEAUX_CONTACTS_CLAUDE_CODE.csv` (lot 1), `…_LOT2.csv`, `…_LOT3.csv` : colonnes `Email,Prenom`, prêt pour l'envoi.
- `NOUVEAUX_CONTACTS_DETAILS.csv` : établissement, ville, catégorie et URL où chaque e-mail a été lu.
- `cache/journal_rejets.csv` : chaque adresse écartée et la raison.
