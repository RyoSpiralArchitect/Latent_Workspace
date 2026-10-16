"""Simplest planted memory at real width: one memory token carries +/- direction = answer."""
import sys, time
sys.path.insert(0, "src")
import torch
from latent_workspace import composition, training
torch.set_num_threads(8); torch.use_deterministic_algorithms(True)
H = 4096
UPDATES, LR, VARIANT, STRENGTH = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3], float(sys.argv[4])
g = torch.Generator().manual_seed(7)
direction = torch.randn(H, generator=g)
pairs = 384  # 256 train worlds x ... use pairs as worlds with 1 question
qs = torch.randn(pairs * 5, H, generator=g).to(torch.bfloat16)
qo = torch.arange(0, pairs * 5 + 1, 5)
first = torch.randint(0, 2, (pairs,), generator=g)
labels = torch.stack([first, 1 - first], 1).flatten()  # rows (pair, side)
mem = torch.randn(pairs * 2 * 26, H, generator=g)
for r in range(pairs * 2):
    mem[r * 26 + 13] += STRENGTH * (2 * labels[r] - 1) * direction
mo = torch.arange(0, pairs * 2 * 26 + 1, 26)
def bank(lo, hi):
    rows = torch.arange(2 * lo, 2 * hi)
    return training.FeatureBank(qs, qo, torch.zeros(len(rows), 2), labels[rows], rows // 2, segments=rows // 2).with_memory((mem.to(torch.bfloat16), mo, rows))
train, held = bank(0, 256), bank(256, 384)
route = composition.DeliberationRoute(H, 32768, (1476, 5849), steps=4, seed=1)
if "open" in VARIANT:
    with torch.no_grad():
        route.lattice.attention.out.weight.copy_(0.02 * torch.randn(route.lattice.attention.out.weight.shape, generator=g))
config = training.TrainConfig(seed=1, updates=UPDATES, batch_size=32, learning_rate=LR, weight_decay=0.01, max_grad_norm=1.0, workspace_loss_weight=0.0, loss_tokens_per_row=0, loss_tokens_per_batch=0, spectral_every=1)
opt = training.optimizer_for(training.trainable(route), LR, 0.01)
t = time.time(); log = []
for step in range(1, UPDATES + 1):
    r = training.update(route, None, opt, train, config, step)
    if step % (UPDATES // 4) == 0:
        a = training.evaluate(route, held)
        log.append((step, round(r["task_loss"], 3), round(float((a.argmax(1) == held.targets).float().mean()), 3)))
print(f"direct strength={STRENGTH} variant={VARIANT} lr={LR} updates={UPDATES} {time.time()-t:.0f}s", log, flush=True)
