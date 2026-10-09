# V15.5 diagnostic continuation 01: running

Client date: 2026-10-10 (Asia/Tokyo). **RUNNING — not a terminal results report.**
The previous expression gate is still **FAIL**. No learner update, new learner
generation, provider substitution, or weight deletion is involved.

Following the [terminal partial report](../v15_5_diagnostic_judge_20261010/README.md),
Ryō approved a separate continuation of only the 320 **never-dispatched** Mistral
study requests. The original four timeout outcomes (remote execution/billing
unknown), invalid repeat, and OpenAI calibration failure are not retried or
reclassified. All 1,042 original-bundle files remain sealed and unchanged.

The unchanged `mistral-large-4` setting began at **07:02:25 JST** on 2026-10-10,
using committed and pushed source `92bd66a0024f8c4b4442d1addfa4105f60287b96`.
The exact 320 request bodies were fixed before dispatch; no post-hoc selection
or model/rubric/token-cap change is introduced. See the
[protocol](../../../docs/v15_5/DIAGNOSTIC_CONTINUATION_01.md),
[seal](CONTINUATION_SEAL.json), [prelaunch checks](PRELAUNCH_VALIDATION.json), and
[execution handoff](EXECUTION_HANDOFF.md).

Before this continuation, the 544 planned Mistral study/repeat coordinates had
219 valid diagnoses (188 main and 31 repeats), one invalid repeat, four unknown
transport outcomes and 320 never dispatched. All 544 OpenAI study/repeat calls
remain undispatched. Those prior results are a historical snapshot, not current
live counts. New live outcomes are retained under `mistral/study/calls/`.

After a terminal receipt, the additive offline analyzer will overlay only the
formerly undispatched coordinates in a new combined analysis. Even if every new
call is valid, main coverage can reach only **508/512**, not 512/512. Repeat
stability remains the original 25 equal / six differing / one invalid pairs out
of 32, and cross-provider status remains `INCOMPLETE_OR_CALIBRATION_BLOCKED`.
Neither a complete dispatch grid nor a favorable diagnosis repairs old strict
scores or establishes a learner-quality/non-regression claim.

All 274 selected local tests passed; Ruff and original cue replay passed with
the old FAIL retained. These are local mechanical checks, not CI or scientific
qualification. The additional-request conservative undiscounted upper bound is
**$24.13401720** under the frozen plan's rates. This is not an invoice; actual
charges, including original timeout calls, remain unknown.

The existing heartbeat follows this process through offline verification, an
English terminal report and branch-only publication. It will not start new API
calls. Another transport failure or process loss requires a new recovery
decision; no implicit resume, PR, merge, or learner experiment is authorized.
