# Native-FT storage candidates — read-only inventory

Observed **2026-10-20 05:54:31 UTC**, on SpiralReality-furnace. **Deleted: 0.**
Ryō requested candidates in parallel with the next engineering qualification,
not retirement of a new condition. [INVENTORY.json](INVENTORY.json) retains
exact remote paths, current file sizes/mtimes, and historical checkpoint
receipts. Its historical SHA-256 values were **not recomputed** over the large
files in this read-only listing; size agreement is not current content proof.

All paths below are relative to the Furnace project root recorded in the JSON.
All eight listed checkpoints are regular files, not symlinks. The scope is
these explicit V16/V18 pairs, not every weight/cache on the machine.

## Candidates and protected comparators

| Condition / directory | Files | Total bytes | GiB | Proposed disposition, not authorization |
| --- | --- | ---: | ---: | --- |
| V16 `tmp/latent-v16-full-comparison-20261014/checkpoints/common/` | `step1.pt`, `step2.pt` | 58,109,645,496 | 54.12 | First whole-condition retirement candidate; oldest completed common control |
| V16 `tmp/latent-v16-full-comparison-20261014/checkpoints/raw_matched_control/` | `step1.pt`, `step2.pt` | 58,166,321,608 | 54.17 | Second whole-condition retirement candidate; completed matched control |
| V16 `tmp/latent-v16-full-comparison-20261014/checkpoints/slot_contrast/` | `step1.pt`, `step2.pt` | 58,166,321,608 | 54.17 | Keep for now: historical workspace comparator; lower-priority retirement choice |
| V18 `tmp/latent-v18-native-pilot-20261015/checkpoints/primary/` | `step1.pt`, `step2.pt` | 58,166,527,816 | 54.17 | Protect: latest retained qualified native-update/replay comparator |

Each condition has only **latest plus previous**. There is no excess third
checkpoint to rotate away under the current retention rule. Removing either
candidate pair therefore requires an explicit **whole-condition retirement**
decision, or an alternate storage destination. It is not ordinary rotation.
Git retains source, metrics, evaluation outputs, hashes and receipts, **not
the weight bytes**. Those records cannot reconstruct the exact trained weights
without a new training reproduction, whose equality is not assumed.

Preserved evidence: [V16 comparison](../../pilots/v16_full_comparison_20261014/README.md),
[V16 population diagnostic](../../pilots/v16_population_diagnostics_20261015/README.md),
[V18 native pilot](../../pilots/v18_native_pilot_20261015/README.md).
Before an authorized deletion, validate the exact files against receipts,
record the retirement and its consequence, and retain all non-weight artifacts.
The earlier [V16 engineering retirement](../v16_engineering_retirement_20261015/README.md)
and [V20 feature retirement](../v20_retirement_20261017/README.md) authorize
only their own historical targets, not these new candidates.

The original Mistral model cache, smaller V15 retained states, beta adapter
package and cut-4/beta feature banks remain protected. A separate scoped scan
found a ~4.10-GiB A5 development feature bank; it is **features, not weights**,
and cannot solve the capacity gap alone. It is not selected for removal here.

## Capacity decision

Available filesystem space was **91,695,153,152 bytes (85.40 GiB)**. Two old
V18-sized checkpoints plus the previous **50-GiB free-space floor** imply a
planning requirement of **104.17 GiB**, a shortfall of **18.77 GiB** before
new outputs. This is an estimate, not a measured reservation for the new
graph. Retiring the V16 common pair alone would make the corresponding
point-in-time estimate ~139.52 GiB free, but no space has been freed or reserved.

The tiny CPU/CUDA qualification fits without deletion. A 7B canary still needs
a storage decision, live capacity/admission recheck, a frozen bounded plan,
and then its own resource measurement. GPU idleness alone is not admission.
