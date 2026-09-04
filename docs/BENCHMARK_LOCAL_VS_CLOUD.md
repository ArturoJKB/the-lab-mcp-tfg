# Benchmark — Local vs Cloud LLM Providers

> Side-by-side comparison of The Lab's multi-agent pipeline driven by a local Ollama model vs. the cloud OpenRouter API (GLM 5.3 Flash). Same dataset, same deterministic pipeline; only the LLM brain differs.

---

## Setup

| | Local (Ollama) | Cloud (OpenRouter) |
|---|---|---|
| Model | `llama3.2:3b` (3B params, quantized) | `z-ai/glm-5.3-flash` |
| Latency per call | ~2–4 s | ~2–8 s |
| Cost | Free | ~$0.01–0.05 per experiment |
| Privacy | 100% local | Data sent to openrouter.ai |
| Network | Not required (offline capable) | Required |

Both experiments ran on the **Titanic dataset** (891 rows, cleaned to 14 features, binary target `Survived`) with the full orchestration pipeline: EDAAnalyst → FeatureEngineer → ModelSelector → batch training.

---

## Three-way execution path comparison

The **strongest proof** of the design: the same dataset run through three different execution paths produces **bit-for-bit identical results**.

| Execution path | LLM involved | Test accuracy | Test macro F1 | Match |
|---|---|---|---|---|
| **Deterministic only** (no LLM, no agents — raw `run_model` call) | None | **0.8045** | **0.7893** | baseline |
| **Ollama experiment** (llama3.2:3b interpretations + same pipeline) | llama3.2:3b | **0.8045** | **0.7893** | ✅ exact |
| **OpenRouter experiment** (GLM 5.3 Flash interpretations + same pipeline) | z-ai/glm-5.3-flash | **0.8045** | **0.7893** | ✅ exact |

All three paths: same dataset (891 rows, 14 features), same target (`Survived`), same seed (42), same model (`logistic_regression`), same split — and therefore the same trained model.

This is the thesis's central design claim, empirically proven:

> *The LLM decides what to run; the deterministic pipeline executes it. Changing the LLM changes the explanation, never the training outcome.*

The deterministic-only path (no LLM at all) is always available as a **ground-truth baseline** — useful for validating that the agentic layer adds interpretation without introducing nondeterminism.

---

## Agent quality comparison

The interesting difference is in the **LLM interpretation quality** — what the sub-agents *say* about the data.

### Interpretation coverage

| Sub-agent | Ollama (llama3.2:3b) | OpenRouter (GLM 5.3 Flash) |
|---|---|---|
| EDAAnalyst | ✅ Produced (2 of 3 fields populated) | ✅ Produced (clean, structured) |
| FeatureEngineer | ❌ Failed (retry exhausted) | ✅ Produced |
| ModelSelector | ✅ Produced | ✅ Produced |

**Token usage** (from provider responses):

| Sub-agent | Ollama | OpenRouter |
|---|---|---|
| EDAAnalyst | (not reported by Ollama API for this call) | 2,273 prompt + 289 completion |
| ModelSelector | 341 prompt + 89 completion | 349 prompt + 235 completion |
| **Total tracked** | **430 tokens** | **867 tokens** |

### Interpretation quality samples

**EDAAnalyst** — Ollama (llama3.2:3b):

> "Summary of Key Findings and Modeling Risks from EDA Report: Key Findings:"

*(truncated — the 3B model produced a valid JSON structure but the content was shallow)*

**EDAAnalyst** — OpenRouter (GLM 5.3 Flash):

> "1. Class balance: The dataset is imbalanced with a minority class (Survived=1) rate of 38.38% compared to the majority class (Survived=0) rate of 61.62%. Modeling risks include potential bias towards the majority class..."

*(specific, quantified, actionable)*

**ModelSelector** — Ollama (llama3.2:3b):

> "Based on the provided data, I recommend selecting the logistic_regression model as the best configuration for the task..."

**ModelSelector** — OpenRouter (GLM 5.3 Flash):

> "Based on the provided data, I recommend selecting the logistic_regression model as the best configuration for the task. Here's why: 1. **Consistent Performance**: The logistic_regr..."

*(both correct; OpenRouter provides more detailed reasoning)*

---

## Multi-dataset benchmark (P3.7 + earlier)

| Dataset | Rows | Task | Best model | Metric | Provider |
|---|---|---|---|---|---|
| Iris (fixture) | 150 | classification | logistic_regression | Acc 1.0000 | mock (deterministic) |
| Titanic (Kaggle) | 891 | classification | logistic_regression | Acc 0.8045, F1 0.7893 | Ollama + OpenRouter (same result) |
| Churn modelling (Kaggle) | 10,000 | classification | random_forest | Acc 0.8615, F1 0.7420 | deterministic |
| California housing (Kaggle) | 20,640 | regression | random_forest_regressor | R² 0.8172, RMSE 48,942 | deterministic |
| IBM HR attrition (Kaggle) | 1,470 | classification | logistic_regression | Acc 0.8605, F1 0.6794 | deterministic |
| S&P 500 analyst ratings (local) | 164,231 | classification | random_forest | Acc 0.7492, F1 0.7478 | deterministic |
| E-commerce sales (Kaggle) | 49,222 | regression | ridge | R² 1.0000 (computed col) | deterministic |

---

## Honest findings

1. **Cloud models produce better interpretations** — quantified, specific, well-structured. The 3B local model struggles with longer prompts (FeatureEngineer interpretation failed even with retry).
2. **Both providers make the same deterministic decisions** — model selection, cleaning policy, and training results are identical because the pipeline is deterministic. The LLM adds *reasoning and explanation*, not different training outcomes.
3. **Local Ollama is viable for a demo** — the pipeline works end-to-end, the experiment completes, and the interpretations are useful (if less polished). Zero cost, zero data leakage.
4. **Cloud OpenRouter is viable for production** — better quality, faster per-token, but costs money and sends data externally.
5. **The fallback path matters** — when a cloud provider is unavailable or misconfigured, the deterministic fallback still completes the full pipeline (proven across all P3.7 datasets).
6. **Sandbox limitations are honest** — the chat agent's `run_python` tool has no network access and can't download datasets. Kaggle ingestion requires the dedicated API endpoint. This is by design (security), not a bug.

---

## Reproduction

```bash
# 1. Install from lock
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install -e .

# 2. Run the defense demo (deterministic, no LLM required)
./scripts/demo_defense.sh

# 3. Run with a local LLM (Ollama running)
./scripts/demo_defense.sh --live

# 4. Or via the API with a specific provider
curl -X POST localhost:8000/experiment/run \
  -H 'Content-Type: application/json' \
  -d '{"goal": "Predict survival", "dataset_id": "uploads/yasserh_titanic-dataset_cleaned_Survived.csv",
       "target": "Survived", "provider": "openrouter"}'
```
