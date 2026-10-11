# Real aggregate revenue model comparison

**Retain the existing default.** Its revenue forecast error is **59.10% lower** than the frozen teammate inflow model on existing common-support real aggregate cases, and **58.13% lower** on the additional reserved temporal panel. The new LightGBM trained on actual revenue produces a small improvement, but neither it nor any preregistered fixed mixture reaches the five-percent development improvement required for replacement consideration. The additional reserved temporal panel also gives no clear material improvement. Both serving scorers remain unchanged.

Recorded on 11 October 2026, followed by a same-recipe reproducibility run. Every saved case-level forecast was identical across both runs; only timings, timestamps and byte hashes of development outputs containing timings changed. Repetition does not create independent evidence; first outputs are preserved locally. The comparison evaluates the incumbent's frozen `adaptive_revenue_10` revenue component, the teammate's frozen `m-f7d2fc389743` LightGBM inflow component, a four-configuration real-trained residual experiment, and a seasonal-naive reference. It excludes net cash flow, expenses, capacity scores, officer decisions and repayment schedules.

The protocol and target reservation were fixed before comparative errors: [preregistered protocol](../../docs/model-benchmark-protocol.md), [reserved temporal target manifest](../data/real-comparison-unused-temporal.json). [Machine-readable report](real-model-benchmark.json) and [case-level predictions and observed targets](real-model-benchmark-predictions.json) preserve measured evidence. Original frozen reports were not replaced.

## What was measured

The primary metric is each case's monthly mean absolute revenue error divided by the mean of its latest up to 12 historical revenue months; case errors are averaged within provider, then providers receive equal weight. Smaller is better. A value such as 0.105 is a normalized error, not a 10.5% borrower default probability or a calibrated accuracy percentage. Percentage improvement below means relative reduction in this error.

The incumbent uses patterns fitted to licensed real revenue aggregates. The teammate's frozen artifacts identify synthetic business training; public aggregates lack its channel, expense, debt, activity, payer and industry inputs. Those inputs remain `NaN`, rather than invented zero values. Only the existing inflow equations execute. Each supplied history is normalized to recent level 100 and output is rescaled to its original units; this is an explicitly declared aggregate revenue adaptation, not a test of the full native bank-transaction scorer. The incumbent's normalized features and baselines are scale invariant.

Raw Uzbekistan million UZS, ABS million AUD, Statistics Canada thousand CAD, Eurostat index points (2021=100), and ONS index points (2024=100) are never pooled as money or converted to borrower amount indices. All comparisons below use dimensionless errors.

## Existing terminal panels: compare identical supported cases

The requested existing panels contain 264 cases and 2,888 observed target months. The vendor requires six historical months and refuses 67 Uzbekistan 2025 cases with only three months after the service methodology boundary: **25.38% of requested existing cases**. The common-support comparison therefore contains **197 cases / 2,084 observed months**, all scored by every model. This restriction must accompany the headline comparison.

Across both final panels, 712 requested windows contain 7,428 observed target months. The directly comparable supported total is **645 windows / 6,624 observed months** (197 existing plus 448 reserved temporal windows). These are dependent aggregate windows, not 645 independent businesses.

| Provider               | Cases | Observed months | Incumbent | Teammate | Real LightGBM | Naive    |
| ---------------------- | ----- | --------------- | --------- | -------- | ------------- | -------- |
| Uzbekistan SIAT        | 73    | 596             | 0.259615  | 0.356022 | 0.254209      | 0.307816 |
| ABS Australia          | 24    | 288             | 0.057789  | 0.232260 | 0.058017      | 0.068629 |
| Statistics Canada      | 32    | 384             | 0.066731  | 0.220370 | 0.066232      | 0.073226 |
| Eurostat               | 49    | 588             | 0.066860  | 0.251789 | 0.067773      | 0.083420 |
| ONS Great Britain      | 19    | 228             | 0.074065  | 0.223225 | 0.076135      | 0.090323 |
| Equal-provider primary | 197   | 2,084           | 0.105012  | 0.256733 | 0.104473      | 0.124683 |

On common support, teammate error is **144.48% greater** than incumbent error (0.256733 versus 0.105012). The paired whole-geography bootstrap describes its error improvement as **−144.48%**, interval **[−191.53%, −121.30%]**. This measures these aggregate forecasts; it does not establish the same ranking for complete transaction-level borrower inputs.

The real-trained LightGBM's common-support improvement is **0.51%**, independently recomputed interval **[−2.14%, 2.02%]**. On all 264 cases its improvement is 0.15%, interval [−1.28%, 0.82%]. Neither supports a material replacement.

All requested cases must also remain visible. The incumbent, real-trained model and naive reference support all 264. Vendor standalone errors cannot fairly be compared to their all-case total because it omits the difficult three-month histories.

