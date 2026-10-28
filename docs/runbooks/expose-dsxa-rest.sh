#!/usr/bin/env bash
# Expose the DSX/A 4.3 REST scanner (release dsxa-430 on cluster dsxa422-xvmn9) on an external
# GCP load balancer, reachable only from ALLOWED source IPs. Plain HTTP on port 80.
# Usage: bash expose-dsxa-rest.sh [CIDR ...]   (default: this machine's current public IP)
set -euo pipefail
ALLOWED=("$@"); [ ${#ALLOWED[@]} -eq 0 ] && ALLOWED=("$(curl -s https://checkip.amazonaws.com)/32")
RANGES=$(printf '"%s",' "${ALLOWED[@]}"); RANGES="[${RANGES%,}]"
echo "Allowing: $RANGES"

gcloud compute ssh ocp-sno-admin --zone us-east1-b --tunnel-through-iap --quiet --command "
set -e; cd ~/ocp422; export KUBECONFIG=install-dsxa422-r4/auth/kubeconfig
sed -i 's/^    type: ClusterIP\$/    type: LoadBalancer      # external IP; source IPs restricted via loadBalancerSourceRanges/' dsxa-430-values.yaml
~/linux-amd64/helm upgrade dsxa-430 dpa-4.3.0.2347/dpa/dpa-chart -n dsxa-430 -f dsxa-430-values.yaml | grep -E 'STATUS|REVISION'
./oc patch svc rest-1 -n dsxa-430 --type merge -p '{\"spec\":{\"loadBalancerSourceRanges\":$RANGES}}'
for i in \$(seq 1 30); do ip=\$(./oc get svc rest-1 -n dsxa-430 -o jsonpath='{.status.loadBalancer.ingress[0].ip}'); [ -n \"\$ip\" ] && break; sleep 10; done
./oc get svc rest-1 -n dsxa-430 -o wide
echo \"sourceRanges: \$(./oc get svc rest-1 -n dsxa-430 -o jsonpath='{.spec.loadBalancerSourceRanges}')\"
echo \"Test: curl -X POST http://\$ip/scan/binary/v2 -H 'Content-Type: application/octet-stream' --data-binary @/bin/ls\"
" 2>&1 | grep -v -i -e numpy -e tcp_upload -e '^WARNING'
