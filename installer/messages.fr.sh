#!/usr/bin/env bash
# Messages français pour install.sh et la CLI cobble. Mêmes clés que messages.en.sh.
# Les valeurs sont des formats printf; pas de barre oblique inverse ni de pourcent isolé.
# shellcheck disable=SC2034,SC1112,SC2016

M_help="Installateur de Cobble

Utilisation : install.sh [options]

  --dir <chemin>       répertoire d'installation (défaut : /opt/cobble)
  --source <src>       arborescence source : dossier, archive (fichier ou URL) ou URL git
                       (défaut : ce dépôt, sinon \$COBBLE_TARBALL_URL)
  --lang fr|en         langue des messages et de l'application (défaut : selon \$LANG)
  --gpu auto|nvidia|amd|none
                       gestion du GPU (défaut : auto; en v0.1 il est seulement détecté et noté)
  --yes, -y            ne pas demander de confirmation
  --skip-checks        ignorer les vérifications CPU/RAM/disque/ports/Internet (CI, tests)
  --help, -h           afficher cette aide

Relancer l'installateur répare ou complète une installation sans rien supprimer.
Journal : /var/log/cobble-install.log"

M_usage_error='Option inconnue ou incomplète : %s (voir --help)'
M_lang_invalid='Langue invalide : %s (fr ou en attendu)'
M_gpu_invalid='Valeur de --gpu invalide : %s (auto, nvidia, amd ou none attendu)'
M_dir_invalid="Répertoire d'installation invalide : %s (chemin absolu requis)"
M_need_root="Cet installateur doit s'exécuter en root. Essayez : sudo bash install.sh"
M_os_ok="Système d'exploitation : %s"
M_os_unsupported="Système non supporté : %s. Supportés : Ubuntu 24.04, Ubuntu 26.04, Debian 12, Debian 13."
M_arch_arm64="arm64 n'est pas encore supporté. Cobble v0.1 fonctionne seulement sur amd64."
M_arch_unsupported="Architecture non supportée : %s. Cobble v0.1 fonctionne seulement sur amd64."
M_cpu_low='Pas assez de processeurs : %s trouvés, %s requis.'
M_ram_low='Pas assez de mémoire : %s Mo trouvés, 4 Go requis.'
M_disk_low="Pas assez d'espace disque libre : %s Go trouvés, %s Go requis sur le système de fichiers du répertoire d'installation."
M_port_busy='Le port %s est déjà utilisé par un autre programme. Libérez-le, puis relancez l’installateur.'
M_port_busy_443="Le port 443 est utilisé. Cobble n'en a pas encore besoin (HTTP seulement en v0.1)."
M_no_internet='Pas d’accès Internet (download.docker.com injoignable). Vérifiez le réseau, le DNS et le proxy.'
M_lxc_detected='Conteneur LXC détecté. Cobble exige un conteneur privilégié avec nesting=1 et keyctl=1, sinon Docker ne démarrera pas. Une VM est recommandée.'
M_confirm_install='Installer Cobble dans %s ?'
M_aborted='Annulé.'
M_docker_reuse='Utilisation du Docker existant (serveur version %s).'
M_docker_unusable='Docker est installé mais inutilisable ou trop ancien (serveur >= 24 et plugin compose requis, trouvé : %s). Mettez-le à jour ou retirez-le, puis relancez l’installateur.'
M_docker_installing='Installation de Docker Engine depuis le dépôt officiel de Docker.'
M_docker_broken='Docker est installé mais "docker compose" ne fonctionne pas.'
M_gpu_none='Aucun GPU utilisé (aucun détecté ou --gpu=none).'
M_gpu_detected='GPU noté : %s (la v0.1 le note seulement; les modèles locaux viendront dans une version ultérieure).'
M_gpu_nvidia_nodriver='GPU NVIDIA trouvé mais aucun pilote fonctionnel (nvidia-smi échoue). Installez le pilote NVIDIA, puis relancez l’installateur. Suite sans GPU.'
M_gpu_toolkit_installing='Installation du NVIDIA Container Toolkit.'
M_gpu_toolkit_ok='NVIDIA Container Toolkit prêt et testé.'
M_gpu_toolkit_failed='Impossible de configurer le GPU dans Docker. Cela ne bloque pas l’installation.'
M_source_fetching='Récupération des sources depuis %s'
M_source_failed='Impossible de récupérer les sources depuis %s'
M_source_bad='Source invalide (core/compose.yml introuvable) : %s'
M_env_created='Secrets générés dans le fichier .env (mode 0600).'
M_env_kept='.env existant conservé (jamais écrasé).'
M_core_starting='Construction et démarrage de Cobble (le premier lancement prend plusieurs minutes).'
M_core_failed='Cobble n’est pas devenu sain. Lancez "cobble doctor" et "cobble logs" pour enquêter.'
M_systemd_skip="systemd n'est pas le PID 1 ici : unité cobble.service ignorée (Cobble ne démarrera pas au boot)."
M_unit_installed='Unité systemd cobble.service installée et activée.'
M_ufw_opened='ufw est actif : ports web ouverts (SSH inchangé).'
M_cli_installed='CLI installée : %s'
M_done_title='Cobble est installé.'
M_done_url_ip='Ouvrez Cobble à : %s'
M_done_url_host='Ou par nom d’hôte : %s'
M_done_activation='Lien à usage unique pour créer le compte admin (valide 24 h) :'
M_done_admin_exists='Pas de lien d’activation : le compte admin existe déjà (ou l’API n’est pas prête). Pour obtenir un nouveau lien : cobble reset-admin'
M_done_next='Commandes utiles : cobble status | cobble doctor | cobble logs | cobble modules | cobble help'

