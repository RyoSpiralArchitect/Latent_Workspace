import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "provenance/engineering/v24_recruitment_ft02_20261023"


def test_external_launchers_only_change_identity_not_the_runner_calls():
    for phase in ("checks", "training"):
        path = HERE / f"launch_{phase}.sh"
        subprocess.run(["bash", "-n", str(path)], check=True)
        text = path.read_text()
        old = (ROOT / f"scripts/launch_v24_recruitment_{phase}.sh").read_text()
        marker = "env CUDA_VISIBLE_DEVICES=" if phase == "checks" else '"$task_python" -I '
        assert text[text.index(marker) :] == old[old.index(marker) :]
        assert 'git rev-parse HEAD)" = d43382833f6dc85787720bda80aec511c66f58be' in text
        assert (
            "task_output=/home/ryospiralarchitect/spiralreality/SpiralReality/latent-v24-recruitment-ft02-20261023"
            in text
        )
        assert (
            "task_source=/home/ryospiralarchitect/spiralreality/SpiralReality/worktrees/latent-v24-recruitment-ft01-20261023"
            in text
        )
        assert "rm " not in text and "unlink" not in text
    assert "dispatch-training" not in (HERE / "launch_checks.sh").read_text()