| Provider               | Requested | Vendor supported | Vendor refused | Incumbent all | Real LGB all | Naive all |
| ---------------------- | --------- | ---------------- | -------------- | ------------- | ------------ | --------- |
| Uzbekistan SIAT        | 140       | 73               | 67             | 0.825923      | 0.821611     | 0.856640  |
| ABS Australia          | 24        | 24               | 0              | 0.057789      | 0.058017     | 0.068629  |
| Statistics Canada      | 32        | 32               | 0              | 0.066731      | 0.066232     | 0.073226  |
| Eurostat               | 49        | 49               | 0              | 0.066860      | 0.067773     | 0.083420  |
| ONS Great Britain      | 19        | 19               | 0              | 0.074065      | 0.076135     | 0.090323  |
| Equal-provider primary | 264       | 197              | 67             | 0.218274      | 0.217954     | 0.234448  |

The high all-case Uzbekistan error is material: post-break three-month histories include difficult small/near-zero observations. On Uzbekistan Jan-Dec 2025 the incumbent normalized MAE is **1.386960** across 70 cases, while the vendor supports only 3. On Jan-Aug 2026 all 70 cases are supported: incumbent **0.264886**, teammate **0.359097**, real LightGBM **0.259600**, naive **0.311719**. Four unpublished late-2026 forecast months are excluded, not invented. The individual period results are preserved in the JSON report.

## Newly reserved retrospective temporal check

A separate fixed rule reserves terminal observations from original training geographies, plus Uzbekistan 2026 validation geographies: **448 cases / 4,540 months**, all supported by every model. Exact target coordinates have zero overlap with every original real train, validation, final/audit and public retail baseline target coordinate, including the `retail:code` alias. They also have zero overlap with history coordinates constructed by those original cases. The reservation preserves source hashes, target-value hashes, identities, exclusions and methodology flags.

These targets were newly reserved before errors, but use already known economic periods, trained geographies, and revised published vintages. Prior ad hoc access outside committed builders cannot be disproved. This is an exploratory retrospective temporal check, not fresh independent provider evidence or borrower validation. ONS is absent because it has no training/development geography.

| Provider               | Cases | Observed months | Incumbent | Teammate | Real LightGBM | Naive    |
| ---------------------- | ----- | --------------- | --------- | -------- | ------------- | -------- |
| Uzbekistan SIAT        | 209   | 1672            | 0.240517  | 0.315935 | 0.244308      | 0.301425 |
| ABS Australia          | 52    | 624             | 0.056889  | 0.230925 | 0.055912      | 0.068798 |
| Statistics Canada      | 95    | 1140            | 0.072301  | 0.218813 | 0.067765      | 0.076465 |
| Eurostat               | 92    | 1104            | 0.050249  | 0.237329 | 0.048702      | 0.058701 |
| Equal-provider primary | 448   | 4,540           | 0.104989  | 0.250751 | 0.104172      | 0.126347 |

Teammate error is **138.84% greater** than incumbent error; paired descriptive improvement interval **[−166.42%, −115.61%]**. Real-trained LightGBM error is **0.104172** versus **0.104989**, a **0.78%** improvement with independently recomputed interval **[−1.31%, 3.21%]**. It improves ABS, Canada and Eurostat slightly but worsens Uzbekistan. The required five-percent gain and positive lower interval bound both fail.

## Development selection and the bounded improvement experiment

Only original development data selected hyperparameters and mixture weights: 135 validation cases, 1,620 observed target months, from Uzbekistan (32), ABS (30), Canada (29) and Eurostat (44). ONS never enters fitting or selection. The vendor supports 106 and refuses 29 three-month Uzbekistan histories (**21.48%**). In preregistered mixtures, only these expected short-history refusals fall back to incumbent for the vendor contribution; unexpected failures or invalid output fail evaluation.

The real-trained experiment uses 86,976 real target-month examples from 7,248 rolling cases. Windows overlap and are not independent samples. Providers have equal total training loss weight. It uses the incumbent's 21 revenue features, learns the log residual to damped seasonal revenue, and reconstructs with a fixed residual clip of ±3. The four LightGBM configurations share L1 objective, learning rate 0.04, minimum leaf size 60, L2 penalty 1 and seed 20261011. No final targets fit these models.

| Leaves | Rounds | Development primary nMAE | Improvement vs incumbent |
| ------ | ------ | ------------------------ | ------------------------ |
| 15     | 200    | 0.086765                 | -1.19%                   |
| 15     | 400    | 0.085306                 | 0.51%                    |
| 31     | 200    | 0.083960                 | 2.08%                    |
| 31     | 400    | 0.083698                 | 2.39%                    |

The selected real-trained configuration is **31 leaves / 400 rounds**, with development error 0.083698 versus incumbent 0.085743: **2.39%** improvement, below the required 5%. Configurations are selected among those meeting the two-percent per-provider regression gate; no final-label routing or hyperparameter expansion occurs.

