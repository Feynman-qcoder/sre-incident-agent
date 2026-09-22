#!/bin/bash
for i in 1 2 3; do
  python3 /root/p1_calibration/sample_once.py > /root/p1_calibration/round_${i}.json 2>&1
  echo "ROUND_${i}_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /root/p1_calibration/progress.log
  [ $i -lt 3 ] && sleep 600
done
echo "ALL_DONE" >> /root/p1_calibration/progress.log
