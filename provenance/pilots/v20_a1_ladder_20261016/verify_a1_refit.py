"""Run the sealed A1 verifier with --refit under the probe role's arithmetic.

The probe role hid the GPU, used 8 intra-op threads and deterministic
algorithms; refitting under the same settings is what makes an exact match
meaningful. Usage: python -B verify_a1_refit.py <sealed checkout> <verifier args...>
"""
import os
import runpy
import sys
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch  # noqa: E402

torch.set_num_threads(8)
torch.use_deterministic_algorithms(True)
assert not torch.cuda.is_available()
checkout = Path(sys.argv[1]).resolve()
script = checkout / "scripts/verify_v20_a1_ladder.py"
sys.argv = [str(script), *sys.argv[2:]]
runpy.run_path(str(script), run_name="__main__")
