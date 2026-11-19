"""How a job's spec is turned into calls: step chaining, legacy vs namespaced sorting, the
postprocessing stage, and the output layout. Runners are faked, so none of this needs the
sorting stack."""

import json
import pathlib
import runpy

import pytest

import u19_sorting.postprocess_wrappers as ppw
import u19_sorting.preprocess_wrappers as pw
import u19_sorting.sorter_wrappers as sw
from u19_sorting import config, job_spec, si_wrappers

REPO = pathlib.Path(__file__).resolve().parents[1]

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
    monkeypatch.setattr(
        config,
        "postprocess_parameter_file",
        str(params_dir / "postprocess_paramset_{}.json"),
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

    def post_recorder(name):
        def run(context, params):
            calls.append((name, context, params))

        return staticmethod(run)

    def fake_finish(context, export_phy):
        calls.append(("finish", context, export_phy))

    monkeypatch.setattr(si_wrappers, "run_sorter", fake_si_run_sorter)
    monkeypatch.setattr(
        si_wrappers.spikeinterface_postproc, "run", post_recorder("si_post")
    )
    monkeypatch.setattr(si_wrappers.bombcell_postproc, "run", post_recorder("bombcell"))
    monkeypatch.setattr(si_wrappers, "finish_postprocessing", fake_finish)

    class Job:
        raw = tmp_path / "raw"
        processed = tmp_path / "processed"

        def write(self, pre, proc, post=None):
            (params_dir / "preprocess_paramset_1.json").write_text(json.dumps(pre))
            (params_dir / "process_paramset_1.json").write_text(json.dumps(proc))
            if post is not None:
                (params_dir / "postprocess_paramset_1.json").write_text(
                    json.dumps(post)
                )

        def process_file(self):
            return json.loads((params_dir / "process_paramset_1.json").read_text())

        def sorter_file(self, method="kilosort4"):
            """What a legacy sorter was handed: <method>_output/sorter_params.json."""
            path = self.processed / f"{method}_output" / "sorter_params.json"
            return json.loads(path.read_text())

        def preprocess(self):
            return pw.preprocess_main(1, self.raw, self.processed)

        def sort(self):
            return sw.sorter_main(1, self.raw, self.processed)

        def sort_and_postprocess(self, sorter_input=None):
            """The sort and postprocessing stages, as main_script.py runs them."""
            sorter_input = self.raw if sorter_input is None else sorter_input
            spec = job_spec.load_job_spec(1, missing_preprocess_ok=True)
            result = sw.run_sort(1, sorter_input, self.processed, spec)
            context = ppw.postprocess_main(spec, self.raw, sorter_input, result)
            return result, context

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


def test_legacy_kilosort4_runs_the_native_call_with_its_own_param_file(job):
    job.write([{"catgt": CATGT}], LEGACY)
    out = job.sort()
    assert [c[0] for c in job.calls] == ["ks4"]
    raw, output_dir, params_file, chanmap = job.calls[0][1]
    assert (raw, output_dir) == (job.raw, job.processed / "kilosort4_output")
    assert params_file == (output_dir / "sorter_params.json").as_posix()
    assert chanmap == config.chanmap_file.format(1)
    assert job.sorter_file() == {"n_chan_bin": 385}
    # the job's own file is left as written, so a rerun can read it again
    assert job.process_file() == LEGACY
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
    assert job.sorter_file(method) == expected


def test_legacy_sorter_after_a_spikeinterface_motion_step(job):
    steps = {"steps": [{"name": "correct_motion", "kwargs": {}}]}
    job.write([{"spikeinterface": steps}], LEGACY)
    job.sort()
    assert job.sorter_file() == {"n_chan_bin": 385, "nblocks": 0}


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


def test_the_sort_stage_does_no_postprocessing(job):
    post = {"extensions": {"quality_metrics": {}}, "export": "phy"}
    job.write([], {**NAMESPACED, "postprocessing": post}, [{"bombcell": {}}])
    job.sort()
    assert [c[0] for c in job.calls] == ["si_sort"]


def test_namespaced_kilosort_postprocessing_does_not_export_phy(job):
    post = {"extensions": {"quality_metrics": {}}, "export": "phy"}
    job.write([], {**NAMESPACED, "postprocessing": post})
    result, _ = job.sort_and_postprocess()
    assert [c[0] for c in job.calls] == ["si_sort", "si_post", "finish"]
    _, context, postprocessing = job.calls[1]
    assert context.output_directory == job.processed / "kilosort4_output"
    assert postprocessing["extensions"] == {"quality_metrics": {}}
    assert job.calls[2][2] is False  # export_phy
    # the analyzer is built on what the sort stage had in memory, exactly as before
    assert (context._recording, context._sorting) == ("recording", "sorting")
    assert (result.recording, result.sorting) == ("recording", "sorting")
    assert context.resolved_recording_steps() == []


def test_other_sorters_always_export_phy(job, monkeypatch):
    os_copies = []
    monkeypatch.setattr(sw, "params_file_for_different_os", os_copies.append)
    job.write([], {"clustering_method": "spykingcircus2", "sorter_params": {}})
    result, _ = job.sort_and_postprocess()
    assert [c[0] for c in job.calls] == ["si_sort", "finish"]
    assert job.calls[1][2] is True
    assert result.output_directory == job.processed / "spykingcircus2_output"
    # the sort stage ran it before the export, and the export wrote a new params.py
    assert os_copies == [result.output_directory] * 2


def test_no_postprocessing_for_a_kilosort_job_without_steps(job):
    job.write([{"catgt": CATGT}], LEGACY)
    _, context = job.sort_and_postprocess()
    assert context is None
    assert [c[0] for c in job.calls] == ["ks4"]


def test_postprocess_file_steps_run_in_order_after_the_paramset_ones(job):
    post = {"extensions": {"quality_metrics": {}}}
    file_steps = [
        {"bombcell": {"split_non_somatic": True}},
        {"spikeinterface": {"extensions": {"template_metrics": {}}}},
    ]
    job.write([], {**NAMESPACED, "postprocessing": post}, file_steps)
    job.sort_and_postprocess()
    assert [c[0] for c in job.calls] == [
        "si_sort",
        "si_post",
        "bombcell",
        "si_post",
        "finish",
    ]
    assert job.calls[2][2]["split_non_somatic"] is True
    assert job.calls[3][2]["extensions"] == {"template_metrics": {}}
    # one analyzer for every step
    assert len({id(c[1]) for c in job.calls[1:]}) == 1


def test_legacy_sort_is_read_back_from_disk_for_postprocessing(job, monkeypatch):
    opened = []
    monkeypatch.setattr(
        si_wrappers, "read_recording", lambda d: opened.append(("rec", d)) or "rec"
    )
    monkeypatch.setattr(
        si_wrappers, "read_sorter_output", lambda d: opened.append(("ks", d)) or "ks"
    )
    job.write([{"catgt": CATGT}], LEGACY, [{"bombcell": {}}])
    catgt_out = job.processed / "catgt_output"
    result, context = job.sort_and_postprocess(sorter_input=catgt_out)

    assert [c[0] for c in job.calls] == ["ks4", "bombcell", "finish"]
    assert (result.recording, result.sorting) == (None, None)
    assert job.calls[2][2] is False  # Kilosort wrote the phy folder itself
    # nothing is opened until a step builds the analyzer
    assert opened == []
    assert context._open(context._recording) == "rec"
    assert context._open(context._sorting) == "ks"
    assert opened == [("rec", catgt_out), ("ks", job.processed / "kilosort4_output")]
    # CatGT filtered the recording, so the default ("auto") adds nothing
    assert context.recording_steps == job_spec.AUTO
    assert context.resolved_recording_steps() == []


def test_auto_filters_a_raw_recording_for_the_analyzer(job):
    job.write([{"Nothing": {}}], LEGACY, [{"bombcell": {}}])
    _, context = job.sort_and_postprocess()
    assert [s["name"] for s in context.resolved_recording_steps()] == [
        "highpass_filter",
        "common_reference",
    ]


def test_main_script_postprocesses_before_the_cleanup(monkeypatch, tmp_path):
    """The postprocessing stage reads the recording the sorter read, which the cleanup
    deletes when it is a CatGT/DREDge/spikeinterface output; IBL runs last."""

    calls = []
    spec = job_spec.build_job_spec([{"catgt": CATGT}], LEGACY, [{"bombcell": {}}])
    sorted_dir = tmp_path / "processed" / "kilosort4_output"
    result = sw.SortResult(sorted_dir)

    def record(name, value=None):
        def call(*args):
            calls.append((name, args))
            return value

        return call

    monkeypatch.setenv("recording_process_id", "5")
    monkeypatch.setenv("raw_data_directory", "raw/run_g0_imec0")
    monkeypatch.setenv("processed_data_directory", "proc/run_g0_imec0/job_id_5")
    monkeypatch.setattr(job_spec, "load_job_spec", record("spec", spec))
    monkeypatch.setattr(pw, "preprocess_main", record("preprocess", "catgt_dir"))
    monkeypatch.setattr(sw, "run_sort", record("sort", result))
    monkeypatch.setattr(ppw, "postprocess_main", record("postprocess"))
    monkeypatch.setattr(pw, "post_process_partial_results", record("cleanup"))
    monkeypatch.setattr(ppw, "post_process_main", record("ibl"))

    runpy.run_path(str(REPO / "main_script.py"), run_name="__main__")

    assert [c[0] for c in calls] == [
        "spec",
        "preprocess",
        "sort",
        "postprocess",
        "cleanup",
        "ibl",
    ]
    _, (got_spec, raw, sorter_input, got_result) = calls[3]
    assert got_spec is spec and got_result is result
    assert sorter_input == "catgt_dir"  # what the sorter read, not the raw run
    assert raw == pathlib.Path(config.root_raw_data_dir, "raw/run_g0_imec0")
    assert calls[5][1][2] == sorted_dir


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


# ---------------------------------------------------------------------------- job kwargs


def test_n_jobs_defaults_to_the_cpus_slurm_gave_the_job(monkeypatch):
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "8")
    assert si_wrappers.with_default_job_kwargs(None) == {
        "n_jobs": 8,
        "chunk_duration": "1s",
    }
    assert si_wrappers.with_default_job_kwargs({"chunk_memory": "1G"}) == {
        "n_jobs": 8,
        "chunk_memory": "1G",
    }


def test_paramset_n_jobs_wins_over_slurm(monkeypatch):
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "8")
    given = {"n_jobs": 2, "progress_bar": False}
    assert si_wrappers.with_default_job_kwargs(given) == given


@pytest.mark.parametrize("cpus", [None, "", "1", "many"])
def test_no_job_kwargs_are_added_without_several_slurm_cpus(monkeypatch, cpus):
    if cpus is None:
        monkeypatch.delenv("SLURM_CPUS_PER_TASK", raising=False)
    else:
        monkeypatch.setenv("SLURM_CPUS_PER_TASK", cpus)
    assert si_wrappers.with_default_job_kwargs({}) == {}
