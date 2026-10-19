# Algorithm comparison (mean of seeds 1-5)

| Algorithm | Precision | Recall | F1-score | ROC-AUC | Training time | Review doc (P / R / F1 / AUC) |
|---|---|---|---|---|---|---|
| Isolation Forest | 93.5% | 91.7% | 92.6% | 99.8% | 108 ms | 92.2% / 93.6% / 92.8% / 99.9% |
| Elliptic Envelope | 82.6% | 85.1% | 83.6% | 99.6% | 325 ms | 85.1% / 82.4% / 83.5% / 99.6% |
| One-Class SVM | 67.8% | 74.9% | 71.0% | 93.8% | 13 ms | 66.4% / 77.1% / 71.3% / 94.6% |
| Frequency heuristic | 65.7% | 66.9% | 66.3% | 78.7% | none | 62.8% / 65.6% / 64.0% / 78.5% |
| Local Outlier Factor | 14.1% | 14.7% | 14.3% | 52.4% | 35 ms | 20.6% / 20.8% / 20.7% / 68.4% |

Training time depends on the machine.

# Luhn test

Random 16-digit numbers: 10,000 (seed 42).

- False alarms with the card regex only: **10,000**
- False alarms with regex + Luhn: **980** (90.2% fewer)
- Standard test card numbers detected: 6 of 6 (Visa, Mastercard, Amex, Discover, JCB, Diners Club)
