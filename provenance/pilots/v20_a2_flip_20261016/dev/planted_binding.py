"""Planted deferred-memory task at real width with D1's training settings (calibration)."""
import sys
import time

sys.path.insert(0, "src")
import torch

from latent_workspace import availability, composition, training

torch.set_num_threads(8)
torch.use_deterministic_algorithms(True)
H, ENTITIES, NOISE, BIND = 4096, 12, float(sys.argv[1]) if len(sys.argv) > 1 else 0.5, 0.7
UPDATES = int(sys.argv[2]) if len(sys.argv) > 2 else 512
LR = float(sys.argv[3]) if len(sys.argv) > 3 else 3e-4
VARIANT = sys.argv[4] if len(sys.argv) > 4 else "zero"
g = torch.Generator().manual_seed(2026)
E = torch.randn(ENTITIES, H, generator=g)
R = torch.randn(H, H, generator=g) / H**0.5
F = torch.randn(6, H, generator=g)  # fillers: header, is, ranked, above, period, cue/answer


def noisy(v):
    return v + NOISE * torch.randn(v.shape, generator=g)


def facts(order):
    pairs = [(order[i], order[i + 1]) for i in range(5)]
    return sorted(pairs)  # canonical order, independent of rank position


def memory_tokens(order):
    toks = [noisy(F[0])]
    for a, b in facts(order):
        toks += [noisy(E[a]), noisy(F[1]), noisy(F[2]), noisy(F[3]), noisy(E[b] + BIND * (R @ E[a]))]
    return torch.stack(toks)


def question_tokens(x, y):
    return torch.stack([noisy(F[5]), noisy(E[x]), noisy(F[3]), noisy(E[y] + BIND * (R @ E[x])), noisy(F[5])])


def world():
    order = torch.randperm(ENTITIES, generator=g)[:6].tolist()
    k = int(torch.randint(0, 5, (1,), generator=g))
    twin = order.copy()
    twin[k], twin[k + 1] = twin[k + 1], twin[k]
    rank = {e: i for i, e in enumerate(order)}
    others = [i for i in range(5) if i not in (k - 1, k, k + 1)] or [0]
    j = others[0]
    pairs = [(order[k], order[k + 1]), (order[j], order[j + 1])]
    far = [(order[0], order[5]), (order[1], order[4])]
    queries = []
    for a, b in pairs + far:
        queries += [(a, b), (b, a)]
    labels = []
    for a, b in queries:
        intact = int(rank[a] < rank[b])
        trank = {e: i for i, e in enumerate(twin)}
        labels.append([intact, int(trank[a] < trank[b])])
    return order, twin, queries, labels


def build(worlds):
    q_states, q_off, m_states, m_off, rows = [], [0], [], [0], []
    for w, (order, twin, queries, labels) in enumerate(worlds):
        for q, ((a, b), lab) in enumerate(zip(queries, labels)):
            t = question_tokens(a, b)
            q_states.append(t)
            q_off.append(q_off[-1] + t.shape[0])
            rows.append(dict(world=w, query=q, labels=lab, affected=lab[0] != lab[1]))
        for o in (order, twin):
            t = memory_tokens(o)
            m_states.append(t)
            m_off.append(m_off[-1] + t.shape[0])
    return (torch.cat(q_states).to(torch.bfloat16), torch.tensor(q_off),
            torch.cat(m_states).to(torch.bfloat16), torch.tensor(m_off), rows)