All 15 quarter-step convex mixtures were measured on the same development cases. Weights are `(incumbent, frozen teammate, selected real LightGBM)`. The table includes the predeclared short-history vendor fallback; it does not imply standalone vendor support for those histories.

| Weights incumbent / teammate / real LGB | Development nMAE | Improvement | Provider ≤2% regression gate |
| --------------------------------------- | ---------------- | ----------- | ---------------------------- |
| 0.00 / 0.00 / 1.00                      | 0.083698         | 2.39%       | pass                         |
| 0.00 / 0.25 / 0.75                      | 0.096767         | -12.86%     | fail                         |
| 0.00 / 0.50 / 0.50                      | 0.127078         | -48.21%     | fail                         |
| 0.00 / 0.75 / 0.25                      | 0.163351         | -90.51%     | fail                         |
| 0.00 / 1.00 / 0.00                      | 0.201167         | -134.62%    | fail                         |
| 0.25 / 0.00 / 0.75                      | 0.083391         | 2.74%       | pass                         |
| 0.25 / 0.25 / 0.50                      | 0.096782         | -12.87%     | fail                         |
| 0.25 / 0.50 / 0.25                      | 0.127311         | -48.48%     | fail                         |
| 0.25 / 0.75 / 0.00                      | 0.163573         | -90.77%     | fail                         |
| 0.50 / 0.00 / 0.50                      | 0.083742         | 2.33%       | pass                         |
| 0.50 / 0.25 / 0.25                      | 0.097173         | -13.33%     | fail                         |
| 0.50 / 0.50 / 0.00                      | 0.127740         | -48.98%     | fail                         |
| 0.75 / 0.00 / 0.25                      | 0.084623         | 1.31%       | pass                         |
| 0.75 / 0.25 / 0.00                      | 0.097825         | -14.09%     | fail                         |
| 1.00 / 0.00 / 0.00                      | 0.085743         | 0.00%       | pass                         |

The best measured development error belongs to 25% incumbent / 75% real LightGBM: **0.083391**, improvement **2.74%**. Every mixture containing vendor weight fails the provider guard. No mixture reaches the preregistered five-percent gain, so selection falls back to **100% incumbent** before terminal errors are inspected. Its final improvement and bootstrap interval are exactly zero by construction. Terminal evidence cannot override failed development eligibility.

## Secondary metrics, short histories and scale sensitivity

| Panel                   | Model                 | sMAPE % | Normalized WAPE % | Seasonal MASE |
| ----------------------- | --------------------- | ------- | ----------------- | ------------- |
| Existing common support | Frozen incumbent      | 11.92   | 11.28             | 0.894         |
| Existing common support | Frozen teammate       | 27.18   | 25.17             | 2.611         |
| Existing common support | Real-trained LightGBM | 11.74   | 11.17             | 0.884         |
| Reserved temporal       | Frozen incumbent      | 12.03   | 11.81             | 0.742         |
| Reserved temporal       | Frozen teammate       | 25.73   | 24.29             | 2.420         |
| Reserved temporal       | Real-trained LightGBM | 11.88   | 11.79             | 0.739         |

MAE, WAPE and sMAPE retain observed zeros and near-zero months. Exactly zero actual/prediction pairs have zero sMAPE. MASE uses historical twelve-month differences only, with short or zero-denominator cases excluded and counts recorded in JSON. Secondary metrics do not select models.

Short-history stresses reuse existing terminal actuals and are not extra independent observations. Each row has its own eligible case set; comparing rows does not isolate a history-length causal effect.

| History months | Requested cases | Vendor supported | Incumbent | Teammate    | Real LightGBM | Naive    |
| -------------- | --------------- | ---------------- | --------- | ----------- | ------------- | -------- |
| 3              | 264             | 0                | 0.402969  | unsupported | 0.401744      | 0.364045 |
| 6              | 197             | 197              | 0.207252  | 0.275432    | 0.208450      | 0.157463 |
| 12             | 197             | 197              | 0.175314  | 0.268542    | 0.176879      | 0.124683 |
| 24             | 131             | 131              | 0.096517  | 0.239598    | 0.091270      | 0.110815 |

Three-month vendor stress is entirely unsupported. In the three-, six- and twelve-month slices naive error is lower than incumbent error, which must remain visible. Across requested terminal/stress rows the vendor has 331 expected `insufficient_history` refusals; 264 are the three-month stress and 67 are the existing Uzbekistan full panel. The reserved temporal panel has no refusals.

Optional vendor predictions without mean100 normalization are sensitivity diagnostics only. On existing common support, primary/native-unit error is **0.256733 / 0.256580**; on reserved temporal data **0.250751 / 0.251772**. Small aggregate differences do not reverse the observed comparison. They do not prove exact scale invariance or justify choosing a transform after observing errors.

