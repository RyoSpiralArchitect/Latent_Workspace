# V18 window/reference owner — qualified recovery 01

2026-10-15. **310/310 PASS independently on Furnace CPU and CUDA, with offline
source/receipt verification.** This qualifies tiny engineering mechanics only.
No 7B training, preservation loss, real reference capture, new reader-selection
factor or language-quality evaluation is implied.

The [original attempt](../v18_window_reference_20261015/README.md) remains
**FAILED**: its 310 tests passed per device, then the import guard mishandled
PyTorch's virtual module filename. Ryō authorized this distinct corrected-source
trial. Only the runner and its guard tests changed; all 310 selected tests,
three new learner modules, learning arithmetic, resource limits and criteria
are unchanged. Neither original receipt was overwritten or reclassified.

## Source and execution

Execution commit: `cc9cc49e2ea1da5a73fd08bbecf2c3584125b085`,
[557-file seal](SOURCE_SEAL.json). Each fresh process checked the exact clean
checkout before project imports, then verified 68 imported module names mapping
to 67 unique sealed source files. The [offline replay](OFFLINE_VERIFY.json)
verifies both terminal manifests, exact test populations, source hashes, runtime
metadata, offline flags and claim ceilings. All 546 preceding V16 source files
and the original failure bundle are unchanged.

| Runtime | Passed / planned | Failures / errors / skips | JUnit test time | Total time | Peak CUDA allocated |
| --- | --- | --- | --- | --- | --- |
| Furnace CPU | 310/310 | 0 / 0 / 0 | 80.758 s | 83.200039 s | Not applicable |
| Furnace CUDA | 310/310 | 0 / 0 / 0 | 110.200 s | 112.882262 s | 67,661,824 bytes / 64.527344 MiB |

CPU [STARTED](cpu/STARTED.json), [JUnit](cpu/TESTS.xml),
[FINISHED](cpu/FINISHED.json); CUDA [STARTED](cuda/STARTED.json),
[JUnit](cuda/TESTS.xml), [FINISHED](cuda/FINISHED.json).
Native integration/gradient fixtures route to the selected device; pure schema
and CPU-bank tests do not become GPU kernels merely because the suite is CUDA.
Comparisons are within-runtime, not CPU/CUDA bitwise equivalence.
Native model integration is qualified on the tiny Mistral binding only; a
model-neutral interface does not qualify other architectures automatically.

Runtime: Python 3.12.14, Torch 2.13.0+cu132, Transformers 5.15.0, pytest 9.1.1,
CUDA 13.2, Linux x86_64 / RTX 5090. Both processes used two CPU threads, a
900-second deadline, and a fixed 4-GiB CUDA allocator ceiling. They ran
concurrently; timings are not a speed benchmark. Tiny peak memory is not a
7B forecast. CPU PID 1809185 and CUDA PID 1809222 both exited 0.

## Exact scope of the tests

Each device ran **85 reference-bank + 59 objective + 166 learner cases = 310**:

- Immutable supplied full-vocabulary bank ownership, schema/provenance hashes,
  exact native-dtype values, nonaliasing exports and mutation rejection. Capture
  origin, tokenization and family disjointness remain external declarations;
  no real original-model bank was captured.
- Complete-window counts and independent reduction/gradient oracles at 2, 7,
  16 and 37 rows; empty affected/unaffected strata reject. Historical 16-pair
  losses/components/every gradient are exact in FP32/BF16, full/frozen and
  checkpointing on/off, for affected and unaffected cases.
- 24 variable 2→3-pair serialized replay configurations: three reader arms ×
  full/frozen × FP32/BF16 × checkpointing on/off. Checkpoint snapshots, next
  update, model/master/optimizer state and RNG continuation agree exactly.
- 12 historical-window gradient-buffer/update parity cells, plus 12 independent
  variable-window native-dtype CPU accumulation / AdamW / Adafactor references.
- Partial/order rejection, exact nested checkpoint schema, fail-before-write
  corruption checks (including tensor versions/storage and RNG), common-reader
  policy guards, and flat/nested objective and reference-source binding.

The separate [123 local guard/verifier tests](LOCAL_GUARD_TESTS.xml) pass:
36 runner controls (including nine new virtual-module regressions) and 87
synthetic receipt controls. These are not added to the 310-per-device denominator.
Ruff passes for the new implementation, runner, verifier and tests.

## Bounded conclusion and next work

The [complete-window/reference owner](../../../docs/v18/WINDOW_REFERENCE.md)
can carry these declared reductions and supplied immutable evidence through
qualified tiny updates and save/resume. Its reference role is still
`reference_only_no_preservation_loss`. Full-vocabulary tuple storage, repeated
hash checks and actual capture need their own memory/transfer design before a
large bank; no correctness floor is established by this engineering result.

Next is the [selection-only operand-query proposal](../../../docs/v18/SELECTION_FACTOR_PROPOSAL.md):
preserve the common final-state route, test ordered versus symmetric operand
queries only in the interaction path, and first require controlled reciprocal
binding before using the real writer or selecting a 7B training cell. The
proposal is not implemented or launched by this qualification.

No model API request, free learner generation, paid/manual judge, real reference
capture, weight deletion, HF upload, PR creation or merge occurred. The beta
release remains conditional. **Old FAIL / winner:none / non_regression
NOT_ESTABLISHED is unchanged.**
