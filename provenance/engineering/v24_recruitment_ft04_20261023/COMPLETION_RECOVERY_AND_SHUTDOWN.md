# FT04 completion, recovery and graceful-poweroff handoff

## Terminal update — 2026-10-23 19:32 JST

Both arms completed 32/32 updates; full offline recovery verification and both
remote final-body hashes passed. See [completed results](COMPLETION_RESULTS.md)
and [shutdown handoff](SHUTDOWN_HANDOFF.json). No poweroff command was issued:
OS authentication is still required, and SMB transfer quiescence remains
unverified. No further training, evaluation, retry or deletion is authorized
by this handoff. The heartbeat was deleted at 19:34:59 JST after its terminal handoff;
older pause/no-monitor descriptions below are historical.

## New user authority (2026-10-23 JST)

Ryō initially thought training had ended and requested result recovery followed
by safe Furnace shutdown for a physical move. Inspection showed inline training
was still running with no scientific checkpoint yet. Ryō then explicitly chose
**wait for completion, recover results, then shut down** over interruption and
loss of unsaved state. This supersedes the earlier no-monitor handoff for this
one completion workflow only. It does not authorize retries, new training or
evaluation, checkpoint deletion, changes to system authentication, or stopping
unrelated active jobs.

At 17:39 JST inline was processing `step21:row6:before`, after 20 completed
updates; workspace was not yet started. PID 21717 was the inline child. The
existing dispatcher remains responsible for inline then workspace, 32 updates
per arm. Do not start either role again. All previous failures remain unchanged.

## Exact identities

- Local checkout: `/Users/ryohiga/SpiralReality/worktrees/latent-workspace-full-ft-v1`.
- Branch: `SpiralReality/v24-readout-improvement`.
- Remote: `https://github.com/RyoSpiralArchitect/Latent_Workspace.git`.
- Last published result/progress head: `cfe49b0bfd57dc8065f2506dbf7eae83e36a808a`.
- Frozen execution source: `4b69c6b0d604f4947b7075e40430b9b8f113f4ad`, 856 sealed files.
- Remote source: `/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v24-recruitment-ft04-20261023`.
- Remote output: `/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft04-20261023`.
- Tmux: `ltws-v24-recruitment-training04-20261023`.
- Observed boot ID: `66f9404a-e062-436f-82ce-0fc459a36143`.
- Transport: existing `spiral` wrapper and pinned peer; do not reconstruct SSH or change host addressing.

## Completion and recovery gate

While running, inspect existing processes and receipts only. No model call,
resume, retry, source edit, weight deletion or resource-threshold change.
If either role fails or the process disappears without the expected terminal,
preserve missingness and recover available evidence, then request direction.
The selected completion path is not permission to discard an interrupted run.

Require both role `FINISHED.json` receipts, plus `training/FINISHED.json` and
`raw/FINISHED.json`, before complete-run recovery. Copy the source seal,
retirement receipt, dispatcher scripts/logs, checks, qualification, training,
and raw metadata/logs into the local `furnace/` bundle. **Do not recursively pull
the entire output root**, because `checkpoints/` contains the large tensor
bodies. Never copy an active log as a closed terminal artifact. Compare hashes
and retain literal bytes, including XML/log trailing spaces.

Run the existing offline verifier:

```sh
python3 -B scripts/verify_v24_recruitment_ft04.py provenance/engineering/v24_recruitment_ft04_20261023/furnace --phase training
```

It must verify both 32-update arms, 538 rows and 21,112 target tokens per arm,
64 scientific / 67 total updates including engineering checks, closed manifests,
source seals, original qualification/replay and resource floors. Keep old
`FAIL`, `winner:none`, and `non_regression:NOT_ESTABLISHED`. Development NLL is
descriptive, not a capability gate. Summarize completed training and NLL locally
without new generations, benchmark calls or judges. No PR, merge, external
upload or GitHub push is part of this shutdown monitor.

Independently hash the two saved final checkpoint files on Furnace and compare
their full-file SHA-256 and sizes with their closed save receipts. Do not load
the models, remove files, or replace a receipt after a mismatch. Copy the
verification report and hashes locally before poweroff.

## Weight-body disposition and storage

The Mac had about 49 GiB available; two final checkpoints are expected to total
about 54 GiB. The announced recovery scope is metadata/logs/metrics/ledgers to
the Mac, with the actual final weights retained on Furnace's SSD. This is **not
an off-host tensor backup**. Preserve original Mistral and V22/V23 final weights
as well. Do not free more space or choose an unconfirmed external/network mount
for a large transfer. If Ryō requests off-host copies, obtain a suitable named
destination and verify them before treating that expanded recovery as complete.

## Graceful shutdown gate and current authentication blocker

Read-only checks at 17:39–17:40 JST returned:

- `sudo -n -l`: exit 1, `sudo: interactive authentication is required`.
- logind `CanPowerOff`: `challenge`.
- Inhibitors: normal ModemManager/UPower sleep delays and Unattended Upgrades
  shutdown delay. These observations are not permission to bypass inhibitors.
- Old Aether/Qspace tmux panes were mostly dead; the h-wave pane was an idle
  shell with no child. There were still long-lived Python/Codex/Claude processes
  and SMB clients. Recheck their actual activity at shutdown time; do not assume
  this snapshot proves they are safe to terminate later.

Do not test a real poweroff command while training runs. After recovery and
verification, recheck all CPU/GPU jobs, transfers, login sessions and shutdown
inhibitors. If another job or active transfer could lose work, stop and ask Ryō;
never kill it to clear the machine. Flush outstanding filesystem writes with
`sync`. Only use ordinary authenticated graceful shutdown, without force,
inhibitor override or privilege-policy changes. User authorization exists,
but OS authentication is currently unavailable to this noninteractive agent.
If it remains unavailable, report **READY_FOR_SHUTDOWN_AUTH_REQUIRED** and have
Ryō authenticate in their own terminal; never request a password in chat or
claim that shutdown happened. If normal shutdown becomes available, issue it
once, preserve its acknowledgement, and distinguish accepted shutdown from
unreachable host and independently confirmed poweroff. A lost connection alone
is not proof of power loss; never alter peer addresses based on that alone.

## Completion of this follow-up

App heartbeat **`v24-ft04`**, named **V24 FT04回収と安全シャットダウン**,
was created ACTIVE in this same chat on 2026-10-23, with a ten-minute cadence.
It is distinct from the paused V15.5 judge monitor; that old monitor was not
reactivated or repurposed. Use this exact new ID when pausing the completed
follow-up. The authentication requirement remains unresolved; creation of an
automation does not grant operating-system privileges.

Use one thread heartbeat for the already-running run. Remain quiet for routine
progress. Notify Ryō in Japanese on failure, a required decision, successful
recovery with an authentication blocker, or completed shutdown. Pause that
heartbeat after a terminal handoff or a required external action so no repeated
poweroff or completed work occurs. This handoff is not a background job itself.
