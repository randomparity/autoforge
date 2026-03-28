# Sprint Migration Guide

How to create a new sprint from an existing one when shifting optimization
focus, trying a different strategy, or starting fresh iteration history.

## When to migrate

- Switching optimization targets (e.g. from baseline measurement to source optimization)
- Changing builder mode (e.g. prebuilt to source builds)
- Starting a new round of experiments with fresh history
- Narrowing or expanding the scope of allowed modifications

## Steps

### 1. Initialize the new sprint

```bash
uv run autoforge sprint init YYYY-MM-DD-slug --from existing-sprint
```

This copies `campaign.toml` from the parent sprint, stamps a fresh
`optimization_branch` (`autoforge/YYYY-MM-DD-slug`), creates empty
`requests/`, `docs/`, and `results.tsv`, and updates `.autoforge.toml` to
point at the new sprint.

### 2. Update campaign.toml

Open `projects/<project>/sprints/<new-sprint>/campaign.toml` and adjust:

- **`[campaign].max_iterations`** — set the iteration budget
- **`[goal].description`** — describe the new optimization focus
- **`[project].scope`** — allowed source paths (relative to submodule)
- **`[metric].threshold`** — minimum improvement percentage to keep a change
- **`[sprint]`** — add `description` and `parent` fields
- **`[platform]`** — target architecture and hardware
- **`[agent]`** — poll interval and timeout
- **`[profiling]`** — enable/disable profiling

### 3. Create program.md

Write `projects/<project>/sprints/<new-sprint>/program.md` following the
structure of existing sprint programs. Include:

- Setup steps (read config, check history, verify submodule, create branch, baseline)
- Architecture overview (two-machine system)
- What you CAN/CANNOT do (scoped paths, constraints)
- CLI command reference table
- Output format examples
- The experiment loop (8-step cycle)
- Error handling (build, deploy, test failures)
- Strategy section (optimization targets and techniques)

See `projects/dpdk/sprints/2026-03-25-ppc64le-mem-alignment/program.md` for
a reference implementation.

### 4. Switch builder mode (if needed)

If changing from prebuilt to source builds (or vice versa), edit the project's
build plugin config:

```bash
# projects/<project>/builds/<plugin>.toml
[build]
mode = "source"   # was "prebuilt"
```

### 5. Initialize the optimization branch

```bash
git -C projects/<project>/repo submodule update --init
git -C projects/<project>/repo checkout -b autoforge/YYYY-MM-DD-slug
```

### 6. Run a baseline

```bash
uv run autoforge baseline
```

This confirms the build pipeline works end-to-end and establishes a reference
metric for the new sprint.

## What carries over

- `campaign.toml` is copied from the parent sprint (then you customize it)
- The optimization branch name is stamped fresh by `sprint init`

## What does NOT carry over

- `results.tsv` — starts empty (fresh iteration history)
- `failures.tsv` — created on first failure
- `requests/` — starts empty
- `docs/` — starts empty
- Source changes — the new optimization branch starts from the submodule's
  current HEAD, not from the parent sprint's branch

## Checklist

Before starting experiments in the new sprint:

- [ ] `sprint init --from` completed successfully
- [ ] `campaign.toml` updated with new goal, scope, and constraints
- [ ] `program.md` created with strategy and instructions
- [ ] Builder mode matches intent (prebuilt vs. source)
- [ ] Optimization branch created in submodule
- [ ] `.autoforge.toml` points to new sprint
- [ ] `uv run autoforge doctor` passes
- [ ] `uv run autoforge context` shows the new sprint
- [ ] `uv run autoforge baseline` completes with a reasonable metric
