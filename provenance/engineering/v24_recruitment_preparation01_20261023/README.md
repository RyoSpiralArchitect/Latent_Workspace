# V24 R1 route-bank preparation: complete, not trained

Source **`92d078880176d1a3f6fd1aa16adc9d2c19050b85`**. Furnace isolated checkout
`worktrees/latent-v24-recruitment-data01-20261023`; output
`latent-v24-recruitment-data01-20261023`, under the Furnace project root.
This was a CPU-only tokenizer/data run, not native model inference or training.

**60/60 CPU tests passed; CPU/GPU isolation PASS.** The single data role and
dispatcher completed without a retry. Zero native forwards, updates, new
sequences, teacher calls, judge requests or weight saves. The source seal
contains **825 files** and replays against the committed Git archive.

## Frozen matched-arm exposure

Both route arms have the same 32 ordered windows, 538 whole training rows,
21,112 supervised target tokens and 403 source groups. Differences are the
placement of the supplied record, not target selection or supervised budget.

| Role | Row occurrences per arm | Target tokens per arm |
| --- | ---: | ---: |
| Expanded world | 306 | 2,023 |
| New reasoning/transform | 151 | 2,036 |
| Instruction | 32 | 8,431 |
| Prose | 40 | 5,080 |
| Code | 9 | 3,542 |
| **Total** | **538** | **21,112** |

Each route registry has 5,548 train/development rows. Maximum query length is
1,024 for both routes; maximum memory length is 0 inline / 121 workspace.
No truncation was used. The mixed-route canary selects eight row occurrences
over two windows. The fixed development NLL panel has 76 rows per route;
NLL is not a capability or non-regression gate.

The public synthetic source contains 512 world groups / 4,096 raw rows and
264 new arithmetic/register/filter groups / 2,112 raw rows. Whole source-group
splits, twin direction, unaffected controls and independent oracle checks
replay. New reasoning confirmation has 48 groups / 384 raw rows; old world
confirmation has 56 groups / 448 rows; the three-hop OOD family has 64 groups /
512 rows. These are **not training inputs and have zero model evaluations**.

## Source, replay and private data boundary

- [Source seal](furnace/SOURCE_SEAL.json), [CPU receipt](furnace/qualification/cpu/FINISHED.json),
  [isolation audit](furnace/qualification/CPU_ISOLATION.json).
- [Dispatcher terminal](furnace/raw/FINISHED.json), [data terminal](furnace/raw/data/FINISHED.json),
  [data manifest](furnace/raw/data/bank/MANIFEST.json), [summary](furnace/raw/data/bank/SUMMARY.json),
  [ordered schedule](furnace/raw/data/bank/SCHEDULE.json), [synthetic audit](furnace/raw/data/bank/SYNTHETIC_AUDIT.json).
- Manifest SHA256: `6f1869b47e2e592d9ffdb7fda21812d08a1baad9d9d7ec148067171e026cc854`.
  Data-terminal SHA256: `fbc25077df7d7f82caf84004e4953f3f2d0925b1d59b5046c5a7cc1ecd78419b`.
- [Offline verifier](../../../scripts/verify_v24_recruitment_preparation.py)
  checks the entire archived source, public receipt subsets, exact synthetic
  regeneration, CPU XML and isolation, ordered-row counts and role-token sums.
  It explicitly omits `PRIVATE_CANARY.json.gz`, `PRIVATE_inline.json.gz` and
  `PRIVATE_workspace.json.gz`: those arrays contain existing source-owned
  preservation text and remain on Furnace. Their hashes are in the manifest;
  the successful producer checked written arrays, and the training loader
  independently rechecks all private bytes and the exact route schedule.
  **Local public replay does not claim to re-tokenize those private arrays.**

The subsequent proposed FT source's larger local selection recorded
**566 PASS / 4 FAIL / 0 skipped** in [LOCAL_570.xml](LOCAL_570.xml).
All four failures are the existing fresh-process owner/preservation tests:
the local Python 3.13 isolated child cannot import `typing_extensions`, before
model computation. They are not excluded or relabeled; the new pinned Furnace
CPU and CUDA selections must each pass **all 570** before 7B dispatch.
The new FT harness's 21 local tests passed, including FP32/BF16 mixed-route
owner update/save/replay, mutated data rejection and the spent-canary gate.

Read [the predeclared route-learning scope](../../../docs/v24/RECRUITMENT_FT_01.md)
and [FT plan](../../../configs/v24/RECRUITMENT_FT_01.json). No trained winner,
matched-compute advantage, new latent S, general intelligence, non-regression
or release is claimed. Old `FAIL / winner:none / NOT_ESTABLISHED` remains.
