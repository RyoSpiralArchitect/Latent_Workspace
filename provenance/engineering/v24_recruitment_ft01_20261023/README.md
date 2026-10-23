# V24 R1 FT qualification: interrupted after the first saved update

2026-10-23. **CPU 570/570 PASS; CUDA 570/570 PASS; one of two 7B
canary updates completed; exact replay NOT RUN; scientific FT NOT RUN.**
The terminal remains `INCOMPLETE_NO_RETRY`. This is a shared-GPU contention
stop, not a measured capability failure and not permission to bypass a gate.

## Provenance and denominators

Execution source: `d43382833f6dc85787720bda80aec511c66f58be`,
[831-file source seal](furnace/SOURCE_SEAL.json). The source checkout remained
clean and every sealed byte matched after termination. The [prepared bank](../v24_recruitment_preparation01_20261023/README.md)
has a separate source, `92d078880176d1a3f6fd1aa16adc9d2c19050b85`, and manifest
SHA256 `6f1869b47e2e592d9ffdb7fda21812d08a1baad9d9d7ec148067171e026cc854`.
No frozen recipe, source seal, threshold, coefficient or data body was changed.

| Stage | Observed / planned | Outcome |
| --- | --- | --- |
| Isolated CPU qualification | 570 / 570 tests; zero failures/errors/skips | PASS, 74.221 s |
| CUDA qualification | 570 / 570 tests; zero failures/errors/skips | PASS, 78.016 s |
| 7B mixed-route canary | 1 / 2 updates; 4 / 8 backward rows | Stopped after first save |
| Canary fresh-process replay | 0 / 1 updates | NOT RUN |
| Inline scientific arm | 0 / 32 updates | NOT RUN |
| Workspace scientific arm | 0 / 32 updates | NOT RUN |
| Generation / judge / held-out model evaluation | 0 | Not dispatched |

The CPU [isolation receipt](furnace/qualification/CPU_ISOLATION.json), CPU
[XML](furnace/qualification/cpu/TESTS.xml) and CUDA [XML](furnace/qualification/cuda/TESTS.xml)
are retained. These are actual Furnace qualifications, distinct from the
previously reported local 566/570 result whose four subprocess dependency
failures remain in the preparation bundle. Post-run offline verifier and
retirement-guard tests are separate; they do not change the frozen 570-test set.
The local selected verification/retirement/route-runner regression suite passed
**59/59**, with Ruff PASS. This includes an explicit regression that the actual
failed canary cannot pass the spent-checkpoint retirement gate.

## What happened on 7B

The [first completed update](furnace/raw/canary/step1.json) contains four frozen
rows and **1,171 supervised target tokens**: 982 English-instruction tokens,
10 world tokens, 52 stable-filter tokens, and 127 prose tokens. They exercised
both inline and workspace routes. All **291 native parameter tensors** have
update entries; the native, master and optimizer fingerprints differ from
[initial state](furnace/raw/canary/INITIAL.json). This is engineering evidence,
not a loss trend, full-run result, or correctness improvement.

The last [GPU resource record](furnace/raw/canary/RESOURCES.jsonl) is at
`saved:canary_step1.pt`. It records own PID `4139912` and separate PID `4140617`,
whose executable was under `scratch/ltt-furnace-20261017` and whose GPU memory
was **1,354,760,192 bytes (1.2617 GiB)**. The [canary terminal](furnace/raw/canary/FINISHED.json)
reports `ValueError: Another GPU client; stop own job only`. Our process
stopped; the other workload was not changed. A subsequent idle GPU snapshot
does not invalidate that historical contention observation.

Observed PyTorch high-water marks were **29,797,427,712 allocated bytes
(27.7510 GiB)** and **30,903,631,872 reserved bytes (28.78125 GiB)**. The
recorded failure was not OOM, a lowered resource floor, or an incorrect
identity hash. It occurred in the post-save guard before update 2; there is
no `step2.json`, replay role, scientific arm, or successful checks terminal.

The failed raw terminal intentionally retains `native_weight_updates: null`.
The verified observed count of **one completed update** is derived separately
from matching per-row, update, state and save receipts. It does not rewrite
the original terminal or imply that the incomplete role passed.

## Checkpoint disposition and recovery boundary

Exactly one canary body is retained on Furnace:

- Path: `latent-v24-recruitment-ft01-20261023/checkpoints/canary_step1.pt`,
  relative to `/home/ryospiralarchitect/spiralreality/SpiralReality`.
- Bytes: **29,004,378,444 (27.0124 GiB)**.
- Complete SHA256:
  `19a09fcccc84960795bd02aa563a6e64d1d7061eac02e3dafaa5a780b9c4d4a8`.
- [Original save receipt](furnace/raw/canary/CHECKPOINT_canary_step1.pt.json) and
  [independent post-stop full-body rehash](BODY_REHASH_20261023.json) agree.
  Stable filesystem identity and no open handles were checked. **Restore and
  next-update equivalence have not been tested.**

The prepared [spent-canary retirement helper](../../inventory/v24_spent_canary_20261023/README.md)
is blocked: this checkpoint is not a completed/replayed spent canary. No
inventory, unlink or retirement receipt was produced. Original Mistral,
V18 comparators and V22/V23 finals remain protected. The separately authorized
[obsolete V15 pair retirement](../../inventory/v24_v15_engineering_20261023/README.md)
already freed **54.1187 GiB**; it is not undone or conflated with this run.

Do not rerun either launcher against this output tree, manufacture a checks
PASS, relax the other-client guard, or feed the canary into a scientific arm.
A new attempt requires a separately recorded recovery decision and a fresh
output identity, with the same frozen conditions unless explicitly revised.
Reconfirm an exclusive GPU window before admission. Current free disk after
retaining this canary was about **90.31 GiB**, enough for another 28-GiB
engineering body plus the 50-GiB floor, but not two new finals plus that floor.
Any future checkpoint retirement needs its own exact ledger; no additional
body deletion is implied by this stopped result.

## Offline verification and claim ceiling

Run from the repository root (no model load, CUDA call, or provider call):

```bash
python3 scripts/verify_v24_recruitment_ft.py \
  provenance/engineering/v24_recruitment_ft01_20261023/furnace --phase stopped
```

This replays the committed source archive, qualification manifests/XML,
isolation receipt, three failure manifests, fixed first-window keys, saved
state fingerprints and actual foreign-client record. `--phase checks` and
`--phase training` deliberately reject this bundle. No tensor computation or
checkpoint-body rehash is repeated locally; the latter has its own remote
receipt above. Raw log/XML bytes are preserved, including any whitespace.

The new data factor still needs successful replay and **32 updates / 538 rows /
21,112 targets per arm**, then a separately specified capability evaluation.
No new candidate, causal workspace gain or base non-regression is established.
Old expression gate **FAIL**, winner **none**, non-regression
**NOT_ESTABLISHED** remain unchanged.
