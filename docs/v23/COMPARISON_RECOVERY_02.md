# V23 whole-P-on recovery 02 — prepared, not dispatched

This is the same finite P-on-only evaluation as recovery 01, under a distinct
plan, source seal, execution directory and decision. Recovery 01's 789-file
source `106e12314d72a16a0515a5961989ed49a193a4f8`, passing visibility audit
and failed CPU collection are [retained unchanged](../../provenance/pilots/v23_comparison_recovery01_20261022/README.md).

The only execution repair is same-PID reentry of the already registered CPU
visibility boundary. It cannot authorize a fresh process that imported torch
before masking, a changed PID, or a removed mask. Four additional regression
cases cover these controls and collection under the real qualification argv;
the actual-entry subprocess test also reloads the module after torch import.
The original 244-test gate therefore becomes **248 tests per device**, with
no exclusions or threshold relaxation. CPU→CUDA→P-on remain sequential.
The numerical evaluator, original plan, inputs, restored weights and native
policy remain unchanged. The original 79 scores are never spliced.

Local boundary/judge/MMLU-Pro regression selection: **64/64 PASS**. This does
not replace either full Furnace gate. No new Furnace process, generation,
judge request, update, checkpoint save, deletion, export or release was run
for recovery 02 when this document was prepared. The separate recovery decision
is still required; see the [execution handoff](../../provenance/pilots/v23_comparison_recovery01_20261022/EXECUTION_HANDOFF.md).

Old expression gate **FAIL**, winner **none**, non-regression
**NOT_ESTABLISHED**. After a complete verified P-on arm, downstream judge
and MMLU-Pro must use explicit combined provenance, never a forged successful
original dispatcher. The calibrated judge and prepared benchmark policies
remain frozen.
