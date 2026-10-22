# Native length resource probe 01 — stopped before backward

2026-10-21 JST. Source `2c7a62eafd525a13aefcb976c4fa99f97165f37a`,
693 sealed source files. The original short two-update/replay pass is unchanged.

- CPU qualification: **253/253 passed**, zero failures/errors/skips.
- CUDA qualification: **253/253 passed**, zero failures/errors/skips.
- Pinned Mistral identity: both historical hash schemes matched.
- Real role: **INCOMPLETE_NO_RETRY**, `ValueError: Unknown objective`.
  The diagnostic incorrectly replaced the owner's objective identifier with
  `synthetic_length_probe_no_update`; the owner correctly rejected it.
- Stopped at owner construction, before any of the three backward rows.
  Native updates **0**, checkpoint writes **0**, model-generated sequences **0**.
- No measured length-resource conclusion, no quality result, no retry of this
  run. Raw receipts and the literal log remain unchanged under `furnace/`.

The role terminal SHA-256 is
`7e39eb4f318346c90331bc6261224f4cff7646ddd702e2ed1b80deb988b95d3d`.
Ryō subsequently explicitly approved repair, regression tests and a **separate**
attempt with the same limits and zero updates/saves. That is not a change to
this failed result. The actual loss remains query-only token-weighted causal
NLL; resource-probe purpose belongs in the diagnostic receipt, not the loss ID.

Historical **FAIL / winner:none / non_regression NOT_ESTABLISHED** remains.
