#!/usr/bin/env bash
# Keep every node's clock synced continuously (DietPi time sync mode 4: daemon + drift).
#
# The SoQuartz boards have no battery-backed clock: after a power loss they boot with the last time
# fake-hwclock saved. DietPi's default mode syncs once at boot (and daily); if the network isn't up
# yet, that sync fails and the node runs hours behind, which breaks TLS, tokens and Kubernetes leases.
# Mode 4 keeps systemd-timesyncd running, so a node catches up as soon as it can reach a time server.
#
# Usage: scripts/set-node-time-sync.sh [--check] [host ...]
#   Hosts default to the ones in k0sctl.yaml (ssh user dietpi). --check only reports.
set -euo pipefail

check=false
if [ "${1:-}" = "--check" ]; then
  check=true
  shift
fi

cd "$(dirname "$0")/.."
if [ "$#" -gt 0 ]; then
  hosts=("$@")
else
  read -r -a hosts <<< "$(awk '/address:/ {print $2}' k0sctl.yaml | tr '\n' ' ')"
fi

status=0
for host in "${hosts[@]}"; do
  if ! $check; then
    if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "dietpi@${host}" \
        'sudo /boot/dietpi/func/dietpi-set_software ntpd-mode 4 >/dev/null' 2>/dev/null; then
      echo "${host}: couldn't set the time sync mode" >&2
      status=1
      continue
    fi
  fi
  report=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "dietpi@${host}" \
    'printf "mode=%s ntp=%s synced=%s timesyncd=%s" \
       "$(sed -n "s/^CONFIG_NTP_MODE=//p" /boot/dietpi.txt)" \
       "$(timedatectl show -p NTP --value)" \
       "$(timedatectl show -p NTPSynchronized --value)" \
       "$(systemctl is-active systemd-timesyncd)"' 2>/dev/null) || report="unreachable"
  echo "${host}: ${report}"
  case "$report" in
    *"mode=4 ntp=yes"*"timesyncd=active"*) ;;
    *) status=1 ;;
  esac
done
exit "$status"
