# Retirement of the three closed V16 scientific conditions

2026-10-20. **TERMINAL: exactly six V16 scientific checkpoint bodies deleted.**
Ryō explicitly approved recording and retiring the previously listed V16
candidates. This is a whole-condition retirement of `common`,
`raw_matched_control`, and `slot_contrast`: exactly their `step1.pt` and
`step2.pt` bodies. It is an explicit exception to keeping the latest and
previous checkpoint per condition, not a general cleanup policy.

The fixed-path [utility](../../../scripts/retire_v16_scientific_checkpoints.py)
reuses the existing audited filesystem primitives without modifying the
historical four-file retirement plan. Before deletion it requires fresh
SHA-256/size/identity checks of all six files, an exclusively created inventory,
publication of the exact plan and inventory on the named GitHub branch, another
all-file hash check, visible-process/open-handle screening and protected-state
metadata agreement. It journals each unlink separately. Failed/partial attempts
are retained and never retried automatically. This is not an atomic filesystem
transaction or proof of visibility into privileged services.

The inventory and intent were published at
`708f09a51952283ecf025b15e11604c42a10ba23` **before deletion**. The single
deletion transaction checked that exact GitHub branch HEAD, repeated all six
hashes and completed at **08:16:52 UTC**.
The [terminal receipt](deletion/DELETE_FINISHED.json),
[12-event journal](deletion/DELETIONS.jsonl), and
[pre-delete checks](deletion/PREDELETE.json) are separate from the immutable
inventory. The [read-only postflight](POSTFLIGHT.json) confirms all six exact
paths absent and the declared protected metadata unchanged. No failed,
partial or repeated retirement transaction exists.

Removed: **174,442,288,712 logical bytes (162.462041445 GiB)**, occupying
174,442,332,160 allocated bytes. In the deletion receipt filesystem available
space rose from 87,131,123,712 to **261,573,443,584 bytes (243.609253 GiB)**:
an observed increase of 174,442,319,872 bytes, 12,288 bytes below allocation.
Receipts and other filesystem activity can affect this difference. The later
08:18:38 UTC postflight observed **261,573,406,720 bytes (243.609219 GiB)**,
119.61 GiB available RAM, and an idle RTX 5090 (10/32,607 MiB; no compute
process). These are point-in-time measurements, not reservations.

The read-only inventory completed at **08:11:15 UTC**, from source
`3cdce65a59da599d29c00de741abd7f851853e70`.
All **6/6** current file SHA-256 values and sizes match the historical checkpoint
receipts. [PLAN.json](PLAN.json) binds the fixed target paths, both source
utilities, and **667** unchanged historical evidence files.
[INVENTORY.json](INVENTORY.json) records current file identity, protected-state
metadata, available disk space and visible-process checks. No target handle or
target-referencing command was visible; five service processes had limited
visibility, explicitly `UNKNOWN`. [FINISHED.json](FINISHED.json) is an
inventory receipt, not evidence of deletion. The local guards passed
[57/57 tests](TESTS.xml), with no failures/errors/skips; Ruff passed.
Available space at inventory completion was **87,145,967,616 bytes**.

## Exact authorized scope

All paths share the Furnace prefix
`/home/ryospiralarchitect/spiralreality/SpiralReality/tmp/latent-v16-full-comparison-20261014/checkpoints/`.

| Condition | Exact files | Total logical bytes |
| --- | --- | ---: |
| `common` | `step1.pt`, `step2.pt` | 58,109,645,496 |
| `raw_matched_control` | `step1.pt`, `step2.pt` | 58,166,321,608 |
| `slot_contrast` | `step1.pt`, `step2.pt` | 58,166,321,608 |
| Total | 6 files | 174,442,288,712 |

The [comparison](../../pilots/v16_full_comparison_20261014/RESULTS.md) and
[population diagnostics](../../pilots/v16_population_diagnostics_20261015/README.md),
including raw outcomes, checkpoint/state hashes, source seals, negative results
and evaluation denominators, remain unchanged. The historical
[candidate listing](../native_ft_candidates_20261020/README.md) remains a
read-only snapshot, not a deletion receipt. The new plan fingerprints every
tracked file in those two evidence bundles and the candidate listing.

## Protection and recoverability

V18's two native checkpoints, pinned original Mistral snapshot, all V15 states,
beta package, features, other jobs, sources and non-weight artifacts are excluded
from deletion. The new transaction checks metadata of the V18 pair, three
specified retained feature banks and the pinned Mistral snapshot directory;
it does not claim a content audit of all excluded files.

**Git retains records, not the checkpoint payloads.** No backup of the six
weight bodies was created. Their exact state cannot be restored from
hashes/metrics; new training reproduction is not guaranteed to recover it.
Direct resume and new evaluations from these V16 checkpoint files are no
longer possible. The later retirement record controls current existence;
historical statements that checkpoints existed are retained as chronology.

Capacity recovery does not run 7B FT or establish resource admission for the
new graph. The next stage still requires a frozen, bounded native-memory 7B
canary. The old expression gate remains **FAIL**, winner **none**, and
non-regression **NOT_ESTABLISHED**.

The previous planning requirement (two V18-sized checkpoints plus the unchanged
50-GiB remaining-space floor) is **104.171800 GiB**, now leaving **139.437418 GiB**
of point-in-time headroom. That storage shortfall is resolved, not silently
lowered. Native graph/owner/runtime code is unchanged by retirement; its
203/203 CPU and 203/203 CUDA receipts were re-verified offline, with zero new
model forwards. [LOCAL_CHECKS.json](LOCAL_CHECKS.json) also records replay of
the six exact unlink outcomes and unchanged historical evidence.
The next unmet gate is the [bounded 7B canary](../../../docs/v1_0/FULL_FT.md),
not another weight-deletion request. No full-FT job, generation, judge, PR or
model publication was started here.
