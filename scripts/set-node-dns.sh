#!/usr/bin/env bash
# Put every node's DNS behind systemd-resolved, so the DHCP client and Tailscale stop fighting over
# /etc/resolv.conf.
#
# Without it, Tailscale (MagicDNS, "direct" mode) owns /etc/resolv.conf and forwards everything that
# isn't a tailnet name to whatever nameserver it last saw there. dhclient rewrites the file on every
# lease renewal (about every 11 hours); Tailscale notices and re-learns the router from it. If it reads
# the file mid-rewrite, while it's empty, it's left with no upstream and answers every outside name
# with SERVFAIL until the next renewal. node-local-dns forwards to Tailscale, so that broke DNS for
# every pod on the node (homelab-soquartz-4, 2026-10-15 01:11-11:57).
#
# With systemd-resolved, dhclient hands the router's DNS to resolved (isc-dhcp-client's resolved hooks)
# instead of writing the file, and Tailscale registers only the tailnet's domains with resolved. Outside
# names go straight to the router; tailnet names go to Tailscale. k0s notices resolved when kubelet
# starts and gives pods /run/systemd/resolve/resolv.conf rather than the 127.0.0.53 stub.
#
# Usage: scripts/set-node-dns.sh [--check] [host ...]
#   Hosts default to the ones in k0sctl.yaml (ssh user dietpi), one at a time; it stops at the first
#   node that doesn't check out. --check only reports.
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

# Run as root on the node.
apply_script=$(cat <<'EOF'
set -euo pipefail
iface=$(ip route show default | awk '{print $5; exit}')
if ! dpkg -s systemd-resolved >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q systemd-resolved >/dev/null
fi
mkdir -p /etc/systemd/resolved.conf.d
printf '[Resolve]\n# Nothing on this network uses them.\nLLMNR=no\nMulticastDNS=no\n' > /etc/systemd/resolved.conf.d/homelab.conf
systemctl enable --now systemd-resolved >/dev/null 2>&1
systemctl restart systemd-resolved
ln -sfn ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
# The DHCP hook updates resolved at each renewal; until the next one, use the current lease.
lease="/var/lib/dhcp/dhclient.${iface}.leases"
if [ -f "$lease" ]; then
  dns=$(sed -n 's/^ *option domain-name-servers \(.*\);/\1/p' "$lease" | tail -1 | tr ',' ' ')
  domain=$(sed -n 's/^ *option domain-name "\(.*\)";/\1/p' "$lease" | tail -1)
  # shellcheck disable=SC2086 # one argument per server
  [ -n "$dns" ] && resolvectl dns "$iface" $dns
  [ -n "$domain" ] && resolvectl domain "$iface" "$domain"
fi
# Tailscale picks its DNS mode when it starts: now it registers the tailnet with resolved.
systemctl restart tailscaled
sleep 5
# kubelet reads resolv.conf's path when k0s starts it. Running containers keep running.
for unit in k0sworker k0scontroller; do
  if systemctl cat "$unit.service" >/dev/null 2>&1; then
    systemctl restart "$unit"
  fi
done
# k0s writes kubelet's config a moment after it starts.
for _ in $(seq 1 60); do
  grep -q '^resolvConf: /run/systemd/resolve/resolv.conf' /run/k0s/kubelet/config.yaml 2>/dev/null && break
  sleep 2
done
EOF
)

check_script=$(cat <<'EOF'
iface=$(ip route show default | awk '{print $5; exit}')
tailnet=$(tailscale status --self --peers=false --json 2>/dev/null | sed -n 's/.*"DNSName": "\([^"]*\)\.".*/\1/p' | head -1)
kubelet=$(sed -n 's/^resolvConf: //p' /run/k0s/kubelet/config.yaml 2>/dev/null)
printf 'resolved=%s resolv.conf=%s upstream=%s tailscale=%s kubelet=%s outside=%s tailnet=%s' \
  "$(systemctl is-active systemd-resolved 2>/dev/null)" \
  "$(readlink /etc/resolv.conf || echo file)" \
  "$(resolvectl dns "$iface" 2>/dev/null | sed 's/.*: *//' | tr ' ' ',')" \
  "$(resolvectl dns tailscale0 2>/dev/null | grep -q 100.100.100.100 && echo resolved || echo direct)" \
  "${kubelet:-?}" \
  "$(getent ahosts pkg-containers.githubusercontent.com >/dev/null && echo ok || echo FAIL)" \
  "$( [ -n "$tailnet" ] && getent ahosts "$tailnet" >/dev/null && echo ok || echo FAIL)"
EOF
)

status=0
for host in "${hosts[@]}"; do
  if ! $check; then
    echo "${host}: switching to systemd-resolved…"
    if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "dietpi@${host}" 'sudo bash -s' <<< "$apply_script"; then
      echo "${host}: couldn't switch to systemd-resolved" >&2
      exit 1
    fi
    if command -v kubectl >/dev/null; then
      kubectl wait "node/${host}" --for=condition=Ready --timeout=180s >/dev/null || {
        echo "${host}: node not Ready after restarting k0s" >&2
        exit 1
      }
    fi
    sleep 5
  fi
  report=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "dietpi@${host}" 'sudo bash -s' <<< "$check_script" 2>/dev/null) || report="unreachable"
  echo "${host}: ${report}"
  case "$report" in
    *"resolved=active resolv.conf=../run/systemd/resolve/stub-resolv.conf"*"tailscale=resolved kubelet=/run/systemd/resolve/resolv.conf outside=ok tailnet=ok") ;;
    *)
      status=1
      $check || exit 1 # stop the rollout at the first node that doesn't check out
      ;;
  esac
done
exit "$status"
