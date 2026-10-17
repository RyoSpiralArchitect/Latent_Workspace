# docs/v20

Two versions share this folder (Ryō, 2026-10-16).

- **V19.5**, between V19's [closeout](../v19/CLOSEOUT.md) and V20: the
  [scope](SCOPE.md) and its square, the
  [D1 Deliberation pilot](DELIBERATION_PILOT.md), the
  [A1 Availability ladder](A1_LADDER.md), and the
  [architecture](../ARCHITECTURE.md) with the `latent_workspace` engine. These
  documents, their plans, scripts, receipts and status strings keep the `v20`
  names under which they were frozen and sealed.
- **V20** is A2: the flip through v4's logit route, on the engine. It starts
  from what A1 and V19 point at: content reached the workspace read output but
  barely moved the answer.
  - [Power checks](../../provenance/pilots/v20_a2_flip_20261016/DEV_POWER_CHECKS.md)
    stopped the first design before launch. The frozen host reads a
    separately encoded memory only from shallow cuts (0–4).
  - The [depth ladder](A2_DEPTH_LADDER.md) seals that finding: memory
    written into the host at cuts 0, 4, 8 and 16, with and without v4's
    route. [Results](../../provenance/pilots/v20_a2_depth_ladder_20261016/README.md):
    read depth host 0, route 4. The first design's draft runner and plan were never frozen. They
    left the tree when the depth ladder replaced them, and git history keeps
    them (commit `1fe66c8`).
  - **A3** (development) tried Ryō's option 3, a compact memory written into
    the lower layers. Eight soft tokens at cut 0 carry an unseen world's facts
    well enough for the host to reproduce them, but no reader tried could
    answer from them ([checks](../../provenance/pilots/v20_a3_shallow_writer_20261016/DEV_CHECKS.md)).
  - **A4** refines the low-layer version the ladder supports, following Ryō's
    fallback: the [content-gated cut-4 route](A4_GATED_ROUTE.md), trained to
    leave answers alone when the memory does not answer the question
    ([development](../../provenance/pilots/v20_a4_gated_route_20261017/DEV_CHECKS.md)).
    [Results](../../provenance/pilots/v20_a4_gated_route_20261017/README.md):
    `NOT_ESTABLISHED` by the all-seeds rule (seeds 2 and 3 content, seed 1
    scored after a late training disturbance). Gating closed the random-memory
    weak point in every seed.
