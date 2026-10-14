# V18 selection/window qualification before full-parameter FT

2026-10-15. Ryō approved completing the window owner and CUDA update/restart
checks, then proceeding to full FT. This additive engineering stage changes no
historical arithmetic, reader whitelist, source seal or scientific threshold.

Implemented [V18SelectionWindowLearner](../../src/latent_workspace_ft_v10/v18_selection_window_learner.py)
uses format `v18-selection-window-reference-resume-v1`. It binds the independently
declared interaction-query policy, ordered window schedule, exact reduction
denominators, cursor, immutable supplied reference bank and native inner owner.
All outer/inner restore checks precede native/bridge/RNG publication. Legacy
complete-window operations and objective arithmetic are inherited unchanged.
The bank remains reference-only: no preservation loss or capture claim is added.

Local development: **102/102 tests passed in 342.67 s**, including all three
query modes, raw/centered factors, FP32/BF16, frozen/full updates, variable
two-/three-pair windows, legacy final-route parity, malformed restore nonmutation,
snapshot independence and partial-window rejection. The separate offline
receipt-validator fixtures pass **23/23 in 1.69 s**; these are synthetic metadata,
not model evidence. Ruff passes. No execution-source file was edited during
the 102-case run.

## Frozen Furnace qualification

[Runner](../../scripts/qualify_v18_selection_window.py) and
[offline verifier](../../scripts/verify_v18_selection_window.py) are additive.
The exact source is committed and sealed before any remote computation. Use a
new isolated checkout and exclusive output directory; do not resume or retry an
ambiguous or failed launch. The historical local/remote bundles stay unchanged.

Each device, CPU then CUDA, has a 900-second envelope, two CPU threads, and a
4-GiB CUDA allocation cap. The coordinator imports no Torch and launches
children serially through the pre-import source guard with a fresh bytecode
prefix. Children inherit no API keys or arbitrary Python paths. The 102-case
unit-test interpreter exits before any restart child is created. A tests child
has at most 600 seconds; each restart child at most 60 seconds.

Ten restart cases per device: eight ordered-query FP32/BF16 × frozen/full ×
raw/centered cases, plus BF16/full/centered final and symmetric controls. Each
case has separate producer/resumer interpreters. The producer saves window 1
then computes window 2. The resumer rebuilds the independent caller contracts,
challenges ambient RNG, loads `weights_only=True`, and must reproduce the exact
complete window-2 receipt, optimizer/master/native/bridge payload fields and RNG
continuation. Source/import/runtime/file receipts and tiny checkpoint bytes are
retained. No full all-mode factorial process matrix or cross-device bit equality
is claimed. There are 21 computation children per device (one tests + twenty
restart), not 21 independent scientific experiments.

Offline verification rehashes the sealed source and all artifacts, validates
the exact case population, distinct process IDs and matching producer/resumer
receipts. It does not execute or replay the tensor checkpoints itself.

## Transition to full FT

Both device qualifications must pass before the separately frozen native run.
Capacity admission uses actual free GPU/host/storage state and contextual
backward, not tiny-test peaks. The storage forecast currently permits one
condition at a time, not three retained new arms. Full update means all native
Mistral parameters plus the writer/common/interaction partitions are trainable;
it does not imply a large-data run, a winner or release readiness.

Keep the prior **FAIL / winner:none / non_regression NOT_ESTABLISHED**. The
historical permutation failures are not repaired by state-owner qualification.
No benchmark, generation, paid judge, additional weight deletion, PR/merge or
Hugging Face upload is part of this engineering qualification.
