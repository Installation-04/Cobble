#!/usr/bin/env bash
# English messages for install.sh and the cobble CLI. Same keys as messages.fr.sh.
# Values are printf formats; do not use backslashes or stray percent signs.
# shellcheck disable=SC2034,SC1112,SC2016

M_help='Cobble installer

Usage: install.sh [options]

  --dir <path>         install directory (default: /opt/cobble)
  --source <src>       source tree: directory, tarball (file or URL) or git URL
                       (default: this checkout, else $COBBLE_TARBALL_URL)
  --lang fr|en         language of the messages and of the app (default: from $LANG)
  --gpu auto|nvidia|amd|none
                       GPU handling (default: auto; only detected and recorded in v0.1)
  --yes, -y            do not ask for confirmation
  --skip-checks        skip CPU/RAM/disk/port/Internet checks (CI, tests)
  --help, -h           show this help

Re-running the installer repairs or completes an install without deleting anything.
Log: /var/log/cobble-install.log'

M_usage_error='Unknown or incomplete option: %s (see --help)'
M_lang_invalid='Invalid language: %s (expected fr or en)'
M_gpu_invalid='Invalid --gpu value: %s (expected auto, nvidia, amd or none)'
M_dir_invalid='Invalid install directory: %s (must be an absolute path)'
M_need_root='This installer must run as root. Try: sudo bash install.sh'
M_os_ok='Operating system: %s'
M_os_unsupported='Unsupported operating system: %s. Supported: Ubuntu 24.04, Ubuntu 26.04, Debian 12, Debian 13.'
M_arch_arm64='arm64 is not supported yet. Cobble v0.1 runs on amd64 only.'
M_arch_unsupported='Unsupported architecture: %s. Cobble v0.1 runs on amd64 only.'
M_cpu_low='Not enough CPUs: %s found, %s required.'
M_ram_low='Not enough memory: %s MB found, 4 GB required.'
M_disk_low='Not enough free disk space: %s GB found, %s GB required on the install directory filesystem.'
M_port_busy='Port %s is already in use by another program. Free it, then run the installer again.'
M_port_busy_443='Port 443 is in use. Cobble does not need it yet (plain HTTP only in v0.1).'
M_no_internet='No Internet access (could not reach download.docker.com). Check the network, DNS and proxy settings.'
M_lxc_detected='LXC container detected. Cobble needs a privileged container with nesting=1 and keyctl=1 enabled, otherwise Docker will fail to start. A VM is recommended.'
M_confirm_install='Install Cobble into %s?'
M_aborted='Aborted.'
M_docker_reuse='Using the existing Docker (server version %s).'
M_docker_unusable='Docker is installed but unusable or too old (need server >= 24 and the compose plugin, found: %s). Upgrade or remove it, then run the installer again.'
M_docker_installing='Installing Docker Engine from the official Docker repository.'
M_docker_broken='Docker was installed but "docker compose" does not work.'
M_gpu_none='No GPU used (none detected or --gpu=none).'
M_gpu_detected='GPU recorded: %s (v0.1 only records it; local models come in a later version).'
M_gpu_nvidia_nodriver='NVIDIA GPU found but no working driver (nvidia-smi fails). Install the NVIDIA driver, then run the installer again. Continuing without GPU support.'
M_gpu_toolkit_installing='Installing the NVIDIA Container Toolkit.'
M_gpu_toolkit_ok='NVIDIA Container Toolkit ready and tested.'
M_gpu_toolkit_failed='Could not set up GPU support in Docker. This does not block the install.'
M_source_fetching='Fetching the source tree from %s'
M_source_failed='Could not fetch the source from %s'
M_source_bad='Invalid source (core/compose.yml not found): %s'
M_env_created='Secrets generated in the .env file (mode 0600).'
M_env_kept='Existing .env kept (never overwritten).'
M_core_starting='Building and starting Cobble (the first run takes several minutes).'
M_core_failed='Cobble did not become healthy. Run "cobble doctor" and "cobble logs" to investigate.'
M_systemd_skip='systemd is not PID 1 here: skipping the cobble.service unit (Cobble will not start at boot).'
M_unit_installed='systemd unit cobble.service installed and enabled.'
M_ufw_opened='ufw is active: opened the web ports (SSH untouched).'
M_cli_installed='CLI installed: %s'
M_done_title='Cobble is installed.'
M_done_url_ip='Open Cobble at: %s'
M_done_url_host='Or by host name:   %s'
M_done_activation='One-use link to create the admin account (valid 24 h):'
M_done_admin_exists='No activation link: the admin account already exists (or the API is not ready). To get a new link run: cobble reset-admin'
M_done_next='Useful commands: cobble status | cobble doctor | cobble logs | cobble modules | cobble help'
M_done_v01_pack='A v0.1 pack (Git server and CI installed by hand) was found. It keeps running, but modules replace it: remove the pack (packs/v01/hooks/uninstall.sh), then run: cobble modules install woodpecker'

