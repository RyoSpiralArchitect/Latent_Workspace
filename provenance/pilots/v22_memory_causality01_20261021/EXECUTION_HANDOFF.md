# V22 memory causality 01 — execution handoff

Ryō requested further analysis of whether V22 actually uses latent workspace
content, and evidence to guide V23 toward a future 1.0. This bounded diagnostic
does not authorize V23 training, new paid judges, checkpoint deletion or release.
The [design](../../../docs/v22/MEMORY_CAUSALITY_01.md) and committed plan freeze
2,492 prefix positions and 928 short deterministic intervention/replay answers.

- Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
- Branch: `SpiralReality/latent-memory-full-ft`.
- Origin: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
- Furnace checkout: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v22-causality01-20261021`.
- Evidence: `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v22-causality01-20261021`.
- Interpreter: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/aether-cuda-pretrain-20260822/.venv/bin/python` (read-only).
- Finite session: `ltws-v22-causality01-20261021`.
- Source identity: recorded in `SOURCE_SEAL.json` before qualification.

Furnace was idle: no compute clients, 10/32607 MiB GPU, 119 GiB available
host memory, approximately 76 GB filesystem space. `spiral-local-llm doctor`
passed with `ok:true`, empty failure codes and matching frozen packages. Its
existing modelopt/transformers warning was retained. Native PyTorch is required
for the custom cut-state graph and strict full-owner restoration. No managed
runtime or unrelated Aether/QSpace job is changed.

Use only `spiral`. `scripts/launch_v22_causality.sh <exact-source-commit>` is a
finite CPU → CUDA qualification → three fresh-process role launch. Existing
output is an error. Stop at any failed gate; never resume/retry a completed or
partial cell. Preserve failures and request direction for a distinct recovery.
Check terminal manifests, not just a vanished PID. No recurring monitor.

The target is the unchanged step-32 file, SHA256
`cdf605b8740a45d16d03f8e375497ad0dabd45e8548bae2733057eee83675c68`.
Old training/comparison/weight-diagnostic bundles are immutable. The local
[preflight limitation](LOCAL_PREFLIGHT.md) is retained separately from the
mandatory Furnace qualification. The gate remains
**FAIL / winner:none / non_regression NOT_ESTABLISHED**.

Status at creation: source preparation, no formal trial launched yet.

## Terminal handoff

Frozen execution source: `fd77ee4c84a99a99c22b28aa85d321e95caa843f` (739 files).
Both qualifications passed 187/187. All three roles and dispatcher are terminal:
`V22_CAUSALITY_COMPLETE_NOT_RELEASE`, 2,492 prefix positions, 928 sequences,
7,653 generated tokens, 876 EOS / 52 caps. Fixed-extent future discrepancies:
zero. Identity/twin historical generation replay disagreements: zero / 288.

The [offline terminal witness](furnace/REMOTE_TERMINAL_CHECK.json) verifies the
same step-32 checkpoint body after execution, all four source checkouts clean,
all 928 literal decodes, no checkpoint writes and no surviving run/GPU workers.
All 58 Furnace files are copied to [furnace/](furnace/). No retry, new training,
judge, weight deletion, PR/merge or release was performed. No monitor was created.

[README.md](README.md), [SUMMARY.json](SUMMARY.json), [ANSWER_BANK.md](ANSWER_BANK.md)
and the additive [INTERPRETATION.json](INTERPRETATION.json) retain positive and
negative outcomes and complete denominators. Run `summarize.py --verify` and
`interpret.py --verify` offline. The next investigation is proposed in
[docs/v23/ROADMAP_TO_1_0.md](../../../docs/v23/ROADMAP_TO_1_0.md), not dispatched.
