# O1 data pilot — retained failed attempt

The first sealed data-only probe ran once on 2026-11-14 from source
`10a1740e21274f36dd31dccc0f943f9e4521a876` in the isolated Furnace
worktree `latent-v24-order-control01-20261114`. The target output path was
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-order-control01-20261114`.
It exited **1** before output-directory creation; a read-only check confirmed
that path remains absent. No model, GPU, training update, save, judge, source
download or weight deletion was invoked. `CUDA_VISIBLE_DEVICES` was empty,
`OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, and the process ran at nice +10 while
another project's CUDA job remained untouched.

The terminal exception was `ValueError: Train-only schedule` from
`scripts/probe_v24_order_control.py:100`. The frozen 538-row schedule includes
instruction/prose/code preservation rows. The probe incorrectly required
every scheduled key to appear in its *synthetic-only* projection, although the
historical sealed private route arrays correctly contain those preservation
rows. This is an audit implementation error, not a tokenizer mismatch or a
scientific outcome. It does not relax the historical 21,112-target reference.

The source, input bundle and absence of a terminal receipt are retained as
the O1 negative execution record. The subsequent fix uses the sealed private
rows unchanged for preservation, checks their route targets, and has a new
regression test. It must run only from a **new committed source** in a new
exclusive O2 output; O1 is never resumed or overwritten.
