import json
import os
import stat
import subprocess

import pytest

import u19_sorting.apptainer_cache as ac
import u19_sorting.sorter_registry as sr


CONTAINER = {
    "mode": "container",
    "sorter": "kilosort3",
    "image": "docker://spikeinterface/kilosort3-compiled-base:0.2.0",
    "sif": "ks3_0.2.0.sif",
    "spikeinterface": "0.104.8",
}
NATIVE = {"mode": "native", "sorter": "kilosort4", "version": "4.1.7"}


@pytest.fixture
def entry():
    return sr.parse_entry("kilosort3@0.2.0", CONTAINER)


class FakeApptainer:
    """ Stands in for subprocess.run: records calls and writes the image `apptainer build` would. """

    def __init__(self, returncode=0, write=True):
        self.calls = []
        self.returncode = returncode
        self.write = write

    def __call__(self, cmd, env=None, **kwargs):
        self.calls.append({"cmd": cmd, "env": env})
        if self.write:
            # `apptainer build [--fakeroot] <out.sif> <def>`
            with open(cmd[-2], "wb") as f:
                f.write(b"SIF")
        return subprocess.CompletedProcess(cmd, self.returncode)


# ----------------------------------------------------------------------------- definition file

def test_definition_bakes_in_pinned_spikeinterface(entry):
    text = ac.definition_file_text(entry)
    assert "Bootstrap: docker" in text
    # `From:` takes the reference without the docker:// scheme
    assert "From: spikeinterface/kilosort3-compiled-base:0.2.0" in text
    assert "docker://" not in text.split("%labels")[0]
    assert "spikeinterface==0.104.8" in text
    assert "u19.sorter_version kilosort3@0.2.0" in text


def test_definition_rejects_native_entry():
    with pytest.raises(ValueError):
        ac.definition_file_text(sr.parse_entry("kilosort4@4.1.7", NATIVE))


def test_build_command(entry, tmp_path):
    cmd = ac.build_command(tmp_path / "out.sif", tmp_path / "x.def")
    assert cmd == ["apptainer", "build", str(tmp_path / "out.sif"), str(tmp_path / "x.def")]


def test_build_command_fakeroot(entry, tmp_path):
    cmd = ac.build_command(tmp_path / "out.sif", tmp_path / "x.def", fakeroot=True)
    assert cmd[:3] == ["apptainer", "build", "--fakeroot"]


# ----------------------------------------------------------------------------- cache_entry

