# Anomaly detection - evaluation

Synthetic data: 5,000 transfer events, 250 exfiltration (5%), 70/30 split stratified by attack pattern (seed 42). Test set: 1,500 events, 75 leaks. Threshold 0.5.

Isolation Forest: 200 trees, contamination 0.05, trained without labels (108 ms).

| Approach | Precision | Recall | F1-score | ROC-AUC | Leaks caught | False alarms |
|---|---|---|---|---|---|---|
| Rule-based heuristic | 66.7% | 66.7% | 66.7% | 79.45% | 50 of 75 | 25 |
| Isolation Forest | 98.6% | 90.7% | 94.4% | 99.96% | 68 of 75 | 1 |
| Proposed hybrid | 73.7% | 97.3% | 83.9% | 99.68% | 73 of 75 | 26 |

Isolation Forest ROC-AUC on the raw (unclipped) score: 99.96%.

## Leaks caught by pattern

| Pattern | Leaks | Heuristic | Isolation Forest | Hybrid |
|---|---|---|---|---|
| night bulk copy | 25 | 25 | 25 | 25 |
| large sensitive file | 25 | 0 | 23 | 23 |
| burst of small files | 25 | 25 | 20 | 25 |

## Review document (Figure 1) for comparison

| Approach | Precision | Recall | F1-score | ROC-AUC |
|---|---|---|---|---|
| Rule-based heuristic | 66.2% | 60.0% | 62.9% | 74.7% |
| Isolation Forest | 95.8% | 90.7% | 93.2% | 99.9% |
| Proposed hybrid | 74.2% | 96.0% | 83.7% | 99.7% |

Note: the data is synthetic. These numbers show that the method separates the simulated patterns; accuracy on real organisational data needs labelled real transfer logs.