## Synthetic intervals do not transfer as calibrated certainty

The teammate's existing P10-P90 inflow interval nominally covers 80% under its synthetic calibration. Actual coverage below is measured on supported existing real aggregate months only; this is a diagnostic, not a calibrated uncertainty claim.

| Provider          | Supported observed months | Actual P10-P90 coverage | Mean width / historical scale |
| ----------------- | ------------------------- | ----------------------- | ----------------------------- |
| Uzbekistan SIAT   | 596                       | 89.60%                  | 1.840                         |
| ABS Australia     | 288                       | 19.44%                  | 0.251                         |
| Statistics Canada | 384                       | 27.86%                  | 0.252                         |
| Eurostat          | 588                       | 17.52%                  | 0.244                         |
| ONS Great Britain | 228                       | 23.25%                  | 0.256                         |

Foreign provider coverage of roughly 18–28% is far below nominal 80%; Uzbekistan has higher coverage with much wider normalized intervals. An interval existing in the native API does not establish real-data calibration or repayment assurance.

## Why the default stays

The declared development threshold of at least 5% improvement was not met. The reserved temporal check also does not show 5% gain with a positive lower descriptive interval bound. The selected pre-terminal fallback is incumbent itself, so its old-panel and reserved-panel point improvements are zero. Per-provider regression guards passing for an identical model cannot establish a useful challenger. Existing and reserved temporal results therefore support retaining the frozen default and preserving the alternatives for research.

A paired provider-stratified bootstrap uses 2,000 draws with seed 20261011, resampling whole geography groups and retaining all their dependent sectors/windows. Existing supported panels have only 3 Uzbekistan, 2 ABS, 2 Canadian, 5 Eurostat and 1 ONS group. The one ONS group remains fixed, so UK cross-country uncertainty is not estimated. The reserved panel has 11, 4, 7 and 16 groups respectively. Providers still share economic shocks and survey revisions. Intervals are descriptive and do not repair consumed evidence, sequential experimentation, or aggregate-to-borrower transfer.

The existing terminal panels were previously consumed by incumbent development, while the additional targets were newly reserved retrospective labels from known geographies and eras before this measurement. After their results have been inspected, the additional temporal panel is also **consumed for future model tuning**. None supplies real expense, capacity, repayment or default labels. These results do not establish bank accuracy, full native transaction-scorer accuracy, future affordability, or default probability. Any later revenue change still needs downstream contract, engineering and product validation, a separately reserved future evaluation, and user authorization to change serving.

## Independent verification and reproducibility

A separate recomputation from the saved case-level predictions verified every reported provider-balanced primary metric across all panels and support sets; the maximum absolute difference was **5.55e-17**. Independent paired whole-group resampling reproduced both vendor comparison intervals, and produced the additional real-trained diagnostic intervals cited above. No retraining or additional scoring was needed for this verification.

The 9 reservation tests check original-builder and public-baseline target disjointness, unique targets, history boundaries, methodology/missing/negative exclusions, frozen-manifest tampering and fail-closed missing reservation. The frozen target-coordinate hash is `7c8ca75b7df6562ceb754945c5b991e223e437f66a33cbba43e24d612b23bfaa`; full artifact, source, protocol, data and prediction provenance remains in the linked JSON files.

The recorded reproduction's local successful prediction timing across these mixed history slices was median/P95 **1.39/7.82 ms** for incumbent and **1.71/2.19 ms** for teammate, with 1,501 incumbent and 1,170 successful vendor calls. These are local prediction timings, not comparable production API/network/concurrency measurements. Timing is diagnostic and did not select the default; later reproduction timings may differ.

Run from the repository root with Node 24, pnpm 12.8.1 and `uv` available:

```bash
bash scripts/benchmark_models.sh /absolute/path/to/the/frozen/model.joblib
```

The default artifact must match SHA-256 `31693530f17dbd481752d0996b0d4131c65ee0af859346a8f83aea7f17283b96` to reproduce this evidence. The script installs Python dependencies from each service's frozen lock, preserves the first default artifact, and reuses already frozen experimental artifacts only after checking the training-data hash. It refuses to overwrite differing frozen artifacts. The teammate artifact is already tracked; its model SHA-256 is `51091e827f0b9d768878bd8e414e2c10dd18c7e3dee884acb3680b722bfa8d1a`.

Reproduction uses `benchmarks.compare_real_revenue` preparation/selection/report commands plus the teammate benchmark runners. Development selection is written before terminal preparation. Frozen artifacts, runtime training arrays, and generated local evidence are ignored; the committed protocol, reservation manifest, tests and measured reports are reviewable. Repeated runs reproduce consumed labels and timings may change.
