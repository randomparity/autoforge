# autoforge-vllm — Perf Profiling Sprint

Autonomous vLLM optimization with Linux perf CPU profiling: improve Python-level serving throughput for Qwen3-0.6B by optimizing the hot path in vLLM's serving stack, guided by CPU stack traces and hardware counters.

## Setup

1. **Read the campaign config**: the sprint's `campaign.toml` defines the metric, scope, goal, and constraints.
2. **Check history**: `uv run autoforge context` shows current state, best result, recent attempts, and past failures.
3. **Verify the vLLM submodule**: `ls projects/vllm/repo/vllm/` should contain the vLLM Python source tree.
4. **Ensure the submodule optimization branch exists**: `git -C projects/vllm/repo checkout -b autoforge/2026-03-27-vllm-perf-profiling 2>/dev/null || git -C projects/vllm/repo checkout autoforge/2026-03-27-vllm-perf-profiling`. All vLLM changes accumulate on this branch inside the submodule.
5. **Establish baseline** (if no history): `uv run autoforge baseline` submits unmodified vLLM for a source build and waits for the result.
6. **Confirm and go**: Confirm setup looks good, then begin experimentation.

All artifacts (requests, results, failures, docs) are stored under `projects/vllm/sprints/2026-03-27-vllm-perf-profiling/`.

## Architecture

This is a two-machine system:

- **You** (the agent) edit vLLM Python source on this workstation and push changes via git.
- **A remote runner** polls git, builds a container from source (`VLLM_USE_PRECOMPILED=1`), runs the serving benchmark, captures a perf profile, and pushes results back.

You cannot run the benchmark locally — the runner machine has the GPU. Communication is entirely via git: you push request JSON files, the runner pushes results back. Each experiment takes ~5-8 minutes (push + container build + benchmark + profile + push back).

## Perf profiling

This sprint uses Linux `perf` to capture CPU-side stack traces and hardware counters against the vLLM container process. After each successful benchmark run, the runner:

1. Discovers the container's host-side PID via `docker/podman inspect`
2. Runs `perf record` (call-graph sampling at 99Hz) and `perf stat` (hardware counters) for 30 seconds
3. Folds the stack traces and summarizes the counters
4. Merges the profile summary into the results JSON under a `"profile"` key

### What profiling data tells you

- **Folded stacks**: show where CPU time is spent in the Python process — scheduler loops, memory management, tensor preparation, IPC overhead
- **Hardware counters**: cache misses, branch mispredictions, instructions per cycle — useful for identifying memory-bound or branch-heavy code paths
- **Top functions**: the profile summary includes the hottest functions by sample count

### Perf requirements for container profiling

Because `perf` must attach to a containerized process (which Docker's seccomp profile blocks), the profiler runs with `sudo`. The runner machine must have:

1. `perf` binary installed and in PATH
2. Passwordless sudo for perf: `echo "$USER ALL=(ALL) NOPASSWD: $(which perf)" | sudo tee /etc/sudoers.d/perf`
3. `sudo = true` in the profiler config: create `projects/vllm/perfs/perf-container.local.toml` with `[profiling]\nsudo = true`
4. `sysctl kernel.perf_event_paranoid <= 0` (PEBS precise events may need `0` or `-1`)
5. `kptr_restrict = 0` for kernel symbol resolution (optional but recommended)

Profile failure is non-fatal — if perf is unavailable, results still complete normally without profiling data.

### Interpreting profile results in `context`

After `poll` completes, the results JSON includes a `"profile"` section (when profiling succeeds). Use this to guide your next optimization: focus on the functions consuming the most CPU samples.

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

## The experiment loop

LOOP FOREVER:

1. `uv run autoforge context` — read current state, best metric, past failures, and profiling data
2. Read the vLLM source files in scope. Study the profile data from recent runs — focus on the hottest functions. Think about what to optimize.
3. Edit the vLLM Python source files directly in `projects/vllm/repo/`. Make a single, focused change.
4. Commit in the submodule:
   ```
   git -C projects/vllm/repo add -A && git -C projects/vllm/repo commit -m "short description of change"
   ```
5. `uv run autoforge submit -d "short description of change"` — creates the request and pushes
6. `uv run autoforge poll` — wait ~5-8 minutes for the runner to build container, benchmark, and profile
7. `uv run autoforge judge` — automatically keeps or reverts based on the metric
8. Repeat from step 1

## Error handling

- **Build failure**: `poll` will show the error. Run `uv run autoforge build-log --seq N` to see the full build log. Common cause: syntax error in Python code. Fix, commit, and `submit` again.
- **Deploy failure**: Usually an import error — the container starts but vLLM fails to import a modified module. Check the build log for tracebacks. Fix, commit, and `submit` again.
- **Test failure**: `judge` will revert the submodule. Move on to a different approach.
- **Timeout**: Treat as failure. `judge` will revert. Consider simplifying the change (large changes may slow the container build).
- **Poll shows "still running"**: Wait and poll again. Container builds from source take longer than prebuilt.
- **Multiple consecutive failures**: Re-read the source code. Review failures with `context`. Try a fundamentally different approach.
- **Profile failure**: Non-fatal. The test result still completes; you just won't get CPU profiling data for that run. Check runner logs for perf-related warnings.

## Strategy: Python-level throughput optimization

### The bottleneck

With Qwen3-0.6B (a tiny 0.6B parameter model), GPU forward passes are fast. The bottleneck shifts to Python overhead between GPU calls: scheduling, memory management, input preparation, output processing, and async orchestration.

### Using perf data to guide optimization

1. **Check the profile summary** in `context` output after each run
2. **Identify hot functions** — functions with the most samples are where CPU time is spent
3. **Look for patterns** — repeated allocations, deep call stacks, cache misses
4. **Target the hottest code** — optimize the top 3-5 functions by sample count
5. **Verify improvement** — after your change, check if the hot functions shifted or reduced

### Key optimization targets

1. **V1 Scheduler** (`vllm/v1/core/`): batch formation, chunked-prefill decisions, request scheduling
2. **KV Cache Manager** (`vllm/v1/core/`): block allocation, prefix caching lookup, free-block tracking
3. **GPU Model Runner** (`vllm/v1/worker/`): input tensor preparation, metadata construction
4. **Sampler** (`vllm/model_executor/layers/sampler.py`): sampling logic, logprob computation
5. **Engine Core** (`vllm/v1/engine/`): async orchestration, IPC overhead, request routing
6. **Tokenizer/Detokenizer** (`vllm/transformers_utils/`): batch decoding, vocabulary lookup

### Optimization techniques

- **Reduce allocations**: reuse objects, avoid creating temporary lists/dicts in hot loops
- **Cache computed values**: memoize repeated lookups, pre-compute static data
- **Simplify hot-path conditionals**: remove dead branches, flatten nested conditions
- **Batch operations**: combine multiple small operations into single bulk calls
- **Streamline data structures**: use tuples instead of dicts for fixed-shape data
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
