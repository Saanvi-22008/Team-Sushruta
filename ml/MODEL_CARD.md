# Trend watch: model card

**What it is.** A small logistic-regression model that looks at the last 6 readings (pH, skin temperature, moisture) and estimates the chance that **pH will cross the placeholder "see a doctor" line (7.5) within the next 4 readings**. The app shows it as an experimental, advisory "Trend watch" on the History tab.

**What it is not.** It does not decide the safety status. The status comes only from the rules in `backend/safety.py`. The model cannot raise, lower or hide a warning.

## Data: where it comes from

| Question | Honest answer |
| --- | --- |
| Is there real patient data? | No. |
| Is there a public dataset for pH + temperature + moisture patch readings? | None that we found. Published smart-bandage work exists, but not as an open sensor dataset. |
| What was used? | Synthetic trajectories from `ml/generate_data.py`: healing, stalled, and healing-that-turns-into-infection courses, with noise and 2% random sensor dropouts. |
| Is it circular? | Partly, yes. We wrote the curves, so the model learns our assumptions. Results show the pipeline works, **not** clinical accuracy. |

## Pipeline

```
ml/generate_data.py  ->  ml/data/synthetic.jsonl (not committed, ~40 MB)
ml/features.py       ->  11 features per 6-reading window
ml/train.py          ->  split by wound, scale, fit, evaluate, export
ml/model.json        ->  weights + scaling + metrics (committed, ~2 KB)
backend/trend.py     ->  loads model.json, scores in pure Python
GET /api/trend       ->  advisory result for the latest 6 stored readings
```

Reproduce from the repo root:

```
pip install -r ml/requirements.txt
python -m ml.generate_data
python -m ml.train
```

## Design choices

- **Logistic regression**, not a neural network: tiny data, every weight is readable, trains in seconds, and exports to a 2 KB JSON file so the API needs no ML library.
- **Split by wound**, not by row: a wound never appears in both train and test, so the score is not inflated by memorising one trajectory.
- **Windows that already crossed the line are dropped**: nothing is left to foresee once the rules have fired.
- **Features are shared** between training and serving (`ml/features.py`), so they cannot drift apart.
- **Compared with a naive baseline** ("is pH already above 7.3?").

## Results (synthetic held-out wounds)

See `ml/metrics.json`. At the default threshold the model catches about 69% of upcoming crossings (baseline: 29%) but has many false alarms (precision about 22%, baseline 37%). Operating points the app uses:

| Level | Score | Precision | Recall |
| --- | --- | --- | --- |
| watch | 0.5 and above | about 22% | about 69% |
| rising | 0.85 and above | about 95% | about 41% |

ROC AUC is about 0.85 on the synthetic test wounds.

## Known limits

- Trained only on our own simulator. Real wounds, real sensor drift and real dressings will behave differently.
- Placeholder thresholds (pH line 7.5) are not clinically validated.
- Onset is random in the simulator, so some crossings cannot be foreseen from a flat window.
- No calibration, fairness or drift analysis on real data, because there is none yet.

## Next step with real data

Collect patch readings with clinician-labelled outcomes, retrain with the same scripts, check calibration per site, and only then consider showing the score to patients.
