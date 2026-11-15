"""A native Kilosort 2 / 3 job must not wait for processes MATLAB leaves behind.

MATLAB R2024a starts a MathWorksServiceHost daemon that outlives it and keeps MATLAB's
stdout and stderr open. Reading them through pipes then never ends: the sort is finished,
MATLAB is gone, and the job sits there until slurm's time limit (spock job 7472123).
"""

import subprocess
import time

import pytest

from u19_sorting import sorter_wrappers

# Prints, leaves a child holding stdout and stderr for a minute, and exits at once.
LEAVES_A_CHILD = "echo sorted; echo warned >&2; sleep 60 & exit {rc}"


@pytest.fixture
def reap_children():
    yield
    subprocess.run("pkill -P $$ -x sleep", shell=True, check=False)


def test_run_matlab_returns_when_matlab_exits(reap_children):
    start = time.monotonic()
    returncode, stdout, stderr = sorter_wrappers.run_matlab(LEAVES_A_CHILD.format(rc=0))

    assert time.monotonic() - start < 20
    assert returncode == 0
    assert stdout == "sorted\n"
    assert stderr == "warned\n"


def test_run_matlab_reports_a_failure(reap_children):
    returncode, _, stderr = sorter_wrappers.run_matlab(LEAVES_A_CHILD.format(rc=3))

    assert returncode == 3
    assert stderr == "warned\n"


@pytest.mark.parametrize("sorter", ["Kilosort2", "Kilosort3"])
def test_native_kilosort_raises_what_matlab_wrote(sorter, monkeypatch, tmp_path):
    cls = getattr(sorter_wrappers, sorter)
    monkeypatch.setattr(
        cls, f"create_{sorter}_command", lambda *args: "echo broken >&2; exit 1"
    )

    with pytest.raises(Exception, match="broken"):
        getattr(cls, f"run_{sorter}")(tmp_path, tmp_path, "params.json", "chanmap.mat")
