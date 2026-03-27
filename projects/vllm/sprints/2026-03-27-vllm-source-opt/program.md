# autoforge-vllm — Source Optimization Sprint

Autonomous vLLM optimization: improve Python-level serving throughput for Qwen3-0.6B by optimizing the hot path in vLLM's serving stack.

## Setup

To set up a new experiment run, work with the user to:

1. **Read the campaign config**: the sprint's `campaign.toml` defines the metric, scope, goal, and constraints.
2. **Check history**: `uv run autoforge context` shows current state, best result, recent attempts, and past failures.
3. **Verify the vLLM submodule**: `ls projects/vllm/repo/vllm/` should contain the vLLM Python source tree.
4. **Ensure the submodule optimization branch exists**: `git -C projects/vllm/repo checkout -b autoforge/2026-03-27-vllm-source-opt 2>/dev/null || git -C projects/vllm/repo checkout autoforge/2026-03-27-vllm-source-opt`. All vLLM changes accumulate on this branch inside the submodule.
5. **Establish baseline** (if no history): `uv run autoforge baseline` submits unmodified vLLM for a source build and waits for the result.
6. **Confirm and go**: Confirm setup looks good, then begin experimentation.

All artifacts (requests, results, failures, docs) are stored under `projects/vllm/sprints/2026-03-27-vllm-source-opt/`.

## Architecture

This is a two-machine system:

- **You** (the agent) edit vLLM Python source on this workstation and push changes via git.
- **A remote runner** polls git, builds a container from source (`VLLM_USE_PRECOMPILED=1`), runs the serving benchmark, and pushes results back.

You cannot run the benchmark locally — the runner machine has the GPU. Communication is entirely via git: you push request JSON files, the runner pushes results back. Each experiment takes ~5-8 minutes (push + container build + benchmark + push back).

## What you CAN do

- Modify Python files in the vLLM submodule under the scoped paths from `campaign.toml` `[project] scope`:
  - `vllm/v1/core/` — V1 scheduler, KV cache manager, request scheduling
  - `vllm/v1/engine/` — V1 engine core, async orchestration, IPC
  - `vllm/v1/worker/` — V1 GPU model runner, input preparation
  - `vllm/core/` — legacy scheduler, block manager
  - `vllm/engine/` — legacy engine, LLM engine
  - `vllm/worker/` — worker processes, model runner
  - `vllm/model_executor/layers/sampler.py` — sampling logic, logprob computation
  - `vllm/transformers_utils/` — tokenizer, detokenizer, config utilities
  - `vllm/sequence.py` — sequence group, sequence data structures
  - `vllm/outputs.py` — request output, completion output
  - `vllm/utils.py` — shared utilities
- Commit in the submodule, create request files, push via the CLI.
- Read any file in the repo for context.

## What you CANNOT do

- Modify CUDA kernels — `VLLM_USE_PRECOMPILED=1` means C++/CUDA code comes from prebuilt wheels.
- Modify `autoforge/runner/`, `autoforge/protocol/`, or `autoforge/perf/` — these run on the remote machine.
- Run the benchmark locally — the runner machine has the GPU.
- Add or remove Python dependencies (changing `pyproject.toml` or `requirements*.txt`).
- Break the vLLM public API — the benchmark client must still be able to send requests.
- Modify files outside the scoped paths listed above.

## CLI commands

All commands: `uv run autoforge <subcommand>`

| Command | What it does |
|---------|-------------|
| `uv run autoforge context` | Print campaign state, history, failures, and profiling data |
| `uv run autoforge submit -d "description"` | Validate submodule change, create request, commit, push |
| `uv run autoforge poll` | Poll git until latest request completes, print result |
| `uv run autoforge judge` | Compare result to best, keep or revert, record in TSV |
| `uv run autoforge baseline` | Submit baseline (no changes), wait for result |
| `uv run autoforge status` | Print latest request status without polling |
| `uv run autoforge sprint list` | List all sprints with iteration counts |
| `uv run autoforge sprint active` | Print active sprint name |
| `uv run autoforge revert` | Revert last vLLM submodule commit and force-push fork |
| `uv run autoforge build-log --seq N` | Print formatted build log for request sequence N |

## Output format

After `poll` completes:
```
Request 0003 completed. Metric: 2452.17
```

After `judge`:
```
Improvement! 2398.00 -> 2452.17
```
or:
```
No improvement (2380.50 vs best 2398.00). Reverting.
```

## The experiment loop

