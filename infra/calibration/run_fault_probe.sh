#!/bin/bash
# A-3: 注入场景 002 并在故障期采样（注入后 2-7 分钟每分钟一次）
cd /root/sre-incident-agent
export KUBECONFIG=/root/.kube/config
date -u +%Y-%m-%dT%H:%M:%SZ > /root/p1_calibration/fault_t0.txt
nohup .venv/bin/python scripts/inject_and_snapshot.py --scenario scenarios/mvp/002-productcatalogservice-high-latency.yaml > /root/p1_calibration/inject_002.log 2>&1 &
for i in 2 3 4 5 6 7; do
  sleep 60
  python3 /root/p1_calibration/sample_once.py > /root/p1_calibration/fault_min_.json 2>&1
  echo "FAULT_SAMPLE_MIN__DONE" >> /root/p1_calibration/progress.log
done
echo "FAULT_PROBE_ALL_DONE" >> /root/p1_calibration/progress.log
