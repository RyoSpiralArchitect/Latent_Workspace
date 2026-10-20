# Retirement of the three closed V16 scientific conditions

2026-10-20. **Prepared; no deletion receipt yet.**
Ryō explicitly approved recording and retiring the previously listed V16
candidates. This is a whole-condition retirement of `common`,
`raw_matched_control`, and `slot_contrast`: exactly their `step1.pt` and
`step2.pt` bodies. It is an explicit exception to keeping the latest and
previous checkpoint per condition, not a general cleanup policy.

The fixed-path [utility](../../../../scripts/retire_v16_scientific_checkpoints.py)
reuses the existing audited filesystem primitives without modifying the
historical four-file retirement plan. Before deletion it requires fresh
SHA-256/size/identity checks of all six files, an exclusively created inventory,
publication of the exact plan and inventory on the named GitHub branch, another
all-file hash check, visible-process/open-handle screening and protected-state
metadata agreement. It journals each unlink separately. Failed/partial attempts
are retained and never retried automatically. This is not an atomic filesystem
transaction or proof of visibility into privileged services.

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
weight bodies is being created. Their exact state cannot be restored from
hashes/metrics; new training reproduction is not guaranteed to recover it.
Direct resume and new evaluations from these V16 checkpoint files will no
longer be possible after deletion.

Capacity recovery does not run 7B FT or establish resource admission for the
new graph. The next stage still requires a frozen, bounded native-memory 7B
canary. The old expression gate remains **FAIL**, winner **none**, and
non-regression **NOT_ESTABLISHED**.
