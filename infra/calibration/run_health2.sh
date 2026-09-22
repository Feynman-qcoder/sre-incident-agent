#!/bin/bash
for i in 4 5 6; do
  python3 /root/p1_calibration/sample_once.py > /root/p1_calibration/round_${i}.json 2>&1
  echo "ROUND_${i}_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /root/p1_calibration/progress.log
  [ $i -lt 6 ] && sleep 600
done
echo "ALL2_DONE" >> /root/p1_calibration/progress.log
