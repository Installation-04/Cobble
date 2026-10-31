# Contribuer à Cobble / Contributing to Cobble

## Français

1. Lire `PLAN.md` et `CLAUDE.md`. Travailler uniquement sur la version en cours; les idées hors portée vont dans une issue avec l'étiquette `idée`.
2. Installer: `make install`. Vérifier: `make lint test`.
3. Commits petits, style Conventional Commits (`feat:`, `fix:`, `docs:`…), **signés DCO**: `git commit -s`.
4. Toute chaîne visible passe par les fichiers i18n, en `fr` et en `en` dans le même commit. Couleurs uniquement via les jetons de thème.
5. Toute fonctionnalité arrive avec ses tests; les tests n'appellent jamais un vrai modèle.
6. Mettre à jour `CHANGELOG.md` (section « Unreleased »).
7. Nouvelle dépendance: licence compatible AGPL-3.0, signalée dans la PR.

Code, commentaires et commits en anglais; documentation utilisateur en français et en anglais.

## English

1. Read `PLAN.md` (French) and `CLAUDE.md`. Work only on the current version; out-of-scope ideas go in an issue labeled `idée`.
2. Install: `make install`. Check: `make lint test`.
3. Small commits, Conventional Commits style, **DCO sign-off**: `git commit -s`.
4. Every user-visible string goes through the i18n files, in both `fr` and `en` in the same commit. Colors only via theme tokens.
5. Every feature ships with tests; tests never call a real model.
6. Update `CHANGELOG.md` ("Unreleased" section).
7. New dependency: AGPL-3.0-compatible license, flagged in the PR.

Code, comments and commits in English; user documentation in French and English.
