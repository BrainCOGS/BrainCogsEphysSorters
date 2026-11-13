"""How a job's spec is turned into calls: step chaining, legacy vs namespaced sorting, and
the output layout. Runners are faked, so none of this needs the sorting stack."""

import json

import pytest

import u19_sorting.preprocess_wrappers as pw
import u19_sorting.sorter_wrappers as sw
from u19_sorting import config, job_spec, si_wrappers

CATGT = {"apfilter": ["biquad", 2, 300, 0], "extras": ["ap", "gblcar"]}
STEPS = {"steps": [{"name": "highpass_filter", "kwargs": {"freq_min": 300}}]}
LEGACY = {"clustering_method": "kilosort4", "n_chan_bin": 385}
NAMESPACED = {
    "clustering_method": "kilosort4",
    "sorter_params": {"Th_universal": 9},
    "si_params": {"save_preprocessed_copy": True},
}


@pytest.fixture
def job(tmp_path, monkeypatch):
    """Parameter files under tmp_path and every runner replaced by a recorder."""

    params_dir = tmp_path / "ParameterFiles"
    params_dir.mkdir()
    monkeypatch.setattr(
        config, "process_parameter_file", str(params_dir / "process_paramset_{}.json")
    )
    monkeypatch.setattr(
        config,
        "preprocess_parameter_file",
        str(params_dir / "preprocess_paramset_{}.json"),
    )
    monkeypatch.setattr(config, "chanmap_file", str(tmp_path / "chanmap_{}.mat"))

    calls = []

    def recorder(name):
        def run(source, output_dir, params):
            calls.append((name, source, output_dir, params))
            return output_dir

        return staticmethod(run)

    monkeypatch.setattr(pw.cat_gt, "run_cat_gt", recorder("catgt"))
    monkeypatch.setattr(pw.dredge, "run_dredge", recorder("dredge"))
    monkeypatch.setattr(
        si_wrappers.spikeinterface_preproc, "run", recorder("spikeinterface")
    )
    monkeypatch.setattr(
        sw.Kilosort4, "run_Kilosort4", staticmethod(lambda *a: calls.append(("ks4", a)))
    )
    monkeypatch.setattr(
        sw.Kilosort3, "run_Kilosort3", staticmethod(lambda *a: calls.append(("ks3", a)))
    )
    monkeypatch.setattr(
        sw.Kilosort2, "run_Kilosort2", staticmethod(lambda *a: calls.append(("ks2", a)))
    )

    def fake_si_run_sorter(sorting, resolved, raw_directory, output_directory):
        calls.append(("si_sort", sorting, resolved, raw_directory, output_directory))
        return "recording", "sorting"

    def fake_postprocessing(
        recording, sorting, output_directory, postprocessing, export_phy
    ):
        calls.append(("si_post", output_directory, postprocessing, export_phy))

    monkeypatch.setattr(si_wrappers, "run_sorter", fake_si_run_sorter)
    monkeypatch.setattr(si_wrappers, "run_postprocessing", fake_postprocessing)

    class Job:
        raw = tmp_path / "raw"
        processed = tmp_path / "processed"

        def write(self, pre, proc):
            (params_dir / "preprocess_paramset_1.json").write_text(json.dumps(pre))
            (params_dir / "process_paramset_1.json").write_text(json.dumps(proc))

        def process_file(self):
            return json.loads((params_dir / "process_paramset_1.json").read_text())

        def preprocess(self):
            return pw.preprocess_main(1, self.raw, self.processed)

        def sort(self):
            return sw.sorter_main(1, self.raw, self.processed)

    j = Job()
    j.calls = calls
    return j


# ----------------------------------------------------------------------------- chaining


def test_production_catgt_job_calls_catgt_as_before(job):
    job.write([{"catgt": CATGT}], LEGACY)
    out = job.preprocess()
    assert job.calls == [("catgt", job.raw, job.processed / "catgt_output", CATGT)]
    assert out == job.processed / "catgt_output"


def test_nothing_step_leaves_the_raw_directory(job):
    job.write([{"Nothing": CATGT}], LEGACY)
    assert job.preprocess() == job.raw
    assert job.calls == []


@pytest.mark.parametrize(
    "order",
    [
        ["catgt", "dredge"],
        ["spikeinterface", "dredge"],
        ["catgt", "spikeinterface", "dredge"],
        ["dredge", "spikeinterface", "catgt"],
        ["spikeinterface", "catgt", "spikeinterface", "dredge"],
    ],
)
def test_each_step_reads_what_the_previous_one_wrote(job, order):
    params = {"catgt": CATGT, "dredge": {}, "spikeinterface": STEPS}
    job.write([{m: params[m]} for m in order], LEGACY)
    out = job.preprocess()

    assert [c[0] for c in job.calls] == order
    sources = [c[1] for c in job.calls]
    outputs = [c[2] for c in job.calls]
    assert sources == [job.raw, *outputs[:-1]]
    assert out == outputs[-1]
    assert len(set(outputs)) == len(outputs)  # a repeated method gets its own folder


