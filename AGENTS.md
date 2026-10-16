# BrainCogsEphysSorters

The spike sorters the U19 ephys pipeline runs on the cluster (Kilosort,
preprocessing with CatGT and IBL tools). Python >= 3.13, managed with uv.
`sorters/` and `preprocess_libs/` are vendored third-party code and binaries:
no hook touches them, and don't edit them.

## Setup and tests

```bash
uv sync --locked --only-group dev
uv run --no-sync pytest
```

Lint: `uvx prek run --all-files` (the same as CI's Lint workflow).

## Pins and gotchas

- U19-pipeline-python drives these sorters on the cluster, so pair dependency
  changes (kilosort, spikeinterface, ibllib) with a matching change there.

## Agent workflow

- Bugs: when you fix an error the user reported, first file an agent bug report issue from the user's account (`gh issue create -R BrainCOGS/BrainCogsEphysSorters`, template `.github/ISSUE_TEMPLATE/agent_bug_report.md`). Put the error exactly as the user pasted it under **Reported error**; don't ask for or invent a Slack link. Then fix it with the `bugfix-from-slack` skill (`.claude/skills/bugfix-from-slack/`, vendored from [agent-tooling](https://github.com/BrainCOGS/agent-tooling)); the PR says `Fixes #<issue>`. Commits, pushes, issues and PRs all go through the user's account.
- Commits end with one `Assisted-by: <Harness>:<model>` trailer per agent, e.g. `Assisted-by: ClaudeCode:claude-opus-5-5`. No AI co-authors, and no `Generated with` lines. `prek install` sets up the `ai-attribution` commit-msg hook (`.github/scripts/check_ai_attribution.py`, vendored from agent-tooling), and CI checks every commit of a PR.
- PRs target `main` on `BrainCOGS/BrainCogsEphysSorters`, opened from the user's own account.
