# INDEX — incident memory routing (derived, rebuildable)

每行：service | fault_type → incident 文件。派生物：与 incidents/ 不一致时以文件为准
（`python -m scripts.import_memory_coldstart --rebuild-index` 重建）。

| service | fault_type | incident | file |
|---|---|---|---|
| cart | memory_stress | cart-memory_stress-seed42 | incidents/cart-memory_stress-seed42.md |
| checkout | pod_crash | checkout-pod_crash-seed42 | incidents/checkout-pod_crash-seed42.md |
| email | pod_crash | email-pod_crash-seed42 | incidents/email-pod_crash-seed42.md |
| frontend | high_latency | frontend-high_latency-seed42 | incidents/frontend-high_latency-seed42.md |
| frontend | pod_crash | frontend-pod_crash-seed42 | incidents/frontend-pod_crash-seed42.md |
| payment | http_abort | payment-http_abort-seed42 | incidents/payment-http_abort-seed42.md |
| payment | http_abort | payment-network-partition-seed42 | incidents/payment-network-partition-seed42.md |
| product-catalog | high_latency | product-catalog-high_latency-seed42 | incidents/product-catalog-high_latency-seed42.md |
| quote | high_latency | quote-high_latency-seed42 | incidents/quote-high_latency-seed42.md |
| recommendation | cpu_stress | recommendation-cpu_stress-seed42 | incidents/recommendation-cpu_stress-seed42.md |
| shipping | high_latency | shipping-high_latency-seed42 | incidents/shipping-high_latency-seed42.md |
| checkout | pod_crash | watchdog-KubeDeploymentReplicasMismatch-88f37cbc | incidents/watchdog-KubeDeploymentReplicasMismatch-88f37cbc.md |
| checkout | pod_crash | watchdog-KubeDeploymentReplicasMismatch-fa7c76e6 | incidents/watchdog-KubeDeploymentReplicasMismatch-fa7c76e6.md |
| checkout | pod_crash | watchdog-KubePodCrashLooping-316567f7 | incidents/watchdog-KubePodCrashLooping-316567f7.md |
| quote | pod_crash | watchdog-KubePodNotReady-0e3c8389 | incidents/watchdog-KubePodNotReady-0e3c8389.md |
| checkout | pod_crash | watchdog-KubePodNotReady-195e11da | incidents/watchdog-KubePodNotReady-195e11da.md |
| checkout | pod_crash | watchdog-KubePodNotReady-3d474e83 | incidents/watchdog-KubePodNotReady-3d474e83.md |
| email | pod_crash | watchdog-KubePodNotReady-e170ff2c | incidents/watchdog-KubePodNotReady-e170ff2c.md |
| ad | http_abort | watchdog-OtelDemoHighClientErrorRate-11ae2a2b | incidents/watchdog-OtelDemoHighClientErrorRate-11ae2a2b.md |
| payment | http_abort | watchdog-OtelDemoHighClientErrorRate-2f18fc07 | incidents/watchdog-OtelDemoHighClientErrorRate-2f18fc07.md |
| recommendation | http_abort | watchdog-OtelDemoHighClientErrorRate-5ea53e32 | incidents/watchdog-OtelDemoHighClientErrorRate-5ea53e32.md |
| fraud-detection | http_abort | watchdog-OtelDemoHighClientErrorRate-d302b7b6 | incidents/watchdog-OtelDemoHighClientErrorRate-d302b7b6.md |
| frontend | http_abort | watchdog-OtelDemoHighErrorRate-3a0d3ec3 | incidents/watchdog-OtelDemoHighErrorRate-3a0d3ec3.md |
| frontend | http_abort | watchdog-OtelDemoHighErrorRate-549ee968 | incidents/watchdog-OtelDemoHighErrorRate-549ee968.md |
| checkout | http_abort | watchdog-OtelDemoHighErrorRate-5da54298 | incidents/watchdog-OtelDemoHighErrorRate-5da54298.md |
| ad | high_latency | watchdog-OtelDemoHighLatencyP99-5735b782 | incidents/watchdog-OtelDemoHighLatencyP99-5735b782.md |
| flagd | high_latency | watchdog-OtelDemoHighLatencyP99-6db6d1e6 | incidents/watchdog-OtelDemoHighLatencyP99-6db6d1e6.md |
| payment | high_latency | watchdog-OtelDemoHighLatencyP99-796321aa | incidents/watchdog-OtelDemoHighLatencyP99-796321aa.md |
| product-catalog | high_latency | watchdog-OtelDemoHighLatencyP99-985567ae | incidents/watchdog-OtelDemoHighLatencyP99-985567ae.md |
| product-catalog | high_latency | watchdog-OtelDemoHighLatencyP99-998068de | incidents/watchdog-OtelDemoHighLatencyP99-998068de.md |
| checkout | high_latency | watchdog-OtelDemoHighLatencyP99-a46af510 | incidents/watchdog-OtelDemoHighLatencyP99-a46af510.md |
| cart | high_latency | watchdog-OtelDemoHighLatencyP99-b47b613b | incidents/watchdog-OtelDemoHighLatencyP99-b47b613b.md |
| shipping | high_latency | watchdog-OtelDemoHighLatencyP99-b699fe05 | incidents/watchdog-OtelDemoHighLatencyP99-b699fe05.md |
| product-catalog | high_latency | watchdog-OtelDemoHighLatencyP99-c2dddb31 | incidents/watchdog-OtelDemoHighLatencyP99-c2dddb31.md |
| payment | high_latency | watchdog-OtelDemoHighLatencyP99-e972d4f8 | incidents/watchdog-OtelDemoHighLatencyP99-e972d4f8.md |
| product-catalog | high_latency | watchdog-OtelDemoHighLatencyP99-f919f10f | incidents/watchdog-OtelDemoHighLatencyP99-f919f10f.md |
| quote | pod_crash | watchdog-OtelDemoTelemetryAbsent-3fa4f1b3 | incidents/watchdog-OtelDemoTelemetryAbsent-3fa4f1b3.md |
