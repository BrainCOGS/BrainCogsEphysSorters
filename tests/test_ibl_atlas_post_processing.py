"""Which python the IBL atlas step runs with, and what happens when it fails.

From the repository's uv environment (.venv) the step runs with that same python (ibllib is
in uv.lock) and a failure stops the job. Anywhere else (the conda environment) it runs
through prepare_ephys_data_ibl_script.sh and the conda env iblenv, exactly as before.
"""

import pathlib
import subprocess
import sys

import pytest

import u19_sorting.postprocess_wrappers as ppw
from u19_sorting import config

RAW = pathlib.Path("/raw/run_g0/run_g0_imec0")


@pytest.fixture
def processed(tmp_path):
    return tmp_path / "processed" / "job_id_7"


@pytest.fixture
def runs(monkeypatch):
    """Record subprocess.run calls; runs.returncode is what they exit with"""

    class Runs:
        def __init__(self):
            self.commands = []
            self.kwargs = []
            self.returncode = 0

    runs = Runs()

    def run(command, **kwargs):
        runs.commands.append(command)
        runs.kwargs.append(kwargs)
        return subprocess.CompletedProcess(command, runs.returncode, b"out", b"err")

    monkeypatch.setattr(ppw.subprocess, "run", run)
    return runs


@pytest.fixture
def in_venv(monkeypatch, tmp_path):
    """Pretend the job runs from <repository_dir>/.venv"""
    repo = tmp_path / "BrainCogsEphysSorters"
    (repo / ".venv" / "bin").mkdir(parents=True)
    monkeypatch.setattr(config, "repository_dir", str(repo))
    monkeypatch.setattr(sys, "prefix", str(repo / ".venv"))
    monkeypatch.setattr(sys, "executable", str(repo / ".venv" / "bin" / "python"))
    return repo


@pytest.fixture
def in_conda(monkeypatch, tmp_path):
    repo = tmp_path / "BrainCogsEphysSorters"
    repo.mkdir()
    monkeypatch.setattr(config, "repository_dir", str(repo))
    monkeypatch.setattr(sys, "prefix", "/conda/envs/u19_pipeline_python_env3")
    monkeypatch.setattr(
        sys, "executable", "/conda/envs/u19_pipeline_python_env3/bin/python"
    )


def run_step(processed):
    ppw.ibl_atlas_post_processing.run_ibl_atlas_post_processing(
        RAW, processed, processed / "kilosort4_output"
    )


def test_uv_env_is_the_repository_venv(in_venv):
    assert ppw.ibl_atlas_python() == sys.executable


def test_conda_env_has_no_ibl_python(in_conda):
    assert ppw.ibl_atlas_python() is None


def test_venv_of_another_checkout_is_not_the_uv_env(in_venv, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "other" / ".venv"))
    assert ppw.ibl_atlas_python() is None


def test_conda_command_is_unchanged(in_conda, runs, processed):
    run_step(processed)

    (command,) = runs.commands
    assert command == (
        "bash "
        + config.ibl_atlas_shell_script.as_posix()
        + " "
        + config.ibl_atlas_script.as_posix()
        + " /raw/run_g0/run_g0_imec0 "
        + (processed / "kilosort4_output").as_posix()
        + " "
        + (processed / "ibl_data").as_posix()
    )
    assert (processed / "ibl_data").is_dir()
    assert runs.kwargs[0] == {"shell": True, "capture_output": True}


def test_uv_runs_the_script_with_the_job_python(in_venv, runs, processed):
    run_step(processed)

    (command,) = runs.commands
    assert command == [
        sys.executable,
        "-u",
        config.ibl_atlas_script.as_posix(),
        "/raw/run_g0/run_g0_imec0",
        (processed / "kilosort4_output").as_posix(),
        (processed / "ibl_data").as_posix(),
    ]
    assert (processed / "ibl_data").is_dir()
    # no shell, no conda; the output goes to the job log as it comes
    assert "shell" not in runs.kwargs[0]
    assert "capture_output" not in runs.kwargs[0]
    assert runs.kwargs[0]["cwd"] == config.ibl_post_processing_dir.as_posix()


def test_uv_failure_stops_the_job(in_venv, runs, processed):
    runs.returncode = 1

    with pytest.raises(RuntimeError, match="IBL atlas step failed .*exit code 1"):
        run_step(processed)
