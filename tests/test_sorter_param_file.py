"""sorter_main must leave the job's parameter file as it found it.

It used to pop "clustering_method" and write the rest back over
process_paramset_<id>.json, so running the same job a second time (a manual
sbatch rerun, a slurm requeue) failed with KeyError: 'clustering_method'.
"""

import json

import pytest

from u19_sorting import config
from u19_sorting import sorter_wrappers as sw

PARAMS = {"clustering_method": "kilosort4", "n_chan_bin": 385}


@pytest.fixture
def job(tmp_path, monkeypatch):
    params_dir = tmp_path / "ParameterFiles"
    params_dir.mkdir()
    param_file = params_dir / "process_paramset_1.json"
    param_file.write_text(json.dumps(PARAMS))
    monkeypatch.setattr(
        config, "process_parameter_file", str(params_dir / "process_paramset_{}.json")
    )
    monkeypatch.setattr(config, "chanmap_file", str(tmp_path / "chanmap_{}.mat"))
    monkeypatch.setattr(sw.pw, "preprocess_tool_params", lambda *a: None)
    monkeypatch.setattr(
        sw, "params_file_for_different_os", lambda *a: None, raising=False
    )

    calls = []

    def fake_run(raw, out, params_filename, chanmap):
        with open(params_filename) as f:
            calls.append(json.load(f))

    monkeypatch.setattr(sw.Kilosort4, "run_Kilosort4", staticmethod(fake_run))
    return tmp_path, param_file, calls


def test_rerun_reads_the_same_parameters(job):
    tmp_path, param_file, calls = job
    for _ in range(2):
        sw.sorter_main(1, str(tmp_path / "raw"), str(tmp_path / "processed"))
    assert json.loads(param_file.read_text()) == PARAMS
    assert calls == [{"n_chan_bin": 385}] * 2


def test_sorter_gets_params_without_clustering_method(job):
    tmp_path, _, calls = job
    out = sw.sorter_main(1, str(tmp_path / "raw"), str(tmp_path / "processed"))
    assert calls == [{"n_chan_bin": 385}]
    assert out.name == "kilosort4_output"
