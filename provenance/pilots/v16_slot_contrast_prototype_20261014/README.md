# V16 slot-contrast reader prototype: local tests only

2026-10-14. **16/16 ordinary local CPU tests; no CUDA/7B qualification or FT.**

[TESTS.xml](TESTS.xml) records the
[prototype suite](../../../tests/test_v16_slot_contrast.py). The
[implementation](../../../src/latent_workspace_ft_v10/v16_slot_contrast.py)
preserves an existing common reader at initialization and adds either centered
slot contrast or an identically initialized uncentered capacity control.

The 16 cases cover: two exact common-initialization cases; one parameter/init
match; three identical-slot/zero-question-gradient nulls; one nonzero raw-carrier
control; two written-zero cases; two cap/common-preservation cases; one live
query/memory/projection backward; one query-independent writer/interface check;
two tiny Mistral FP32/BF16 full-logit zero identities with live backward; and
one intentional rejection by the existing checkpoint owner.

This is a working-tree test run, not an isolated source-sealed execution. It
performs no optimizer update, real-model generation or judge call. The
separately source-sealed 164-case CPU/CUDA checkpoint-v2 qualification is not
qualification of this new reader. The old owner deliberately rejects its new
class until explicit descriptor/resume ownership is implemented and tested.

The null proves an architectural constraint on one route, not semantic memory
use. The common route can still carry shortcuts. Diverse random memory can
still drive the contrast route. Centering adds arithmetic; parameter and
update-budget matching is not FLOP or runtime matching. Zero output projection
initially blocks upstream interaction gradients, and collapsed slots or a
saturated common budget may continue to limit learning.

See [V16 staged plan](../../../docs/v16/PLAN.md). Old **FAIL / winner:none /
non-regression NOT_ESTABLISHED** remains unchanged.
