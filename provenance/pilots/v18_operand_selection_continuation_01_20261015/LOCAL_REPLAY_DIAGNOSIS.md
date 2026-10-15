# Local offline replay diagnosis

2026-10-15. **Cross-platform exact replay failed; no acceptance tolerance changed.**
This is a read-only diagnosis of the saved `assay_cpu` and `assay_cuda` bundles,
not a new experiment or a replacement for their terminal receipts. Subsequent
same-runtime Furnace audits passed both the unchanged exact raw replay and the
supplemental audit: [CPU receipt](ASSAY_CPU_AUDIT.json) and
[CUDA receipt](ASSAY_CUDA_AUDIT.json). Each reports zero forwards and updates.
The failed cross-platform check remains a distinct observation.

## Method and runtime

The local check used Python **3.13.13**, PyTorch **2.13.0**, macOS 26.2 **arm64**,
and two CPU threads, from this checkout's `.venv/bin/python` with bytecode writes
disabled (`-B`). The execution receipts instead report Python **3.12.14** and
PyTorch **2.13.0+cu132** on host `spiralreality`. The supplemental auditor was
frozen at `d2752de88b1f908ed5ee52496196853fe9d5cbca`; experiment source remains
`dd10b20a8fbb0e32e5ac89bcec939802e6940f8b`.

The diagnostic strictly parsed all saved case rows, grouped them by seed,
factor, split and native dtype, reconstructed CPU FP32 full-vocabulary logit
tensors, and called the unchanged frozen `summarize` function. Labels and frame
counts came from the saved realized populations, loaded with `weights_only=True`.
Reader construction and forward functions were replaced with raising guards in
the diagnostic process. No model was constructed, no forward or update ran, and
no artifact or source was changed. The comparison was printed to tool output;
this note records its aggregate findings.

## Exact comparisons

Each runtime contains **50 groups / 36,864 raw rows**. These groups include the
untrained common-only reference and both evaluation dtypes; they are not 50
independent fits.

| Saved study | Integer metrics matching | Float metrics differing | Groups with any difference | Maximum absolute float difference |
| --- | ---: | ---: | ---: | ---: |
| CPU | 700/700 | 27/350 | 20/50 | `9.5367431640625e-7` |
| CUDA | 700/700 | 20/350 | 15/50 | `1.430511474609375e-6` |

All **250/250 threshold-bearing rate comparisons per runtime** match exactly,
as do all text fields. Only two descriptive means differ:

| Metric | CPU differences | CUDA differences |
| --- | ---: | ---: |
| `affected_donor_margin_mean` | 16 | 9 |
| `unaffected_absolute_margin_drift_mean` | 11 | 11 |

The first CPU difference is `17/centered_final/dev/torch.float32`, unaffected
drift mean: saved **0.2550196647644043**, local **0.2550196945667267**.
The first CUDA difference is `17/centered_ordered/dev/torch.float32`, donor mean:
saved **7.408483028411865**, local **7.408482074737549**.
Each study also has one differing BF16 group's donor mean
(`29/centered_final/held_out/torch.bfloat16`): saved **7.296165466308594**, local
**7.2961649894714355**. Summary reductions still use CPU FP32 after logits are
reconstructed, including for that BF16 evaluation group.

These observations are consistent with platform-dependent FP32 reduction order;
they do not independently prove that cause. The frozen exact-equality replay
correctly rejects the local check. Neither thresholds, source seals, saved
metrics, scientific gates nor replay code were relaxed or rewritten. In
particular, integer/rate agreement alone does **not** turn this failed exact
replay into a pass.
