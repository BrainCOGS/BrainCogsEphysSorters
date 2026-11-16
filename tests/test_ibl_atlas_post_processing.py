"""The IBL atlas step must not fail a sorting job when the raw data has no LF file.

SpikeGLX can be set to skip the LF stream, and Neuropixels 2.0 probes never record
one. Kilosort has already finished by the time this step runs, so a missing
`*lf.bin` (or any failure of the IBL script) should be logged, not raised.
"""

import subprocess

import pytest

from u19_sorting import postprocess_wrappers as ppw

run = ppw.ibl_atlas_post_processing.run_ibl_atlas_post_processing


@pytest.fixture
def dirs(tmp_path):
    raw = tmp_path / "raw" / "run_g0_imec0"
    processed = tmp_path / "processed"
    sorter = processed / "kilosort4_output"
    for d in (raw, sorter):
        d.mkdir(parents=True)
    (raw / "run_g0_t0.imec0.ap.bin").touch()
    (raw / "run_g0_t0.imec0.ap.meta").touch()
    return raw, processed, sorter


class FakeRun(list):
    """Stands in for subprocess.run and records each command it gets."""

    returncode = 0

    def __call__(self, command, **kwargs):
        self.append(command)
        return subprocess.CompletedProcess(command, self.returncode, b"", b"boom")


@pytest.fixture
def calls(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(ppw.subprocess, "run", fake)
    return fake


def test_skips_without_lf_file(dirs, calls, capsys):
    raw, processed, sorter = dirs
    run(raw, processed, sorter)
    assert calls == []
    assert "lf.bin" in capsys.readouterr().out


def test_script_failure_is_logged_not_raised(dirs, calls, capsys):
    raw, processed, sorter = dirs
    (raw / "run_g0_t0.imec0.lf.bin").touch()
    calls.returncode = 1
    run(raw, processed, sorter)
    assert len(calls) == 1
    assert "boom" in capsys.readouterr().out


def test_runs_with_lf_file(dirs, calls):
    raw, processed, sorter = dirs
    (raw / "run_g0_t0.imec0.lf.bin").touch()
    run(raw, processed, sorter)
    assert len(calls) == 1
    assert (processed / "ibl_data").is_dir()


def test_missing_raw_directory_skips(tmp_path, calls):
    processed = tmp_path / "processed"
    run(tmp_path / "does_not_exist", processed, processed / "kilosort4_output")
    assert calls == []
