# Native B parity boundary

`B_native_gradacc1_vs_cpu_guard/` preserves the completed one-microbatch native
diagnostic and the CPU-side terminal guard that correctly rejected it as an
offload comparison. `B_native_gradacc2_oom/` preserves the matched
multi-microbatch native OOM evidence. Together they explain why the formal B
CPU-spill run and same-spill resume are verified while native B equivalence is
not.

These artifacts are negative engineering evidence. They are not a parity PASS
and do not contain a loadable model.