M_cli_not_installed="Cobble ne semble pas installé dans %s (définissez COBBLE_DIR si vous avez utilisé --dir)."
M_cli_unknown='Commande inconnue : %s (voir : cobble help)'
M_need_yes='Confirmation requise mais aucun terminal disponible : ajoutez --yes.'
M_not_available='"%s" n’est pas encore disponible (prévu dans une version ultérieure).'
M_status_healthy='En bonne santé : %s'
M_status_unhealthy='Ne répond pas : %s'
M_update_backup='.env sauvegardé dans %s'
M_update_rebuild='Reconstruction et redémarrage de Cobble depuis les sources installées.'
M_uninstall_confirm='Ceci arrête Cobble et SUPPRIME %s et toutes ses données (base, volumes). Continuer ?'
M_uninstall_confirm_keep='Ceci arrête Cobble et retire le programme de %s. Le fichier .env et les volumes de données sont conservés. Continuer ?'
M_uninstall_kept='Conservés dans %s : .env et state.json. Les volumes de données ne sont pas touchés.'
M_uninstall_done='Cobble est désinstallé.'
M_reset_confirm='Ceci déconnecte l’admin et affiche un lien à usage unique pour définir un nouveau courriel et mot de passe (projets et données conservés). Continuer ?'
M_version_installed='version installée : %s'

M_doc_docker_missing="Docker n'est pas installé"
M_doc_docker_down="Docker n'est pas démarré"
M_doc_docker_old='Le serveur Docker version %s est trop ancien (24 ou plus requis)'
M_doc_docker_ok='Serveur Docker version %s'
M_doc_no_containers='Aucun conteneur Cobble trouvé'
M_doc_container_bad='état : %s, santé : %s'
M_doc_containers_ok='%s conteneurs démarrés et sains'
M_doc_http_down='Aucune réponse de %s'
M_doc_disk='%s Go libres'
M_doc_port_noss='impossible de vérifier les ports (ss est absent)'
M_doc_port_ok='le port %s est à l’écoute'
M_doc_port_closed='rien n’écoute sur le port %s'
M_doc_env_ok='%s est en mode 0600'
M_doc_env_bad='.env est en mode %s au lieu de 600'
M_doc_no_systemd="systemd n'est pas disponible; le démarrage au boot n'est pas géré"
M_doc_unit_ok='cobble.service est actif'
M_doc_unit_bad="cobble.service n'est pas actif"
M_doc_gpu='GPU : %s (container toolkit : %s)'
M_doc_summary_fail='%s vérification(s) en échec.'
M_doc_summary_ok='Toutes les vérifications sont passées.'
M_doc_modules_notoken='MODULE_MANAGER_TOKEN est absent de .env'
M_doc_modules_nocatalog='le catalogue de modules est absent ou vide (%s)'
M_doc_modules_ok='catalogue de modules trouvé (%s modules)'
M_doc_modules_gid='Le groupe du socket Docker a changé (installé %s, maintenant %s) : le gestionnaire de modules ne peut plus utiliser Docker'
M_modules_unreachable='cobble modules n’a pas pu joindre le gestionnaire de modules : lancez cobble doctor'
M_fix_modules='Relancez l’installateur pour réparer les réglages des modules : sudo bash install.sh --yes'
M_fix_docker_install='Installez ou mettez à jour Docker, ou relancez l’installateur : sudo bash install.sh --yes'
M_fix_docker_start='Démarrez-le : sudo systemctl start docker'
M_fix_start='Démarrez Cobble : sudo systemctl start cobble (ou : cobble update)'
M_fix_container='Voyez les journaux : cobble logs <service>; redémarrez avec : sudo systemctl restart cobble'
M_fix_http='Vérifiez les conteneurs ci-dessus, puis cobble logs caddy api'
M_fix_disk='Libérez de l’espace disque (docker system prune supprime les images inutilisées)'
M_fix_port='Vérifiez que le conteneur caddy tourne et qu’aucun pare-feu ne bloque le port'
M_fix_env='Corrigez : sudo chmod 600 /opt/cobble/.env (adaptez le chemin si vous avez utilisé --dir)'
M_fix_unit='Démarrez-la : sudo systemctl enable --now cobble'

M_cli_help="cobble : gérer votre installation de Cobble

Utilisation : cobble <commande>

  status               conteneurs et santé web
  logs [service]       suivre les journaux
  update [--source S]  reconstruire et redémarrer (ou installer la source S : dossier, archive, URL git)
  doctor               diagnostiquer les problèmes et proposer des correctifs (code 1 si échec)
  models <commande>    connecter un service de modèles avec une clé d’API : list, add, test, default, remove
  reset-admin [--yes]  afficher un lien à usage unique pour définir un nouvel admin (courriel, mot de passe)
  modules <commande>   lister, installer et désinstaller des modules (cobble modules help)
  uninstall [--keep-data] [--yes]
                       arrêter et retirer Cobble (--keep-data garde .env et les volumes)
  version              afficher les versions
  backup | restore     pas encore disponibles
  help                 cette aide"