def test_trailing_spikeinterface_step_is_not_written_for_a_namespaced_sort(job):
    job.write([{"catgt": CATGT}, {"spikeinterface": STEPS}], NAMESPACED)
    out = job.preprocess()
    assert [c[0] for c in job.calls] == ["catgt"]
    assert out == job.processed / "catgt_output"


def test_partial_results_of_repeated_methods_are_removed(job):
    for name in ("catgt_output", "spikeinterface_output", "spikeinterface_output_2"):
        (job.processed / name).mkdir(parents=True)
    (job.processed / "kilosort4_output").mkdir()
    pw.post_process_partial_results(1, job.raw, job.processed)
    assert [p.name for p in job.processed.iterdir()] == ["kilosort4_output"]


# ------------------------------------------------------------------- legacy vs namespaced


def test_legacy_kilosort4_runs_the_native_call_with_the_rewritten_file(job):
    job.write([{"catgt": CATGT}], LEGACY)
    out = job.sort()
    assert [c[0] for c in job.calls] == ["ks4"]
    raw, output_dir, params_file, chanmap = job.calls[0][1]
    assert (raw, output_dir) == (job.raw, job.processed / "kilosort4_output")
    assert params_file == config.process_parameter_file.format(1)
    assert chanmap == config.chanmap_file.format(1)
    assert job.process_file() == {"n_chan_bin": 385}
    assert out == job.processed / "kilosort4_output"


@pytest.mark.parametrize(
    ("method", "runner", "expected"),
    [
        ("kilosort4", "ks4", {"a": 1, "nblocks": 0}),
        ("kilosort3", "ks3", {"a": 1, "nblocks": 0}),
        ("kilosort2", "ks2", {"a": 1, "reorder": 0}),
    ],
)
def test_legacy_sorters_get_their_drift_turned_off_after_dredge(
    job, method, runner, expected
):
    job.write([{"dredge": {}}], {"clustering_method": method, "a": 1})
    job.sort()
    assert [c[0] for c in job.calls] == [runner]
    assert job.process_file() == expected


def test_legacy_sorter_after_a_spikeinterface_motion_step(job):
    steps = {"steps": [{"name": "correct_motion", "kwargs": {}}]}
    job.write([{"spikeinterface": steps}], LEGACY)
    job.sort()
    assert job.process_file() == {"n_chan_bin": 385, "nblocks": 0}


def test_namespaced_paramset_runs_through_spikeinterface(job):
    job.write([{"spikeinterface": STEPS}], NAMESPACED)
    out = job.sort()

    assert [c[0] for c in job.calls] == ["si_sort"]
    _, sorting, resolved, raw, output_dir = job.calls[0]
    assert sorting.sorter_params == {"Th_universal": 9}
    assert sorting.si_params == {"save_preprocessed_copy": True}
    assert (
        sorting.lazy_steps
        == job_spec.build_job_spec(
            [{"spikeinterface": STEPS}], NAMESPACED
        ).sorting.lazy_steps
    )
    assert resolved is None
    assert (raw, output_dir) == (job.raw, job.processed / "kilosort4_output")
    assert out == job.processed / "kilosort4_output"
    # the file is left alone: nothing reads it again
    assert job.process_file() == NAMESPACED


def test_namespaced_kilosort_postprocessing_does_not_export_phy(job):
    post = {"extensions": {"quality_metrics": {}}, "export": "phy"}
    job.write([], {**NAMESPACED, "postprocessing": post})
    job.sort()
    assert [c[0] for c in job.calls] == ["si_sort", "si_post"]
    _, output_dir, postprocessing, export_phy = job.calls[1]
    assert output_dir == job.processed / "kilosort4_output"
    assert postprocessing["extensions"] == {"quality_metrics": {}}
    assert export_phy is False


def test_other_sorters_always_export_phy(job):
    job.write([], {"clustering_method": "spykingcircus2", "sorter_params": {}})
    out = job.sort()
    assert [c[0] for c in job.calls] == ["si_sort", "si_post"]
    assert job.calls[1][3] is True
    assert out == job.processed / "spykingcircus2_output"


@pytest.mark.parametrize(
    "proc",
    [
        {"clustering_method": "SpikeInterface"},
        {"clustering_method": "SpikeInterface", "sorter_params": {}},
        {"clustering_method": "spykingcircus2", "detect_threshold": 5},
        {"clustering_method": "MountainSort"},
        {"clustering_method": "nosuchsorter", "sorter_params": {}},
        {"clustering_method": "kilosort2_5", "detect_threshold": 5},
    ],
)
def test_sorters_without_a_runner_fail_loudly(job, proc):
    job.write([], proc)
    with pytest.raises(job_spec.JobSpecError):
        job.sort()
    assert job.calls == []
    assert not (job.processed / (proc["clustering_method"] + "_output")).exists()


# ------------------------------------------------------------------------- output layout


