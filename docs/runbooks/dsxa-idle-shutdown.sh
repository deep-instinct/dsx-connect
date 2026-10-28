#!/usr/bin/env bash
# Stop the single-node OpenShift VM after a period with no DSX/A use.
# Runs from cron on the admin VM (ocp-sno-admin) every 5 minutes.
#
# "In use" means any of:
#   - a REST or ICAP scan logged in the last 10 minutes (any dsxa-* namespace)
#   - an SSH/IAP session into this admin VM (SOCKS tunnel for k9s/console, gcloud ssh)
#   - the cluster VM started less than IDLE_MINUTES ago (boot grace period)
# If none of these has been true for IDLE_MINUTES, the cluster VM is stopped.
#
# Install:  crontab line  */5 * * * * $HOME/bin/dsxa-idle-shutdown.sh >> $HOME/dsxa-idle.log 2>&1
# Disable:  touch ~/.dsxa-idle/disabled     (re-enable: rm ~/.dsxa-idle/disabled)
set -uo pipefail

VM=dsxa422-xvmn9-master-0
ZONE=us-east1-b
IDLE_MINUTES=${IDLE_MINUTES:-60}
export KUBECONFIG=$HOME/ocp422/install-dsxa422-r4/auth/kubeconfig
OC=$HOME/ocp422/oc
STATE=$HOME/.dsxa-idle
mkdir -p "$STATE"

now=$(date +%s)
log() { echo "$(date -u +%FT%TZ) $*"; }

[ -e "$STATE/disabled" ] && exit 0

status=$(gcloud compute instances describe "$VM" --zone "$ZONE" --format='value(status)' 2>/dev/null)
[ "$status" = "RUNNING" ] || exit 0

# Boot grace: count the VM's last start as activity.
started=$(date -d "$(gcloud compute instances describe "$VM" --zone "$ZONE" --format='value(lastStartTimestamp)')" +%s 2>/dev/null || echo 0)
last=$(cat "$STATE/last_active" 2>/dev/null || echo 0)
[ "$started" -gt "$last" ] && last=$started

reason=""
sessions=$(ss -Htn state established '( sport = :22 )' 2>/dev/null | wc -l)
[ "$sessions" -gt 0 ] && reason="ssh sessions=$sessions"

if [ -z "$reason" ]; then
  if ! $OC --request-timeout=20s get ns >/dev/null 2>&1; then
    reason="cluster API not answering (booting?)"   # never stop on uncertainty
  else
    scans=0
    for ns in $($OC get ns -o name | sed -n 's#namespace/\(dsxa-.*\)#\1#p'); do
      for d in $($OC get deploy -n "$ns" -o name 2>/dev/null | grep -E '/(rest|icap)-'); do
        n=$($OC logs -n "$ns" "$d" -c dpa --since=10m 2>/dev/null | grep -c '"scan_guid".*"verdict"')
        scans=$((scans + n))
      done
    done
    [ "$scans" -gt 0 ] && reason="scans in last 10m=$scans"
  fi
fi

if [ -n "$reason" ]; then
  echo "$now" > "$STATE/last_active"
  exit 0
fi

idle=$(( (now - last) / 60 ))
if [ "$idle" -ge "$IDLE_MINUTES" ]; then
  log "idle ${idle}m (>= ${IDLE_MINUTES}m): stopping $VM"
  gcloud compute instances stop "$VM" --zone "$ZONE" --async --quiet && echo "$now" > "$STATE/last_active"
fi
