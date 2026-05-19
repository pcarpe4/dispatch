#!/usr/bin/env bash
# find-non-olm-operators.sh
# Discover operator-like workloads on an OpenShift cluster that are NOT managed by OLM.
#
# Output: CSV to stdout with columns:
#   namespace,workload,kind,install_method,helm_release,suspected_crds
#
# Requires: oc (logged in with cluster-read), jq. Optional: helm (for release lookup).
#
# Usage:
#   ./find-non-olm-operators.sh                 # report to stdout
#   ./find-non-olm-operators.sh > report.csv
#   DEBUG=1 ./find-non-olm-operators.sh         # also print intermediate files locations
#
set -euo pipefail

for bin in oc jq; do
  command -v "$bin" >/dev/null || { echo "missing required binary: $bin" >&2; exit 1; }
done
HAVE_HELM=0; command -v helm >/dev/null && HAVE_HELM=1

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
[[ "${DEBUG:-0}" == "1" ]] && echo "workdir: $WORK" >&2

############################################
# 1. CRDs owned by OLM CSVs vs all CRDs
############################################
oc get csv -A -o json > "$WORK/csvs.json"
jq -r '.items[].spec.customresourcedefinitions.owned[]?.name' "$WORK/csvs.json" \
  | sort -u > "$WORK/olm-crds.txt"

oc get crd -o json > "$WORK/crds.json"
jq -r '.items[].metadata.name' "$WORK/crds.json" | sort -u > "$WORK/all-crds.txt"

# CRDs not owned by OLM, with platform/built-in groups filtered out.
comm -23 "$WORK/all-crds.txt" "$WORK/olm-crds.txt" \
  | grep -Ev '\.(k8s\.io|openshift\.io|cncf\.io|tekton\.dev|knative\.dev)$' \
  | grep -Ev '\.(config|operator|machine|machineconfiguration|network|console|samples|imageregistry|authorization|security|quota|template|route|build|apps|project|user|oauth|monitoring|whereabouts|metal3)\.openshift\.io$' \
  > "$WORK/nonolm-crds.txt" || true

############################################
# 2. Map each non-OLM CRD -> controller deployment
#    Heuristic: find Deployments/StatefulSets whose pods have RBAC or args referencing
#    the CRD's group, AND that are NOT owned by a ClusterServiceVersion.
############################################
oc get deploy,sts -A -o json > "$WORK/workloads.json"

# Candidate workloads: not owned by a CSV, operator-ish name OR has leader-election arg.
jq -r '
  .items[]
  | select(
      ( [.metadata.ownerReferences[]?.kind] | index("ClusterServiceVersion") | not )
      and ( .metadata.labels["olm.owner"] // "" ) == ""
    )
  | select(
      (.metadata.name | test("operator|controller|manager"; "i"))
      or ( [.spec.template.spec.containers[].args[]?] | tostring | test("leader-elect|--metrics-bind|--health-probe"))
    )
  | [.metadata.namespace, .kind, .metadata.name] | @tsv
' "$WORK/workloads.json" > "$WORK/candidates.tsv"

############################################
# 3. For each candidate, gather install metadata + suspected CRDs it manages
############################################
echo "namespace,workload,kind,install_method,helm_release,suspected_crds"

while IFS=$'\t' read -r ns kind name; do
  [[ -z "$ns" ]] && continue

  obj_json=$(jq -c --arg ns "$ns" --arg k "$kind" --arg n "$name" '
    .items[] | select(.metadata.namespace==$ns and .kind==$k and .metadata.name==$n)
  ' "$WORK/workloads.json")

  managed_by=$(jq -r '.metadata.labels["app.kubernetes.io/managed-by"] // ""' <<<"$obj_json")
  helm_rel=$(jq -r '.metadata.annotations["meta.helm.sh/release-name"] // ""' <<<"$obj_json")
  kustomize_lbl=$(jq -r '.metadata.labels["kustomize.toolkit.fluxcd.io/name"] // ""' <<<"$obj_json")
  argocd_lbl=$(jq -r '.metadata.labels["app.kubernetes.io/instance"] // ""' <<<"$obj_json")

  if [[ "$managed_by" == "Helm" || -n "$helm_rel" ]]; then
    method="helm"
  elif [[ -n "$kustomize_lbl" ]]; then
    method="flux-kustomize"
  elif [[ -n "$argocd_lbl" && "$managed_by" != "Helm" ]]; then
    method="argocd-or-manual"
  else
    method="manual-or-unknown"
  fi

  # Suspected CRDs: look at this workload's ServiceAccount RBAC for non-OLM CRD groups.
  sa=$(jq -r '.spec.template.spec.serviceAccountName // "default"' <<<"$obj_json")
  groups_from_rbac=$(
    oc get rolebinding,clusterrolebinding -A -o json 2>/dev/null \
    | jq -r --arg ns "$ns" --arg sa "$sa" '
        .items[]
        | select(.subjects[]? | select(.kind=="ServiceAccount" and .name==$sa and (.namespace // $ns)==$ns))
        | .roleRef.name' \
    | sort -u \
    | while read -r role; do
        oc get clusterrole "$role" -o json 2>/dev/null \
        || oc get role "$role" -n "$ns" -o json 2>/dev/null
      done \
    | jq -r '.rules[]?.apiGroups[]?' 2>/dev/null \
    | sort -u
  )

  suspected=$(
    if [[ -s "$WORK/nonolm-crds.txt" && -n "$groups_from_rbac" ]]; then
      while read -r g; do
        [[ -z "$g" ]] && continue
        grep -E "\.${g//./\\.}$" "$WORK/nonolm-crds.txt" || true
      done <<<"$groups_from_rbac" | sort -u | paste -sd';' -
    fi
  )

  printf '%s,%s,%s,%s,%s,"%s"\n' \
    "$ns" "$name" "$kind" "$method" "$helm_rel" "${suspected:-}"
done < "$WORK/candidates.tsv"

############################################
# 4. Footer summary to stderr
############################################
{
  echo ""
  echo "== summary =="
  echo "Non-OLM CRDs detected: $(wc -l < "$WORK/nonolm-crds.txt")"
  echo "Candidate workloads:   $(wc -l < "$WORK/candidates.tsv")"
  if [[ "$HAVE_HELM" == "1" ]]; then
    echo ""
    echo "== helm releases (cross-reference) =="
    helm ls -A 2>/dev/null || true
  fi
} >&2
