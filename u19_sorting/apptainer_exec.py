"""Run SpikeInterface's container sorters with `apptainer exec` instead of an instance.

SpikeInterface's ContainerClient (singularity mode) starts an Apptainer instance, a daemon,
and runs each command in it with `apptainer exec instance://...`. On spock (Apptainer 1.5.5)
the instance was killed with SIGTERM a few seconds into the sort on some nodes (the command
returned -15, then "no instance found"), while `apptainer exec` of the same image worked on
every node. ApptainerExecClient has the same interface and runs every command with
`apptainer exec <image>`, so the sorter stays a child process of the slurm job.
"""

import contextlib
import importlib
import os
import shlex
import subprocess


class ApptainerExecClient:
    """Drop-in for spikeinterface.sorters.container_tools.ContainerClient, singularity mode."""

    def __init__(self, mode, container_image, volumes, py_user_base, extra_kwargs):
        if mode != "singularity":
            raise ValueError(
                f"only singularity mode runs with apptainer exec, not {mode}"
            )
        if not os.path.isfile(container_image):
            # The registry hands over the cached .sif; nothing is pulled on a compute node.
            raise FileNotFoundError(
                f"container image {container_image} is not a local file"
            )

        self.image = str(container_image)
        self.py_user_base = py_user_base
        binds = []
        for source, volume in volumes.items():
            bind = f"{source}:{volume['bind']}"
            if volume.get("mode") == "ro":
                bind += ":ro"
            binds.append(bind)
        self.options = ["--bind", ",".join(binds)]
        if extra_kwargs.get("container_requires_gpu"):
            self.options.append("--nv")

    def start(self):
        """Nothing to start: each command runs in a container of its own."""

    def stop(self):
        """Nothing to stop."""

    def run_command(self, command):
        """Run command in the image; print its output as it comes and return it."""

        if isinstance(command, str):
            command = shlex.split(command)
        full = [
            "apptainer",
            "exec",
            "--cleanenv",
            "--env",
            f"PYTHONUSERBASE={self.py_user_base}",
            *self.options,
            self.image,
            *command,
        ]
        output = []
        with subprocess.Popen(
            full,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        ) as p:
            for line in p.stdout:
                print(line, end="", flush=True)
                output.append(line)
            returncode = p.wait()
        if returncode:
            output.append(f"ERROR: apptainer exec exited with code {returncode}\n")
        return "".join(output)


@contextlib.contextmanager
def exec_instead_of_instances():
    """Within the block, SpikeInterface's run_sorter uses ApptainerExecClient."""

    runsorter = importlib.import_module("spikeinterface.sorters.runsorter")
    original = runsorter.ContainerClient
    runsorter.ContainerClient = ApptainerExecClient
    try:
        yield
    finally:
        runsorter.ContainerClient = original
