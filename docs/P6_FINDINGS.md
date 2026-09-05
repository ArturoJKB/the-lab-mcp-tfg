# P6 Findings — Hole & Fix Log

Harvested deterministically by `scripts/harvest_findings.py` from
recorded workspace evidence: `runs`, `.thelab/jobs`, `.thelab/experiments`.
Every ticket cites its evidence; known signatures fixed in P5 are
marked `applied`. Remaining `proposed` tickets are the P6.B.1 backlog.

**Summary:** 19 findings — major: 5, minor: 8, note: 6.

### P6-BLK-001: Foreign hyperparameters passed to estimator constructor
- Severity:   major
- Category:   run
- Symptom:    LinearRegression.__init__() got an unexpected keyword argument 'alpha'
- Evidence:   `runs/run-20260824-220409-14a52bf6`, `runs/run-20260824-220409-9d665199`, `runs/run-20260824-220409-e05009ab`, `runs/run-20260824-220409-fc8fbae0`, `runs/run-20260903-033052-71d7cbaf`, `runs/run-20260903-033052-d9cecada`
- Samples:    LinearRegression.__init__() got an unexpected keyword argument 'alpha'
- Root cause: Shared LLM hyperparameter grids contained params that do not exist on every model in the grid
- Fix:        Per-model filtering via ModelRegistry.valid_param_keys at batch translation
- Status:     applied

### P6-BLK-002: Experiment completed with zero trained models
- Severity:   major
- Category:   experiment
- Symptom:    no candidate models completed
- Evidence:   `.thelab/experiments/exp-20260829-144800-10e853b5.json`, `.thelab/experiments/exp-20260829-200627-163fbe7b.json`, `.thelab/experiments/exp-20260829-200650-d386b9dd.json`, `.thelab/experiments/exp-20260829-200702-209afada.json`, `.thelab/experiments/exp-20260901-223946-dcd4d847.json`, `.thelab/experiments/exp-20260902-162926-8ba8cfb9.json`
- Samples:    no candidate models completed
- Root cause: Status laundering: all-failing batches were reported as completed experiments
- Fix:        Honest status mapping in jobs._run_experiment (P5 audit BUG 1b)
- Status:     applied