def test_cache_entry_builds_into_sif_dir(entry, tmp_path):
    sif_dir, cache_dir = tmp_path / "sif", tmp_path / "cache"
    runner = FakeApptainer()
    status = ac.cache_entry(entry, sif_dir=sif_dir, cache_dir=cache_dir, runner=runner)

    assert status == "built"
    final = sif_dir / CONTAINER["sif"]
    assert final.read_bytes() == b"SIF"
    # immutable once cached
    assert not (final.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    # no partial / def leftovers
    assert sorted(p.name for p in sif_dir.iterdir()) == [CONTAINER["sif"]]
    # layer cache pointed at shared storage for both apptainer and legacy singularity
    env = runner.calls[0]["env"]
    assert env["APPTAINER_CACHEDIR"] == str(cache_dir)
    assert env["SINGULARITY_CACHEDIR"] == str(cache_dir)
    assert cache_dir.is_dir()


def test_cache_entry_builds_to_partial_then_renames(entry, tmp_path):
    runner = FakeApptainer()
    ac.cache_entry(entry, sif_dir=tmp_path, cache_dir=tmp_path / "c", runner=runner)
    built_to = runner.calls[0]["cmd"][-2]
    assert built_to != str(tmp_path / CONTAINER["sif"])
    # built under the sif dir (same filesystem) so the final rename is atomic
    assert os.path.commonpath([built_to, str(tmp_path)]) == str(tmp_path)


def test_cache_entry_skips_existing_image(entry, tmp_path):
    (tmp_path / CONTAINER["sif"]).write_bytes(b"OLD")
    runner = FakeApptainer()
    assert ac.cache_entry(entry, sif_dir=tmp_path, cache_dir=tmp_path / "c", runner=runner) == "cached"
    assert runner.calls == []
    assert (tmp_path / CONTAINER["sif"]).read_bytes() == b"OLD"


def test_cache_entry_rebuilds_empty_leftover(entry, tmp_path):
    # A 0-byte file can only come from a broken copy; resolve() refuses it, so rebuild.
    leftover = tmp_path / CONTAINER["sif"]
    leftover.write_bytes(b"")
    runner = FakeApptainer()
    assert ac.cache_entry(entry, sif_dir=tmp_path, cache_dir=tmp_path / "c", runner=runner) == "built"
    assert leftover.read_bytes() == b"SIF"


def test_cache_entry_dry_run_does_nothing(entry, tmp_path):
    runner = FakeApptainer()
    sif_dir = tmp_path / "sif"
    assert ac.cache_entry(entry, sif_dir=sif_dir, cache_dir=tmp_path / "c", runner=runner, dry_run=True) == "would-build"
    assert runner.calls == []
    assert not sif_dir.exists()


def test_cache_entry_failure_cleans_up_and_raises(entry, tmp_path):
    runner = FakeApptainer(returncode=1)
    with pytest.raises(RuntimeError, match="kilosort3@0.2.0"):
        ac.cache_entry(entry, sif_dir=tmp_path, cache_dir=tmp_path / "c", runner=runner)
    assert list(p.name for p in tmp_path.iterdir()) == ["c"]


def test_cache_entry_success_without_output_raises(entry, tmp_path):
    with pytest.raises(RuntimeError):
        ac.cache_entry(entry, sif_dir=tmp_path, cache_dir=tmp_path / "c", runner=FakeApptainer(write=False))
    assert not (tmp_path / CONTAINER["sif"]).exists()


def test_cache_entry_native_is_noop(tmp_path):
    runner = FakeApptainer()
    native = sr.parse_entry("kilosort4@4.1.7", NATIVE)
    assert ac.cache_entry(native, sif_dir=tmp_path, cache_dir=tmp_path / "c", runner=runner) == "native"
    assert runner.calls == []


# ----------------------------------------------------------------------------- CLI

@pytest.fixture
def registry_file(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"kilosort3@0.2.0": CONTAINER, "kilosort4@4.1.7": NATIVE}))
    return path


def cli(registry_file, tmp_path, *args, runner=None):
    argv = ["--registry", str(registry_file), "--sif-dir", str(tmp_path / "sif"),
            "--cache-dir", str(tmp_path / "cache"), *args]
    return ac.main(argv, runner=runner or FakeApptainer())


def test_cli_check_reports_missing(registry_file, tmp_path, capsys):
    assert cli(registry_file, tmp_path, "--check") == 1
    assert "kilosort3@0.2.0" in capsys.readouterr().out


def test_cli_check_passes_when_cached(registry_file, tmp_path):
    (tmp_path / "sif").mkdir()
    (tmp_path / "sif" / CONTAINER["sif"]).write_bytes(b"SIF")
    assert cli(registry_file, tmp_path, "--check") == 0


def test_cli_builds_all_container_entries(registry_file, tmp_path):
    runner = FakeApptainer()
    assert cli(registry_file, tmp_path, runner=runner) == 0
    assert len(runner.calls) == 1
    assert (tmp_path / "sif" / CONTAINER["sif"]).is_file()


def test_cli_unknown_key_refused(registry_file, tmp_path):
    runner = FakeApptainer()
    with pytest.raises(sr.UnknownSorterVersionError):
        cli(registry_file, tmp_path, "kilosort3@9.9.9", runner=runner)
    assert runner.calls == []


def test_cli_build_failure_returns_nonzero(registry_file, tmp_path):
    assert cli(registry_file, tmp_path, runner=FakeApptainer(returncode=1)) == 1
