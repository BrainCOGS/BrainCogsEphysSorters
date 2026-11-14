"""The container client that runs each command with `apptainer exec`.

SpikeInterface's own client starts an Apptainer instance (a daemon) and runs the commands in
it. On spock the instance was killed (SIGTERM, return code -15) seconds into the sort on some
nodes; `apptainer exec` keeps every process a child of the slurm job.
"""

import subprocess
import sys
import types

import pytest

import u19_sorting.apptainer_exec as ae

VOLUMES = {
    "/raw/run_g0_imec0": {"bind": "/raw/run_g0_imec0", "mode": "ro"},
    "/processed/job_id_7/kilosort2_output_si_work": {
        "bind": "/processed/job_id_7/kilosort2_output_si_work",
        "mode": "rw",
    },
}
IMAGE = "/sif/kilosort2.sif"


@pytest.fixture
def popens(monkeypatch):
    """Record the commands the client starts; they print `lines` and exit with `returncode`."""

    calls = types.SimpleNamespace(
        commands=[], kwargs=[], lines=["a\n", "b\n"], returncode=0
    )

    class Popen:
        def __init__(self, command, **kwargs):
            calls.commands.append(command)
            calls.kwargs.append(kwargs)
            self.stdout = iter(calls.lines)
            self.returncode = None

        def wait(self):
            self.returncode = calls.returncode
            return self.returncode

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ae.subprocess, "Popen", Popen)
    monkeypatch.setattr(ae.os.path, "isfile", lambda path: True)
    return calls


def client(gpu=True, image=IMAGE):
    extra = {"container_requires_gpu": True} if gpu else {}
    return ae.ApptainerExecClient("singularity", image, VOLUMES, "/pybase", extra)


def test_command_runs_in_the_image_with_the_binds(popens):
    client().run_command(["python", "/processed/job_id_7/script.py"])

    (command,) = popens.commands
    assert command == [
        "apptainer",
        "exec",
        "--cleanenv",
        "--env",
        "PYTHONUSERBASE=/pybase",
        "--bind",
        (
            "/raw/run_g0_imec0:/raw/run_g0_imec0:ro,"
            "/processed/job_id_7/kilosort2_output_si_work:"
            "/processed/job_id_7/kilosort2_output_si_work"
        ),
        "--nv",
        IMAGE,
        "python",
        "/processed/job_id_7/script.py",
    ]
    assert popens.kwargs[0]["stderr"] == subprocess.STDOUT


def test_no_gpu_no_nv(popens):
    client(gpu=False).run_command(["true"])
    assert "--nv" not in popens.commands[0]


def test_string_command_is_split(popens):
    client().run_command("pip install --user --upgrade pip")
    assert popens.commands[0][-5:] == ["pip", "install", "--user", "--upgrade", "pip"]


def test_output_is_printed_and_returned(popens, capsys):
    assert client().run_command(["x"]) == "a\nb\n"
    assert capsys.readouterr().out == "a\nb\n"


def test_failure_is_in_the_output(popens):
    popens.returncode = -15
    out = client().run_command(["x"])
    assert out.endswith("ERROR: apptainer exec exited with code -15\n")


def test_start_and_stop_run_nothing(popens):
    c = client()
    c.start()
    c.stop()
    assert popens.commands == []


def test_only_singularity_mode():
    with pytest.raises(ValueError, match="singularity"):
        ae.ApptainerExecClient("docker", IMAGE, VOLUMES, "/pybase", {})


def test_image_must_be_a_local_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        ae.ApptainerExecClient(
            "singularity", "spikeinterface/ks2:latest", VOLUMES, "/p", {}
        )
    image = tmp_path / "ks2.sif"
    image.write_bytes(b"SIF")
    assert ae.ApptainerExecClient(
        "singularity", str(image), VOLUMES, "/p", {}
    ).image == str(image)


def test_context_manager_swaps_spikeinterface_client(monkeypatch):
    original = object()
    runsorter = types.ModuleType("spikeinterface.sorters.runsorter")
    runsorter.ContainerClient = original
    monkeypatch.setitem(sys.modules, "spikeinterface.sorters.runsorter", runsorter)

    with ae.exec_instead_of_instances():
        assert runsorter.ContainerClient is ae.ApptainerExecClient
    assert runsorter.ContainerClient is original


def test_context_manager_restores_after_an_error(monkeypatch):
    original = object()
    runsorter = types.ModuleType("spikeinterface.sorters.runsorter")
    runsorter.ContainerClient = original
    monkeypatch.setitem(sys.modules, "spikeinterface.sorters.runsorter", runsorter)

    with pytest.raises(RuntimeError), ae.exec_instead_of_instances():
        raise RuntimeError("sort failed")
    assert runsorter.ContainerClient is original
