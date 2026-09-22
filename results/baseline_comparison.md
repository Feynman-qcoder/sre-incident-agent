# Baseline Comparison — run: 20260917T152725Z

| Method                 | Acc@1              | Acc@3              | MRR                | FT Acc             | Grounding          | Latency(s)         | Cost($)            |
|------------------------|--------------------|--------------------|--------------------|--------------------|--------------------|--------------------|--------------------|
| Random                 | 0.000              | 0.000              | 0.000              | 0.286              | 0.000              | 0.0s               | $0.0000            |
| Z-score error_rate     | 0.143              | 0.143              | 0.143              | 0.286              | 0.000              | 0.0s               | $0.0000            |
| Composite Z-score      | 0.286              | 0.286              | 0.286              | 0.286              | 0.000              | 0.0s               | $0.0000            |
| **SRE-Copilot**        | 1.000              | 1.000              | 1.000              | 1.000              | 0.893              | 29.9s              | $0.0281            |

## Notes
- Run ID: 20260917T152725Z
- Model: meta/llama-3.1-70b-instruct
- Seed: 42
- Baseline latency/cost 恒为 0 属口径约定（纯计算、无 LLM），非缺失
- Grounding score: fraction of evidence items verified against tool_calls_log
- Random baseline grounding_score=0.0 by design (no evidence items)
- Reproduce: `make eval-replay RUN_ID=20260917T152725Z`
