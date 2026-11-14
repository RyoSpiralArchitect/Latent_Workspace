# V24 O2 order-control data pilot — completed, not training

The source-backed [O2 receipt](RESULTS.json) and [terminal file manifest](FINISHED.json)
were recovered from Furnace on 2026-11-14. Original source:
`e67590fccc742cf7d9e0223a206036ede6fc189b`; original frozen bank source:
`92d078880176d1a3f6fd1aa16adc9d2c19050b85`; input manifest SHA-256:
`6f1869b47e2e592d9ffdb7fda21812d08a1baad9d9d7ec148067171e026cc854`.
The output is
`/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-order-control02-20261114`
on Furnace and this directory on the Mac. Result SHA-256 is
`303310085492e5d0ad59d01217c4dc2ed9ee5877611bbee2bba42ace02affe5b`.
The local result bytes and the terminal manifest were independently checked
after transfer. No previous output was overwritten.

| Check | Observed O2 result |
| --- | ---: |
| Original answer-first projection versus frozen private route rows | exact, both routes |
| Same source keys, query prefix and external M in steps-first projection | yes |
| Changed present reasoning rows per route (train + dev) | 864 |
| Frozen training schedule | 32 windows, 538 row occurrences |
| Answer-first supervised target tokens | 21,112 |
| Steps-first supervised target tokens | 21,175 |
| Added tokens | **63**: arithmetic 32, register trace 31, stable filter 0 |
| Scheduled occurrences whose target ID sequence changed | 93 |
| Pinned-runtime CPU regressions | 30/30 PASS |
| Local relevant tests after correction | 114/114 PASS |
| 7B/model forwards, updates, saves, judge calls, deletions | **0** each |

The pilot used the original cached tokenizer and disabled CUDA visibility; a
separate GPU job was not interrupted or used. The earlier
[O1 audit-only failure](../v24_order_control01_20261114/FAILED.md) remains a
distinct immutable source/output attempt. O2 fixed only its preservation-row
lookup and added a regression; it did not change the frozen data, target
order factor, expected token counts or old quality gate.

This is **data projection qualification, not an O-effect or a model-quality
result**. The +63 tokens mean historical answer-first FT and a future
steps-first FT would not have exactly matched supervised-token counts under
the same row schedule. [The protocol](../../../docs/v24/ORDER_CONTROL_01.md)
requires this to be resolved or retained as an explicit confound before any
full 7B comparison. The Furnace root filesystem had 19.803 GiB free at the
initial inventory sample and 17.038 GiB after both isolated source checkouts,
below the unchanged 50-GiB FT floor. No full update was admitted.
[Capacity candidates](../../inventory/v24_order_control_capacity_20261114/README.md)
are a read-only shortlist, not a deletion approval.

The prior **FAIL / winner:none / non_regression NOT_ESTABLISHED** ceiling is
unchanged. No PR, merge or checkpoint retirement is implied by this pilot.
