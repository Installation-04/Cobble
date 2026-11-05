# Publier une version (mainteneurs)

Conception: `docs/decisions/0023-release-pipeline.md` (en anglais). Un tag `vX.Y.Z` publie les images
du noyau sur GHCR et une release GitHub avec quatre fichiers: `cobble.tar.gz`, `cobble.tar.gz.sha256`,
`install.sh`, `install.sh.sha256`. L'archive contient `core/compose.release.yml`, qui épingle chaque
image construite par la CI.

## Étapes

1. **Les images des modules d'abord.** Lancer le workflow *Module images* (`images.yml`, onglet
   Actions, « Run workflow ») sur le commit à publier. Copier la liste `PIN-THESE` de son résumé, puis:
   ```bash
   python3 scripts/pin_images.py ghcr.io/<owner>/cobble-agent-service@sha256:<digest> ...
   git diff catalog/   # seuls les condensats changent
   ```
   Commiter (`chore: pin module images for vX.Y.Z`) et fusionner. Les images des modules sont épinglées
   dans les manifestes AVANT le tag; le workflow de release ne les reconstruit pas.
2. **Journal des changements.** Déplacer les entrées « Unreleased » de `CHANGELOG.md` sous
   `## [X.Y.Z] - date` et ajouter les notes `docs/releases/vX.Y.md` si la version en a (elles
   deviennent le texte de la release; sinon GitHub les génère). Vérifier que `make lint test` passe sur
   `main`.
3. **Essai à blanc (facultatif, conseillé pour la première release).** Actions, *Release*, « Run
   workflow », tag `v0.0.0-dryrun`. Toutes les images sont construites sans être poussées et les
   fichiers (avec des condensats factices) sont joints à l'exécution. Rien n'est publié.
4. **Tagger** le commit fusionné et pousser le tag:
   ```bash
   git switch main && git pull
   git tag -s vX.Y.Z -m "Cobble X.Y.Z" && git push origin vX.Y.Z
   ```
   Un tag avec suffixe (`v0.3.0-rc.1`) crée une pré-release.
5. **Vérifier les fichiers** quand l'exécution *Release* est verte:
   ```bash
   gh release view vX.Y.Z --json assets --jq '.assets[].name'   # les 4 fichiers
   mkdir /tmp/rel && cd /tmp/rel
   gh release download vX.Y.Z && sha256sum -c cobble.tar.gz.sha256 install.sh.sha256
   tar -tzf cobble.tar.gz | head                                  # un seul dossier cobble-X.Y.Z/
   tar -xzOf cobble.tar.gz cobble-X.Y.Z/core/compose.release.yml  # 5 images, avec @sha256:
   ```
   **Première release seulement: rendre les paquets publics.** Sur GitHub, *Packages* du dépôt: pour
   chaque paquet `cobble-*` (api, worker, module-manager, ui, fake-llm), Package settings, Change
   visibility, Public. Vérifier avec `docker logout ghcr.io && docker pull ghcr.io/<owner>/cobble-ui:X.Y.Z`.
6. **Tester la commande unique** sur une VM vierge (voir `docs/fr/install.md`):
   ```bash
   curl -fsSL https://github.com/<owner>/Cobble/releases/latest/download/install.sh | sudo bash
   ```
   Elle doit télécharger les images (sans construire), démarrer la pile et afficher le lien
   d'activation.

## En cas d'échec
- Un job échoue avant la création de la release: rien n'est publié comme release; corriger, supprimer
  le tag (`git push origin :refs/tags/vX.Y.Z`, `git tag -d vX.Y.Z`) et retaguer. Les images déjà
  poussées sous ce tag de version sont sans danger (le fichier compose épingle des condensats, pas des
  tags).
- Ne jamais modifier à la main les fichiers d'une release publiée: publier une nouvelle version de
  correctif.
