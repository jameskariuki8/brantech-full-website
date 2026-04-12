# Google Embedding Migration Plan

This guide outlines the steps to replace the current local Hugging Face embeddings with Google Generative AI embeddings, adopting the robust rate-limiting and error-handling patterns from `WozapAuto`.

## 1. Analysis of WozapAuto's Approach

`WozapAuto` uses a dual-layer strategy to handle Google API limits reliably:

### A. Reactive Error Handling (Retries)
- **Custom Exceptions**: Defines `RateLimitError` vs `QuotaExhaustedError`.
- **Intelligent Classification**: Functions like `is_quota_exhausted_error()` distinguish between temporary 429s (rate limits) and hard blocks (quota reached).
- **Exponential Backoff**: A `@retry_with_exponential_backoff` decorator wraps API calls. It retries temporary errors with increasing delays but fails fast or waits longer for quota issues.

### B. Proactive Rate Limiting
- **`ProactiveRateLimiter` Class**:
  - Tracks Requests Per Minute (RPM) and Tokens Per Minute (TPM) locally using a sliding window (using `deque`).
  - Estimates token usage before making a call (~4 chars/token).
  - Sleeps proactively (`wait_if_needed`) *before* calling the API if limits are near, preventing 429s from happening in the first place.
  - Thread-safe (`threading.Lock`) for concurrent usage.

## 2. Implementation Steps for BrandTechSolution

### Step 1: Create Rate Limiting Utilities

Create a new file `brandtechsolution/ai_workflows/rate_limiters.py` (or `utils.py`) and port the following components from `WozapAuto/knowledgebase/service.py`:
- `RateLimitError` / `QuotaExhaustedError` exceptions.
- `is_rate_limit_error` / `is_quota_exhausted_error` helpers.
- `retry_with_exponential_backoff` decorator.
- `ProactiveRateLimiter` class.

### Step 2: Configure Settings

Ensure `brandtechsolution/config.py` (or `.env`) includes:
- `GOOGLE_API_KEY`
- Rate limit constants (e.g., `GEMINI_RPM=15`, `GEMINI_TPM=1000000` for free tier, or higher for paid).

### Step 3: Update Embedding Logic

Modify `brandtechsolution/ai_workflows/tools.py` (or the location where `HuggingFaceEmbeddings` is currently initialized):

1. **Initialize Provider**:
   ```python
   from langchain_google_genai import GoogleGenerativeAIEmbeddings
   from .rate_limiters import retry_with_exponential_backoff, ProactiveRateLimiter

   # Initialize limiter (singleton or per-process)
   limiter = ProactiveRateLimiter(rpm_limit=15, tpm_limit=1000000)

   embeddings_model = GoogleGenerativeAIEmbeddings(
       model="models/embedding-001",
       google_api_key=config.google_api_key
   )
   ```

2. **Wrap Embedding Calls**:
   Instead of calling `embeddings_model.embed_documents` directly, wrap it to use the limiter and retries:

   ```python
   @retry_with_exponential_backoff(max_retries=5)
   def robust_embed_documents(texts):
       # 1. Proactive wait
       total_chars = sum(len(t) for t in texts)
       est_tokens = total_chars // 4
       limiter.wait_if_needed(est_tokens)

       # 2. Call API
       return embeddings_model.embed_documents(texts)
   ```

### Step 4: Refactor `init_vector_stores` Command

Update `management/commands/init_vector_stores.py` to use the new `robust_embed_documents` function.
- **Batching**: Ensure you process records in small batches (e.g., 10-20 items) rather than all at once, so the rate limiter has a chance to intervene between batches.

### Step 5: Clean Up Dependencies

Once verified:
1. Remove `langchain-huggingface` and `sentence-transformers` from `requirements.txt`.
2. Remove the local embedding weights (cached in `~/.cache/huggingface` or local `venv` if applicable) to save space.

## 3. Benefits

- **Reduced Resource Usage**: No need to download/load large local models (Saving ~500MB+ RAM/Disk).
- **Stability**: Handles API flakiness and free-tier limits automatically.
- **Scalability**: Easier to scale by just upgrading the API quota rather than hardware.