### P6-BLK-003: Fixture datasets rejected mid-orchestration
- Severity:   major
- Category:   experiment
- Symptom:    provider 'openrouter' failed during orchestration: only uploaded datasets can be cleaned
- Evidence:   `.thelab/experiments/exp-20260903-033153-bbee3147.json`, `.thelab/experiments/exp-20260903-033250-448d1993.json`, `.thelab/jobs/job-20260903-033153-abbe72d8.json`, `.thelab/jobs/job-20260903-033250-96f7c9ce.json`
- Samples:    provider 'openrouter' failed during orchestration: only uploaded datasets can be cleaned
- Root cause: Orchestrator attempted cleaning on fixtures/* which the cleaning API rejects
- Fix:        Fixtures skip cleaning (P5 audit BUG 2); provider-blame removed via OrchestrationFailed
- Status:     applied

### P6-BLK-004: EDA crashes on array-valued columns
- Severity:   major
- Category:   experiment
- Symptom:    provider 'openrouter'<long>'numpy.ndarray'
- Evidence:   `.thelab/experiments/exp-20260902-164651-eb9dfa4c.json`, `.thelab/jobs/job-20260902-164651-2e022c14.json`
- Samples:    provider 'openrouter' failed during orchestration: eda computation failed: unhashable type: 'numpy.ndarray'
- Root cause: run_eda correlation/missing profiling assumes scalar columns; list/array columns (e.g. from naive JSON ingestion) break it
- Fix:        Guard EDA stage against non-scalar column dtypes with a traceable OrchestrationFailed message
- Status:     proposed

### P6-BLK-005: Re-running an experiment on an already-cleaned dataset id fails
- Severity:   major
- Category:   experiment
- Symptom:    provider 'openrouter'<long>'uploads/shrutimechlearn_churn-modelling_cleaned.csv' is already cleaned (target: uploads/shrutimechlearn_churn-modelling_cleaned)...
- Evidence:   `.thelab/experiments/exp-20260901-173444-b766b410.json`, `.thelab/jobs/job-20260901-173444-d8eb5bc7.json`
- Samples:    provider 'openrouter' failed during orchestration: 'uploads/shrutimechlearn_churn-modelling_cleaned.csv' is already cleaned (target: uploads/shrutimechlearn_...
- Root cause: Re-cleaning guard treats the cleaned id as invalid instead of idempotent
- Fix:        Idempotent re-clean: return the existing cleaned dataset_id with a note
- Status:     proposed

### P6-BLK-006: Tool/provider payload treated as dict when it was a string
- Severity:   minor
- Category:   job
- Symptom:    'str'<long>'get'
- Evidence:   `.thelab/jobs/job-20260831-022921-22899b68.json`
- Samples:    'str' object has no attribute 'get'
- Root cause: A response payload bypassed strict JSON parsing and was used as a dict downstream (recorded in a failed job)
- Fix:        Parse tool responses strictly at the boundary (json.loads + typed contract) so string payloads fail at parse time, not at use time
- Status:     proposed

### P6-BLK-007: Unclassified failure
- Severity:   minor
- Category:   run
- Symptom:    Solver lbfgs supports only 'l2' or None penalties, got l1 penalty.
- Evidence:   `runs/run-20260904-145055-1dc56faa`, `runs/run-20260904-145056-3abc7ff1`, `runs/run-20260904-145056-8adc5a0d`, `runs/run-20260904-145056-9ca388f0`, `runs/run-20260904-145056-d91e3a55`, `runs/run-20260904-145057-c8dce232`
- Samples:    Solver lbfgs supports only 'l2' or None penalties, got l1 penalty.
- Root cause: see evidence (no recorded hypothesis)
- Fix:        triage: reproduce from the cited evidence, then classify
- Status:     proposed

### P6-BLK-008: Unclassified failure
- Severity:   minor
- Category:   run
- Symptom:    The 'learning_rate'<long>'adaptive', 'pa2', 'invscaling', 'optimal', 'pa1', 'constant'}. Got 0.1 instead.
- Evidence:   `runs/run-20260905-170542-93e97a87`, `runs/run-20260905-170543-92e2de81`, `runs/run-20260905-170543-ae40370f`, `runs/run-20260905-170623-8d7351f7`, `runs/run-20260905-170623-ca44d4a5`, `runs/run-20260905-170623-d46f637b`
- Samples:    The 'learning_rate' parameter of SGDClassifier must be a str among {'adaptive', 'pa2', 'invscaling', 'optimal', 'pa1', 'constant'}. Got 0.1 instead.
- Root cause: see evidence (no recorded hypothesis)
- Fix:        triage: reproduce from the cited evidence, then classify
- Status:     proposed

### P6-BLK-009: Unclassified failure
- Severity:   minor
- Category:   run
- Symptom:    The 'learning_rate'<long>'adaptive', 'pa2', 'invscaling', 'optimal', 'pa1', 'constant'}. Got 0.5 instead.
- Evidence:   `runs/run-20260905-170543-137c903a`, `runs/run-20260905-170543-79d8e95f`, `runs/run-20260905-170543-85a35025`, `runs/run-20260905-170623-0c0be5be`, `runs/run-20260905-170623-6a49a016`, `runs/run-20260905-170623-f22c3128`
- Samples:    The 'learning_rate' parameter of SGDClassifier must be a str among {'adaptive', 'pa2', 'invscaling', 'optimal', 'pa1', 'constant'}. Got 0.5 instead.
- Root cause: see evidence (no recorded hypothesis)
- Fix:        triage: reproduce from the cited evidence, then classify
- Status:     proposed

### P6-BLK-010: Unclassified failure
- Severity:   minor
- Category:   run
- Symptom:    The 'learning_rate'<long>'constant', 'optimal', 'pa2', 'pa1', 'invscaling', 'adaptive'}. Got 0.1 instead.
- Evidence:   `runs/run-20260905-151346-255bccbc`, `runs/run-20260905-151349-76080711`, `runs/run-20260905-151352-950cdfe9`
- Samples:    The 'learning_rate' parameter of SGDClassifier must be a str among {'constant', 'optimal', 'pa2', 'pa1', 'invscaling', 'adaptive'}. Got 0.1 instead.
- Root cause: see evidence (no recorded hypothesis)
- Fix:        triage: reproduce from the cited evidence, then classify
- Status:     proposed

### P6-BLK-011: Unclassified failure
- Severity:   minor
- Category:   run
- Symptom:    The 'learning_rate'<long>'constant', 'optimal', 'pa2', 'pa1', 'invscaling', 'adaptive'}. Got 0.5 instead.
- Evidence:   `runs/run-20260905-151348-ae05e2eb`, `runs/run-20260905-151350-c3b3a47d`, `runs/run-20260905-151353-0ce76144`
- Samples:    The 'learning_rate' parameter of SGDClassifier must be a str among {'constant', 'optimal', 'pa2', 'pa1', 'invscaling', 'adaptive'}. Got 0.5 instead.
- Root cause: see evidence (no recorded hypothesis)
- Fix:        triage: reproduce from the cited evidence, then classify
- Status:     proposed

### P6-BLK-012: Provider configuration or connectivity failure
- Severity:   minor
- Category:   job
- Symptom:    [network] network error: [Errno 111] Connection refused
- Evidence:   `.thelab/jobs/job-20260831-233334-525a65b6.json`, `.thelab/jobs/job-20260831-233907-6baa429b.json`, `.thelab/jobs/job-20260831-233934-6758b63b.json`, `.thelab/jobs/job-20260831-234110-ea6abff0.json`, `.thelab/jobs/job-20260831-234117-d7bac1c0.json`
- Samples:    [network] network error: [Errno 111] Connection refused
- Root cause: Dead/misconfigured LLM provider
- Fix:        Fail-fast with named provider and hint (implemented); run the provider setup check before starting live sessions
- Status:     applied

### P6-BLK-013: Invalid target column accepted at experiment entry
- Severity:   minor
- Category:   run
- Symptom:    target column 'quality' not found
- Evidence:   `runs/run-20260824-220446-ecac696e`, `runs/run-20260824-220528-05385c22`, `runs/run-20260824-220528-0cf2d6b4`, `runs/run-20260824-220528-582dab3a`, `runs/run-20260824-220722-efb60754`, `runs/run-20260824-220757-a4ba4543`, `runs/run-20260903-021124-c5381f7c`, `runs/run-20260903-021136-b000fb69` (+6 more)
- Samples:    target column 'quality' not found
- Root cause: POST /experiment/run validates the dataset but not the target column; the failure surfaces mid-orchestration wrapped as a provider failure
- Fix:        Validate target against dataset columns at experiment entry; report deterministic failures via OrchestrationFailed
- Status:     proposed

### P6-BLK-014: Constant feature columns rejected by validation
- Severity:   note
- Category:   run
- Symptom:    constant feature columns found: ['OrderDate_hour', 'SignupDate_hour']
- Evidence:   `runs/run-20260830-222333-729d524c`, `runs/run-20260830-222333-c24187d0`, `runs/run-20260830-222334-8a4c2153`, `runs/run-20260831-001814-cedd5a3b`, `runs/run-20260831-001814-e2a43afb`, `runs/run-20260903-021131-63164b08`, `runs/run-20260903-183300-0575a23a`, `runs/run-20260904-141812-000bf7e3` (+14 more)
- Samples:    constant feature columns found: ['OrderDate_hour', 'SignupDate_hour']
- Root cause: Validation guardrail: constant columns carry no signal
- Fix:        By-design first-class rejection (P0 AC-02); optionally surfaced by the cleaning policy as a drop report entry
- Status:     applied

### P6-BLK-015: Unsafe or unknown dataset id rejected
- Severity:   note
- Category:   run
- Symptom:    dataset not found: uploads/sp500_analyst_cleaned.csv
- Evidence:   `runs/run-20260829-144653-a5b569af`, `runs/run-20260904-032727-441d321a`, `runs/run-20260904-032727-8a6e1290`, `runs/run-20260904-032728-34198f55`, `runs/run-20260904-032728-466cf960`, `runs/run-20260904-032728-52c9949c`, `runs/run-20260904-032728-5ad410ac`, `runs/run-20260904-032728-73782d5c` (+3 more)
- Samples:    dataset not found: uploads/sp500_analyst_cleaned.csv
- Root cause: Path-safety validation rejected the id
- Fix:        By-design first-class rejection (path safety)
- Status:     applied

### P6-BLK-016: Wrong-task models in the training grid
- Severity:   note
- Category:   run
- Symptom:    model 'logistic_regression' is a classification model, but the dataset resolves to regression
- Evidence:   `runs/run-20260824-220627-41391468`, `runs/run-20260824-221138-d1fe42dc`, `runs/run-20260825-193854-d00ae76a`, `runs/run-20260825-193902-80d4b5a1`, `runs/run-20260829-185550-58db686e`, `runs/run-20260829-185550-a82c5088`, `runs/run-20260829-185551-32e32c23`, `runs/run-20260829-185551-44eebc84` (+199 more)
- Samples:    model 'logistic_regression' is a classification model, but the dataset resolves to regression
- Root cause: Model selection did not filter the registry by inferred task type
- Fix:        Task-aware selection + deterministic post-filter (thelab/ide/agentic_round.py)
- Status:     applied

### P6-BLK-017: Scale guard rejected an impractical model/dataset pair
- Severity:   note
- Category:   run
- Symptom:    model 'svc' is limited to 50000 training rows (dataset has 164231 rows); choose a scalable model or subsample the data
- Evidence:   `runs/run-20260903-033054-a8895ee5`, `runs/run-20260903-183519-86af43ae`, `runs/run-20260905-144010-b81eea21`, `runs/run-20260905-145226-872f09ab`, `runs/run-20260905-152052-5b5e02b3`, `runs/run-20260905-170950-00a6ed43`, `runs/run-20260905-180357-ab838a37`, `runs/run-20260905-181409-090bbbee` (+6 more)
- Samples:    model 'svc' is limited to 50000 training rows (dataset has 164231 rows); choose a scalable model or subsample the data
- Root cause: Registry scale guards reject super-linear models on large datasets
- Fix:        By-design first-class rejection (P2.6.5 scale guards)
- Status:     applied

### P6-BLK-018: Non-numeric feature columns rejected before training
- Severity:   note
- Category:   run
- Symptom:    not all feature columns are numeric: ['a']
- Evidence:   `runs/run-20260820-225324-2eccf085`, `runs/run-20260830-222213-38222325`, `runs/run-20260830-222213-801730f8`, `runs/run-20260830-222213-a77b62e8`, `runs/run-20260901-190647-1a01475a`, `runs/run-20260901-190647-5606eedf`, `runs/run-20260901-190647-a4efdb63`, `runs/run-20260901-222425-7a002cac` (+27 more)
- Samples:    not all feature columns are numeric: ['a']
- Root cause: Cleaning policy (cardinality-aware encoding) did not run on this dataset; the factory requires numeric features
- Fix:        By-design first-class rejection; run the cleaning policy first
- Status:     applied

### P6-BLK-019: Target column with missing values rejected
- Severity:   note
- Category:   run
- Symptom:    target column contains 5602 missing values
- Evidence:   `runs/run-20260825-193427-92a7db9e`, `runs/run-20260825-193500-9fd6bd2f`, `runs/run-20260825-193508-c24b0cc6`, `runs/run-20260825-193539-4c44e399`, `runs/run-20260825-193608-56e563b4`, `runs/run-20260825-193823-4807f931`, `runs/run-20260825-193915-8fedb047`, `runs/run-20260825-195503-20b65bee` (+8 more)
- Samples:    target column contains 5602 missing values
- Root cause: Validation guardrail: drop_missing_target policy or explicit rejection
- Fix:        By-design first-class rejection (PRD AC-02)
- Status:     applied