M_cli_not_installed='Cobble does not seem to be installed in %s (set COBBLE_DIR if you used --dir).'
M_cli_unknown='Unknown command: %s (see: cobble help)'
M_need_yes='Confirmation required but no terminal is available: add --yes.'
M_not_available='"%s" is not available yet (planned for a later version).'
M_status_healthy='Healthy: %s'
M_status_unhealthy='Not answering: %s'
M_update_backup='.env backed up to %s'
M_update_rebuild='Rebuilding and restarting Cobble from the installed source.'
M_uninstall_confirm='This stops Cobble and DELETES %s and all its data (database, volumes). Continue?'
M_uninstall_confirm_keep='This stops Cobble and removes the program from %s. The .env file and the data volumes are kept. Continue?'
M_uninstall_kept='Kept in %s: .env and state.json. Data volumes were not touched.'
M_uninstall_done='Cobble is uninstalled.'
M_reset_confirm='This signs the admin out and prints a one-use link to set a new email and password (projects and data are kept). Continue?'
M_version_installed='installed version: %s'

M_doc_docker_missing='Docker is not installed'
M_doc_docker_down='Docker is not running'
M_doc_docker_old='Docker server version %s is too old (24 or later required)'
M_doc_docker_ok='Docker server version %s'
M_doc_no_containers='No Cobble containers found'
M_doc_container_bad='state: %s, health: %s'
M_doc_containers_ok='%s containers running and healthy'
M_doc_http_down='No answer from %s'
M_doc_disk='%s GB free'
M_doc_port_noss='cannot check ports (ss is missing)'
M_doc_port_ok='port %s is listening'
M_doc_port_closed='nothing is listening on port %s'
M_doc_env_ok='%s has mode 0600'
M_doc_env_bad='.env has mode %s instead of 600'
M_doc_no_systemd='systemd is not available; boot-time start is not managed'
M_doc_unit_ok='cobble.service is active'
M_doc_unit_bad='cobble.service is not active'
M_doc_gpu='GPU: %s (container toolkit: %s)'
M_doc_summary_fail='%s check(s) failed.'
M_doc_summary_ok='All checks passed.'
M_doc_modules_notoken='MODULE_MANAGER_TOKEN is missing from .env'
M_doc_modules_nocatalog='the module catalogue is missing or empty (%s)'
M_doc_modules_ok='module catalogue found (%s modules)'
M_doc_modules_gid='Docker socket group changed (installed %s, now %s): the module-manager cannot use Docker'
M_modules_unreachable='cobble modules could not reach the module-manager: run cobble doctor'
M_fix_modules='Re-run the installer to repair the module settings: sudo bash install.sh --yes'
M_fix_docker_install='Install or upgrade Docker, or re-run the installer: sudo bash install.sh --yes'
M_fix_docker_start='Start it: sudo systemctl start docker'
M_fix_start='Start Cobble: sudo systemctl start cobble (or: cobble update)'
M_fix_container='See the logs: cobble logs <service>; restart with: sudo systemctl restart cobble'
M_fix_http='Check the containers above, then cobble logs caddy api'
M_fix_disk='Free some disk space (docker system prune removes unused images)'
M_fix_port='Check that the caddy container runs and that no firewall blocks the port'
M_fix_env='Fix it: sudo chmod 600 /opt/cobble/.env (adjust the path if you used --dir)'
M_fix_unit='Start it: sudo systemctl enable --now cobble'

M_cli_help='cobble: manage your Cobble installation

Usage: cobble <command>

  status               containers and web health
  logs [service]       follow the logs
  update [--source S]  rebuild and restart (or install the source S: dir, tarball, git URL)
  doctor               diagnose problems and suggest fixes (exit 1 if one fails)
  reset-admin [--yes]  print a one-use link to set a new admin email and password
  modules <command>    list, install and uninstall modules (cobble modules help)
  uninstall [--keep-data] [--yes]
                       stop and remove Cobble (--keep-data keeps .env and the volumes)
  version              print versions
  backup | restore     not available yet
  help                 this help'
