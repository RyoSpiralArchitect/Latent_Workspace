"""Dev check (not evidence): can a learned logit map read answers from V19's read output?
A1's train-split features only: fit on worlds 0-191 (both sides), read flips on 192-255."""
import gzip, json, sys
import torch
from safetensors.torch import load_file

torch.set_num_threads(8)
folder = sys.argv[1]
f = load_file(f"{folder}/FEATURES_train.safetensors")
rows = json.loads(gzip.open(f"{folder}/ROWS_train.json.gz").read())
labels = torch.tensor([r["labels"] for r in rows]).view(256, 8, 2)
affected = torch.tensor([r["affected"] for r in rows]).view(256, 8)
for route in ("interaction", "common", "delta"):
    v = f["common"] + f["interaction"] if route == "delta" else f[route]   # [256, 8, 5, 4096]
    x = torch.cat([v[:, :, 0], v[:, :, 1]], 1)  # intact rows then twin rows: [256, 16, 4096]
    y = torch.cat([labels[:, :, 0], labels[:, :, 1]], 1).float()
    tr, te = slice(0, 192), slice(192, 256)
    xs = x[tr].reshape(-1, 4096).double()
    mu, sd = xs.mean(0), xs.std(0).clamp_min(1e-8)
    for l2 in (1e-3, 1e-1):
        w = torch.zeros(4096, dtype=torch.float64, requires_grad=True)
        b = torch.zeros(1, dtype=torch.float64, requires_grad=True)
        opt = torch.optim.LBFGS([w, b], lr=1.0, max_iter=300, line_search_fn="strong_wolfe")
        X, Y = (xs - mu) / sd, y[tr].reshape(-1).double()
        def closure():
            opt.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(X @ w + b, Y) + l2 * w.square().sum()
            loss.backward()
            return loss
        opt.step(closure)
        with torch.no_grad():
            def predict(c):
                z = ((v[te][:, :, c].reshape(-1, 4096).double() - mu) / sd) @ w + b
                return (z > 0).view(64, 8)
            pi, pt = predict(0), predict(1)
            li, lt = labels[te][:, :, 0].bool(), labels[te][:, :, 1].bool()
            aff = affected[te]
            flips = int(((pi == li) & (pt == lt) & aff).sum())
            # random_intact (condition 4) for both sides gives the chance control (V19-style random pair)
            pr = predict(4)
            chance = int(((pr == li) & (pr == lt) & aff).sum())
            acc_i, acc_t = float((pi == li).float().mean()), float((pt == lt).float().mean())
            train_acc = float((((X @ w + b) > 0).double() == Y).double().mean())
        print(json.dumps(dict(route=route, l2=l2, train_acc=round(train_acc, 3), held_acc_intact=round(acc_i, 3), held_acc_twin=round(acc_t, 3), held_flips=flips, affected=int(aff.sum()), chance_flips=chance)))