LOOP FOREVER:

1. `uv run autoforge context` — read current state, best metric, past failures
2. Read the vLLM source files in scope. Think about what to optimize. Study the hot path. Consider what prior failures tell you.
3. Edit the vLLM Python source files directly in `projects/vllm/repo/`. Make a single, focused change.
4. Commit in the submodule:
   ```
   git -C projects/vllm/repo add -A && git -C projects/vllm/repo commit -m "short description of change"
   ```
5. `uv run autoforge submit -d "short description of change"` — creates the request and pushes
6. `uv run autoforge poll` — wait ~5-8 minutes for the runner to build container and benchmark
7. `uv run autoforge judge` — automatically keeps or reverts based on the metric
8. Repeat from step 1

## Error handling

- **Build failure**: `poll` will show the error. Run `uv run autoforge build-log --seq N` to see the full build log. Common cause: syntax error in Python code. Fix, commit, and `submit` again.
- **Deploy failure**: Usually an import error — the container starts but vLLM fails to import a modified module. Check the build log for tracebacks. Fix, commit, and `submit` again.
- **Test failure**: `judge` will revert the submodule. Move on to a different approach.
- **Timeout**: Treat as failure. `judge` will revert. Consider simplifying the change (large changes may slow the container build).
- **Poll shows "still running"**: Wait and poll again. Container builds from source take longer than prebuilt.
- **Multiple consecutive failures**: Re-read the source code. Review failures with `context`. Try a fundamentally different approach.

## Strategy: Python-level throughput optimization

### The bottleneck

With Qwen3-0.6B (a tiny 0.6B parameter model), GPU forward passes are fast. The bottleneck shifts to Python overhead between GPU calls: scheduling, memory management, input preparation, output processing, and async orchestration.

### Key optimization targets

1. **V1 Scheduler** (`vllm/v1/core/`):
   - Batch formation: how requests are grouped for each forward pass
   - Chunked-prefill decisions: when to split long prompts vs. process whole
   - Request priority and ordering

2. **KV Cache Manager** (`vllm/v1/core/`):
   - Block allocation and deallocation overhead
   - Prefix caching lookup efficiency
   - Free-block tracking data structures

3. **GPU Model Runner** (`vllm/v1/worker/`):
   - Input tensor preparation: converting request data to GPU tensors
   - Metadata construction for attention kernels
   - Reducing Python-side tensor operations before GPU launch

4. **Sampler** (`vllm/model_executor/layers/sampler.py`):
   - Sampling logic for greedy/top-k/top-p
   - Logprob computation when not needed
   - Output token post-processing

5. **Engine Core** (`vllm/v1/engine/`):
   - Async orchestration between scheduler, worker, and detokenizer
   - IPC overhead (multiprocessing pipes, shared memory)
   - Request routing and completion detection

6. **Tokenizer/Detokenizer** (`vllm/transformers_utils/`):
   - Batch decoding efficiency
   - Incremental detokenization overhead
   - Vocabulary lookup caching

### Optimization techniques

- **Reduce allocations**: reuse objects, avoid creating temporary lists/dicts in hot loops
- **Cache computed values**: memoize repeated lookups, pre-compute static data
- **Simplify hot-path conditionals**: remove dead branches, flatten nested conditions
- **Batch operations**: combine multiple small operations into single bulk calls
- **Streamline data structures**: use tuples instead of dicts for fixed-shape data, use arrays instead of lists for numeric data
- **Eliminate unnecessary copies**: pass references, use views instead of slices
- **Short-circuit early**: add fast paths for common cases (single request, greedy sampling)

### General tips

- **One change at a time.** Small, targeted changes are easier to evaluate.
- **Profile mentally.** Think about what runs on every token generation step vs. once per request.
- **Read the V1 path first.** vLLM v1 (`vllm/v1/`) is the active code path. Legacy code under `vllm/core/`, `vllm/engine/` may not be hit.
- **Read past failures.** The `context` command shows what was tried and failed.
- **Don't break correctness.** Throughput gains that produce wrong outputs are worthless.

## NEVER STOP

Once the experiment loop has begun, do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep or away from the computer and expects you to continue working *indefinitely* until you are manually stopped. You are autonomous. If you run out of ideas, think harder — re-read the source code for new angles, try combining previous near-misses, try more radical changes. The loop runs until the human interrupts you, period.

As a guide: each experiment takes ~5-8 minutes, so you can run ~8-12/hour or ~60-90 overnight. Make them count.
