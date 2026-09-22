#!/bin/bash
export KUBECONFIG=/root/.kube/config
for i in 1 2 3 4 5 6 7; do
  sleep 300
  TS=$(date -u +%H:%M:%S)
  LOAD=$(cat /proc/loadavg | cut -d" " -f1-3)
  FRONT=$(curl -s --max-time 10 -G http://localhost:9090/api/v1/query --data-urlencode "query=sum(rate(calls_total{service_name=\"frontend\",span_kind=\"SPAN_KIND_SERVER\"}[2m]))" | python3 -c "import json,sys
try:
    r=json.load(sys.stdin)[\"data\"][\"result\"]
    print(round(float(r[0][\"value\"][1]),2) if r else \"NA\")
except Exception:
    print(\"ERR\")" 2>/dev/null)
  NSVC=$(curl -s --max-time 10 -G http://localhost:9090/api/v1/query --data-urlencode "query=count(sum by (service_name) (rate(calls_total{span_kind=\"SPAN_KIND_SERVER\"}[2m])) > 0)" | python3 -c "import json,sys
try:
    r=json.load(sys.stdin)[\"data\"][\"result\"]
    print(r[0][\"value\"][1] if r else \"NA\")
except Exception:
    print(\"ERR\")" 2>/dev/null)
  LG=$(kubectl -n otel-demo get pods -l app.kubernetes.io/component=load-generator --no-headers 2>/dev/null | head -1 | awk "{print \$1, \$3}" || echo k8s_err)
  echo "$TS load=[$LOAD] frontend=$FRONT nonzero_svcs=$NSVC lg=[$LG]" >> /root/p1_calibration/observe.log
  echo "OBS_${i}_DONE" >> /root/p1_calibration/progress.log
done
echo "OBSERVE_ALL_DONE" >> /root/p1_calibration/progress.log
