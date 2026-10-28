#!/usr/bin/env bash
# Tear down the orphaned OpenShift cluster dsxa424-n7j78 (project se-project-388112, us-east1).
# Only touches resources named for n7j78 / dsxa424. The shared VPC (ocp-sno-net), the
# ocp-test public zone itself, and the working cluster dsxa422-xvmn9 are left alone.
set -uo pipefail
P=se-project-388112; R=us-east1; Z=us-east1-b; LB=a2040970c09b5472f93233f84897219c
g() { echo "+ gcloud $*"; gcloud --project "$P" --quiet "$@" || echo "  (failed, continuing)"; }

# 1. VMs (boot disks auto-delete; disk delete below catches leftovers)
g compute instances delete dsxa424-n7j78-bootstrap dsxa424-n7j78-master-0 --zone $Z
g compute disks delete dsxa424-n7j78-bootstrap dsxa424-n7j78-master-0 --zone $Z

# 2. Ingress LB created by the cluster's router-default service
g compute forwarding-rules delete $LB --region $R
g compute target-pools delete $LB --region $R
g compute firewall-rules delete k8s-$LB-http-hc k8s-fw-$LB
g compute http-health-checks delete k8s-$LB 2>/dev/null

# 3. API load balancers
g compute forwarding-rules delete dsxa424-n7j78-apiserver dsxa424-n7j78-api-internal --region $R
g compute target-tcp-proxies delete dsxa424-n7j78-apiserver
g compute backend-services delete dsxa424-n7j78-apiserver --global
g compute backend-services delete dsxa424-n7j78-api-internal --region $R
g compute health-checks delete dsxa424-n7j78-apiserver dsxa424-n7j78-api-internal
g compute addresses delete dsxa424-n7j78-apiserver --global
g compute addresses delete dsxa424-n7j78-api-internal --region $R
for zz in b c d; do g compute instance-groups unmanaged delete dsxa424-n7j78-master-$R-$zz --zone $R-$zz; done

# 4. Firewall rules
g compute firewall-rules delete allow-dsxa424-n7j78-cluster allow-dsxa424-n7j78-healthchecks \
  dsxa424-n7j78-api dsxa424-n7j78-bootstrap-in-ssh dsxa424-n7j78-control-plane dsxa424-n7j78-etcd \
  dsxa424-n7j78-health-checks dsxa424-n7j78-internal-cluster dsxa424-n7j78-internal-network

# 5. DNS: public records for dsxa424, then the private zone
g dns record-sets delete api.dsxa424.ocp-test.deepinstinctweb.com. --type A --zone ocp-test
g dns record-sets delete '*.apps.dsxa424.ocp-test.deepinstinctweb.com.' --type A --zone ocp-test
for n in api.dsxa424 api-int.dsxa424 '*.apps.dsxa424'; do
  g dns record-sets delete "$n.ocp-test.deepinstinctweb.com." --type A --zone dsxa424-n7j78-private-zone
done
g dns managed-zones delete dsxa424-n7j78-private-zone

# 6. Buckets and service accounts
g storage rm -r gs://dsxa424-n7j78-bootstrap-ignition/ gs://dsxa424-n7j78-image-registry-us-east1-hhhgkumtcfcvtnbnvftpnnbt/
g iam service-accounts delete dsxa424-n7j78-m@$P.iam.gserviceaccount.com
g iam service-accounts delete dsxa424-n7j78-w@$P.iam.gserviceaccount.com

echo; echo "Leftovers (should be empty):"
gcloud --project "$P" compute instances list --filter='name~n7j78' --format='value(name)'
gcloud --project "$P" compute firewall-rules list --filter='name~n7j78' --format='value(name)'
gcloud --project "$P" compute forwarding-rules list --filter='name~n7j78' --format='value(name)'
