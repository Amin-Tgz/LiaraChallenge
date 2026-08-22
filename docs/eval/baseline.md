# Golden Set Baseline

خروجی `scripts/evaluate.py`. اعداد بخش «قطعی» بدون هیچ فراخوانی مدل محاسبه
شده‌اند؛ اعداد داور با مدل داور محاسبه شده‌اند و قبل از اعتماد باید دستی
بازبینی شوند (طرح §۲۶).

- generated_at: `2026-08-22T03:56:44+00:00`
- model_under_test: `gemini-3.7-flash`
- judge_model: `gpt-5.6-terra`
- k: `8`
- similarity_threshold: `0.2125`
- index_version: `79616001-aafd-47b4-b2e1-453fb385dddb`

## Deterministic

| متریک | مقدار |
|---|---:|
| Recall@8 | 0.767 |
| Citation correctness | 0.625 |
| Grounded citations | 1.000 |
| Clarification correctness | 0.800 |
| Abstention correctness | 1.000 |
| Mean latency (ms) | 7890 |
| Total tokens | 121128 |

## Judge

| متریک | مقدار |
|---|---:|
| Answer relevance | 4.89 |
| Answer completeness | 4.00 |
| Groundedness | 4.11 |
| Unsupported-claim rate | 0.556 |

## Per question

| # | difficulty | Recall@8 | citation | clarification | abstention | tokens | ms |
|---|---|---:|---:|:-:|:-:|---:|---:|
| Q1 | easy | 1.00 | 1.00 | ✓ | ✓ | 6453 | 6487 |
| Q2 | easy | 1.00 | 1.00 | ✓ | ✓ | 6642 | 5594 |
| Q3 | easy | 1.00 | 0.00 | ✓ | ✓ | 0 | 3421 |
| Q4 | hard | 1.00 | 1.00 | ✓ | ✓ | 8516 | 6863 |
| Q5 | hard | 0.33 | 1.00 | ✓ | ✓ | 8270 | 7693 |
| Q6 | medium | 1.00 | 0.50 | ✓ | ✓ | 6915 | 7426 |
| Q7 | medium | 1.00 | 0.50 | ✓ | ✓ | 7822 | 7268 |
| Q8 | medium | 0.00 | 0.50 | ✗ | ✓ | 15541 | 8085 |
| Q9 | medium | 0.33 | 0.25 | ✗ | ✓ | 19853 | 15448 |
| Q10 | hard | 1.00 | 0.50 | ✓ | ✓ | 28000 | 10612 |
