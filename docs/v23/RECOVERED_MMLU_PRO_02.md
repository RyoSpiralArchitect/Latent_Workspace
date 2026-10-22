# V23 recovered MMLU-Pro 02 — inactive CUDA reservation reclamation

Ryō separately authorized the repair, regressions and a new CPU→CUDA→base→off→on
attempt after the [allocator safety stop](../../provenance/pilots/v23_recovered_mmlu_pro01_20261022/README.md).
The stopped 799-file source, all 280 base direct scores and the incomplete first
reasoning sequence are retained; none is spliced into this new trial.

The only inference change is an explicit generation-boundary guard:
`synchronize → record live/reserved bytes → empty_cache → record bytes → original guard`.
The preceding full-prefix result has been deleted and the selected token copied
to CPU. Only inactive allocator reservations are released; live allocation must
be unchanged or the run fails closed. Every step has an append-only cache audit.
There is no KV cache, tensor offload, model/dtype/backend/seed/prompt/scoring
change, fewer shots, lower token cap or relaxed resource floor. Direct scoring
still uses the original implementation. The default original runner has no
reclamation callback; the separate entry supplies it explicitly.

Regression controls cover ordering, no CUDA calls on CPU/non-generation phases,
unchanged live allocation, propagated resource stops, same-seed BF16 tiny
generation equality with empty/nonempty memory and greedy/sampled decoding,
unmodified model/RNG/no gradients, exact original policy and rejected floor
changes. Both full **315-test** suites and the CPU visibility audit must pass,
with the original **4 GiB / 900 seconds** qualification caps. No exclusions.

The planned scope remains **840 direct scores + 84 reasoning sequences** across
three arms. All inputs and the 5-shot/1,024-token reasoning policy are unchanged.
The same calibrated 174-request judge study is independent and uses the completed
comparison bank. No new judge rubric/calibration, training, weight save/deletion,
export or release. The old expression gate remains **FAIL**, winner **none**,
non-regression **NOT_ESTABLISHED**. Stop on any new failure; never auto-retry.

The native cut-4 graph and strict v1/v2 owner restore require the existing
PyTorch path; the managed TensorRT-LLM runtime cannot reproduce this intervention
interface. Its doctor is checked, but neither managed nor training dependencies
are modified. The new source is committed before launch in an isolated worktree.
