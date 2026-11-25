#!/usr/bin/env bash
# Spark retirement wipe: remove everything an operator can remove from inside
# the running DGX OS. This is NOT a factory reset -- it cannot reflash firmware,
# erase the SSD securely, or reinstall DGX OS. For that use the Founders Edition
# USB recovery media (developer.nvidia.com), which erases the internal SSD.
#
# Default is a dry run. Use --yes to actually execute. Run it from the console
# (or over SSH) as the admin user; it re-executes itself with sudo.
set -uo pipefail

APPLY=0
DELETE_USER=""
KEEP_HOME=0
ACTIONS=()

usage() {
  cat <<'EOF'
usage: spark_retirement_wipe.sh [--yes] [--delete-user NAME] [--keep-home]

  (default)            dry run: print the actions, change nothing
  --yes                execute the actions
  --delete-user NAME   also delete this account and its home after the wipe
                       (only meaningful when nobody needs to log in any more;
                        the machine then has no sudo user until recovery/OOBE)
  --keep-home          clean services/logs/credentials but leave user files
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --yes) APPLY=1 ;;
    --delete-user) shift; DELETE_USER="${1:-}" ;;
    --keep-home) KEEP_HOME=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

say()  { printf '\033[1;35m[wipe]\033[0m %s\n' "$*"; }
run()  { ACTIONS+=("$*"); if [ "$APPLY" = "1" ]; then bash -c "$*"; fi; }

if [ "$APPLY" = "1" ] && [ "$(id -u)" != "0" ]; then
  echo "re-executing with sudo (you will be prompted for your password)" >&2
  exec sudo -- "$0" --yes ${DELETE_USER:+--delete-user "$DELETE_USER"} $([ "$KEEP_HOME" = 1 ] && echo --keep-home)
fi

say "mode: $([ "$APPLY" = "1" ] && echo APPLY || echo DRY-RUN)"
say "this removes services, caches, logs, credentials and demo data."
say "it does NOT erase the SSD or restore firmware; see the header."

# ---------------------------------------------------------------- 1. demo + user services
say "1. stopping the chat demo and any user services"
run "pkill -f 'spark-chat-demo/.*llama-server' 2>/dev/null || true"
run "pkill -f 'scripts/serve.py --host 0.0.0.0 --port 8088' 2>/dev/null || true"
run "rm -rf /home/*/spark-chat-demo /home/*/spark-chat-demo-src"
run "systemctl stop 'user@*.service' 2>/dev/null || true"

# ---------------------------------------------------------------- 2. docker
say "2. removing containers, images, volumes and build cache"
run "docker ps -aq | xargs -r docker rm -f"
run "docker images -q | xargs -r docker rmi -f"
run "docker volume ls -q | xargs -r docker volume rm"
run "docker system prune -af --volumes"

# ---------------------------------------------------------------- 3. logs and caches
say "3. clearing journal, logs, caches, temp"
run "journalctl --rotate && journalctl --vacuum-time=1s"
run "rm -rf /var/log/*.gz /var/log/*.1 /var/log/journal/* /tmp/* /var/tmp/*"
run "apt-get clean"
run "rm -rf /root/.cache /home/*/.cache /home/*/.local/share/Trash"

# ---------------------------------------------------------------- 4. credentials
say "4. removing credentials: ssh keys, known_hosts, git/docker creds, shell history"
run "rm -rf /root/.ssh /home/*/.ssh/id_* /home/*/.ssh/known_hosts*"
run "rm -rf /root/.docker /home/*/.docker/config.json /root/.config/gh /home/*/.config/gh"
run "rm -f /root/.bash_history /root/.python_history /home/*/.bash_history /home/*/.zsh_history /home/*/.python_history"
run "find /home -maxdepth 3 -name '*.env' -path '*/tongxing/*' -delete 2>/dev/null || true"
run "rm -f /home/*/.gitconfig /home/*/.netrc /home/*/.aws/credentials"

# ---------------------------------------------------------------- 5. user data
if [ "$KEEP_HOME" = "0" ]; then
  say "5. removing user files under /home (keeping dotfiles needed to log in)"
  run "find /home -mindepth 2 -maxdepth 2 -not -name '.*' -exec rm -rf {} +"
else
  say "5. --keep-home: user files left in place"
fi

# ---------------------------------------------------------------- 6. optional account removal
if [ -n "$DELETE_USER" ]; then
  say "6. deleting account '$DELETE_USER' (no sudo user will remain)"
  run "pkill -KILL -u '$DELETE_USER' 2>/dev/null || true"
  run "userdel -r '$DELETE_USER' 2>/dev/null || true"
fi

# ---------------------------------------------------------------- 7. report
say "7. summary"
if [ "$APPLY" = "1" ]; then
  say "executed ${#ACTIONS[@]} actions"
  say "remaining listeners (excluding loopback services):"
  ss -ltn 2>/dev/null | awk 'NR>1{print "   ", $4}' | grep -vE '127.0.0|::1' || true
  say "disk: $(df -h / | tail -1)"
  say "still installed: the DGX OS itself, /opt/nvidia tooling, ssd contents outside /home"
else
  printf '   %s\n' "${ACTIONS[@]}"
  say "dry run only: nothing changed. Re-run with --yes to apply."
fi
say "for a true factory reset: 16 GB+ USB, keyboard, display, Founders Edition"
say "recovery media from developer.nvidia.com; boot override -> START RECOVERY."