def make_run_sorter_folder(work, old_results_dir=None):
    """What SpikeInterface leaves behind for a Kilosort sort."""

    out = work / "sorter_output"
    out.mkdir(parents=True)
    results_dir = old_results_dir or out
    (out / "params.py").write_text(
        f"n_channels_dat = 384\ndat_path = '{results_dir.as_posix()}/temp_wh.dat'\n"
    )
    (out / "spike_times.npy").write_bytes(b"x")
    (out / "temp_wh.dat").write_bytes(b"y")
    (work / "spikeinterface_log.json").write_text("{}")
    (work / "spikeinterface_params.json").write_text("{}")
    return out


def test_kilosort_folder_is_flattened_into_the_method_output(tmp_path):
    final = tmp_path / "kilosort4_output"
    final.mkdir()
    (final / "spike_times.npy").write_bytes(b"stale")
    work = tmp_path / "kilosort4_output_si_work"
    make_run_sorter_folder(work)

    si_wrappers.adopt_sorter_folder(work, final, flatten=True)

    assert not work.exists()
    assert (final / "spike_times.npy").read_bytes() == b"x"
    assert sorted(p.name for p in (final / "spikeinterface").iterdir()) == [
        "spikeinterface_log.json",
        "spikeinterface_params.json",
    ]
    # params.py follows the data file to its new place, in the format the element parses
    lines = (final / "params.py").read_text().splitlines()
    assert lines[1] == f"dat_path = '{final.as_posix()}/temp_wh.dat'"
    assert all(len(line.split("=")) == 2 for line in lines)


def test_other_sorter_folder_is_kept_under_spikeinterface(tmp_path):
    final = tmp_path / "simple_output"
    work = tmp_path / "simple_output_si_work"
    make_run_sorter_folder(work)
    si_wrappers.adopt_sorter_folder(work, final, flatten=False)
    assert [p.name for p in final.iterdir()] == ["spikeinterface"]
    assert (final / "spikeinterface" / "sorter_output" / "spike_times.npy").is_file()


def test_missing_sorter_output_is_an_error(tmp_path):
    (tmp_path / "work").mkdir()
    with pytest.raises(RuntimeError, match="sorter_output"):
        si_wrappers.adopt_sorter_folder(tmp_path / "work", tmp_path / "out", True)


def test_phy_folder_is_made_element_compatible(tmp_path):
    np = pytest.importorskip("numpy")
    pd = pytest.importorskip("pandas")

    n_units, n_samples, n_channels, n_sparse = 3, 5, 8, 2
    sparse_ind = np.array([[1, 2], [7, -1], [0, 4]])
    sparse = np.arange(n_units * n_samples * n_sparse, dtype="float64").reshape(
        n_units, n_samples, n_sparse
    )
    np.save(tmp_path / "channel_map.npy", np.arange(n_channels, dtype="int32"))
    np.save(tmp_path / "template_ind.npy", sparse_ind)
    np.save(tmp_path / "templates.npy", sparse)
    pd.DataFrame({"cluster_id": [0, 1, 2], "group": ["unsorted"] * 3}).to_csv(
        tmp_path / "cluster_group.tsv", sep="\t", index=False
    )
    signed = np.array([-12.5, 3.0, -0.25, 0.0], dtype="float32")
    np.save(tmp_path / "amplitudes.npy", signed)

    si_wrappers.make_phy_folder_element_compatible(tmp_path)

    dense = np.load(tmp_path / "templates.npy")
    assert dense.shape == (n_units, n_samples, n_channels)
    assert np.array_equal(dense[0][:, [1, 2]], sparse[0])
    assert np.array_equal(dense[1][:, 7], sparse[1][:, 0])
    assert dense[1][:, :7].sum() == 0  # the -1 padding column is dropped, not written
    # the element takes the argmax over the channel axis as an index into channel_map
    assert np.abs(dense).max(axis=1).argmax(axis=1).tolist() == [2, 7, 4]
    assert not (tmp_path / "template_ind.npy").exists()
    assert np.load(tmp_path / "templates_ind.npy").shape == (n_units, n_channels)
    for name in ("whitening_mat.npy", "whitening_mat_inv.npy"):
        assert np.array_equal(np.load(tmp_path / name), np.eye(n_channels))
    groups = pd.read_csv(tmp_path / "cluster_group.tsv", sep="\t")
    assert groups["group"].tolist() == ["mua"] * 3
    # Kilosort's amplitudes are positive; the IBL step's noise_cutoff needs them to be
    amplitudes = np.load(tmp_path / "amplitudes.npy")
    assert amplitudes.dtype == signed.dtype
    assert amplitudes.tolist() == [12.5, 3.0, 0.25, 0.0]


def test_phy_folder_without_amplitudes_is_left_without(tmp_path):
    np = pytest.importorskip("numpy")
    np.save(tmp_path / "channel_map.npy", np.arange(4, dtype="int32"))
    np.save(tmp_path / "templates.npy", np.zeros((2, 5, 4), dtype="float32"))

    si_wrappers.make_phy_folder_element_compatible(tmp_path)

    assert not (tmp_path / "amplitudes.npy").exists()