def own_bank(data):
    qs, qo, ms, mo, rows = data
    seg, tgt, wor, mem = [], [], [], []
    per = 8
    for w in range(len(rows) // per):
        for side in (0, 1):
            for q in range(per):
                i = w * per + q
                seg.append(i); tgt.append(rows[i]["labels"][side]); wor.append(w); mem.append(2 * w + side)
    seg = torch.tensor(seg)
    return training.FeatureBank(qs, qo, torch.zeros(len(seg), 2), torch.tensor(tgt), torch.tensor(wor), segments=seg).with_memory((ms, mo, torch.tensor(mem)))


def cond_bank(data, side, random=None):
    qs, qo, ms, mo, rows = data
    seg = torch.arange(len(rows))
    bank = training.FeatureBank(qs, qo, torch.zeros(len(rows), 2), torch.tensor([r["labels"][0] for r in rows]), torch.tensor([r["world"] for r in rows]), segments=seg)
    if random is not None:
        return bank.with_memory(random(side))
    return bank.with_memory((ms, mo, torch.tensor([2 * r["world"] + side for r in rows])))


train = build([world() for _ in range(256)])
final = build([world() for _ in range(128)])
qs, qo, ms, mo, rows = final
rg_states, rg_off = [], [0]
for w in range(128):
    gen = torch.Generator().manual_seed(470016 + w)
    for side in (0, 1):
        s = 2 * w + side
        v = ms[mo[s]:mo[s + 1]].float()
        rg_states.append(availability.norm_matched_random(v[None], torch.ones(1, v.shape[0], dtype=torch.long), gen)[0])
        rg_off.append(rg_off[-1] + v.shape[0])
rg = (torch.cat(rg_states), torch.tensor(rg_off))
random = lambda side: (rg[0], rg[1], torch.tensor([2 * r["world"] + side for r in rows]))
rule = dict(chance_control="random_pair", sign_test_alpha=0.001, minimum_actual_flips=26, minimum_flip_margin_over_random=20)
for seed in (1, 2):
    route = composition.DeliberationRoute(H, 32768, (1476, 5849), steps=4, seed=seed)
    gen = torch.Generator().manual_seed(1000 + seed)
    lat = route.lattice
    with torch.no_grad():
        if "open" in VARIANT:
            lat.attention.out.weight.copy_(0.02 * torch.randn(lat.attention.out.weight.shape, generator=gen))
        if "ff" in VARIANT:
            lat.candidate_out.weight.copy_(0.02 * torch.randn(lat.candidate_out.weight.shape, generator=gen))
        if "scale" in VARIANT:
            lat.attention_step_scales.fill_(2.0)
        if "tied" in VARIANT:
            W = lat.attention.workspace_dim
            lat.attention.qkv.weight[W:2 * W].copy_(lat.attention.qkv.weight[:W])
    config = training.TrainConfig(seed=seed, updates=UPDATES, batch_size=32, learning_rate=LR, weight_decay=0.01, max_grad_norm=1.0, workspace_loss_weight=0.0, loss_tokens_per_row=0, loss_tokens_per_batch=0, spectral_every=1)
    named = training.trainable(route)
    opt = training.optimizer_for(named, LR, 0.01)
    bank = own_bank(train)
    start = time.time()
    losses = []
    for step in range(1, UPDATES + 1):
        r = training.update(route, None, opt, bank, config, step)
        losses.append(r["task_loss"])
    elapsed = time.time() - start
    scores = {
        "intact": training.evaluate(route, cond_bank(final, 0)).tolist(),
        "twin": training.evaluate(route, cond_bank(final, 1)).tolist(),
        "random_intact": training.evaluate(route, cond_bank(final, 0, random)).tolist(),
        "random_twin": training.evaluate(route, cond_bank(final, 1, random)).tolist(),
    }
    contrasts = []
    for factor in ("actual", "random_pair"):
        left, right = availability.FACTORS[factor]
        for i, row in enumerate(rows):
            contrasts.append(availability.contrast(row["world"], row["query"], factor, row["labels"], availability.choice(scores[left][i]), availability.choice(scores[right][i])))
    d = availability.diagnose(contrasts, rule)
    acc = sum((s[1] > s[0]) == bool(r["labels"][0]) for s, r in zip(scores["intact"], rows)) / len(rows)
    print(f"variant={VARIANT} noise={NOISE} updates={UPDATES} lr={LR} seed={seed} {elapsed:.0f}s loss {sum(losses[:32])/32:.3f}->{sum(losses[-32:])/32:.3f} acc_intact={acc:.3f} flips={d['flips']} sign={d['world_sign']} p={d['sign_test_p']:.2g} verdict={d['verdict']}", flush=True)
