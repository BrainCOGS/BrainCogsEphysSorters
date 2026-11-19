"""The postprocessing stage on a small synthetic recording: the shared sorting analyzer,
the `spikeinterface` and `bombcell` methods, reuse on a rerun, and the phy labels.

No real data and no GPU: SpikeInterface's ground-truth generator stands in for a sort.
Skipped where the sorting stack is not installed (CI's lightweight leg), like the other
SpikeInterface tests.
"""

import json

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
si = pytest.importorskip("spikeinterface.full")
pytest.importorskip("spikeinterface.curation", reason="needs the bombcell port")

import u19_sorting.postprocess_wrappers as ppw  # noqa: E402
import u19_sorting.sorter_wrappers as sw  # noqa: E402
from u19_sorting import job_spec, si_wrappers  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")

BOMBCELL_LABELS = {"good", "mua", "noise", "non_soma"}
# A SpikeGLX rate, so a Kilosort folder that says 30000 has to be aligned to it.
FS = 30000.390639481


@pytest.fixture(scope="module")
def ground_truth():
    recording, sorting = si.generate_ground_truth_recording(
        durations=[20.0],
        sampling_frequency=FS,
        num_channels=32,
        num_units=6,
        seed=0,
    )
    return recording, sorting


def bombcell_spec(sorter="kilosort4", **params):
    return job_spec.build_job_spec(
        [], {"clustering_method": sorter}, [{"bombcell": params}]
    )


def context_for(tmp_path, recording, sorting, steps=()):
    return si_wrappers.PostprocessContext(
        tmp_path / "kilosort4_output", recording, sorting, recording_steps=list(steps)
    )


# ----------------------------------------------------------------------------- pure parts


def test_threshold_overrides_change_only_what_they_name():
    defaults = si_wrappers.bombcell_thresholds(None)
    merged = si_wrappers.bombcell_thresholds(
        {"mua": {"snr": {"greater": 3}, "isolation_distance": None}}
    )
    assert merged["mua"]["snr"] == {"greater": 3, "less": None}
    assert "isolation_distance" not in merged["mua"]
    assert merged["noise"] == defaults["noise"]
    # the defaults themselves are not modified
    assert si_wrappers.bombcell_thresholds(None)["mua"]["snr"]["greater"] == 5


def test_phy_labels_of_a_kilosort_folder_use_the_unit_ids(tmp_path):
    si_wrappers.write_bombcell_phy_labels(tmp_path, {3: "good", 7: "noise"})
    rows = pd.read_csv(tmp_path / "cluster_bc_unitType.tsv", sep="\t")
    assert rows.to_dict("list") == {
        "cluster_id": [3, 7],
        "bc_unitType": ["good", "noise"],
    }


def test_phy_labels_of_an_exported_folder_use_its_cluster_ids(tmp_path):
    pd.DataFrame({"cluster_id": [0, 1], "si_unit_id": ["a", "b"]}).to_csv(
        tmp_path / "cluster_si_unit_ids.tsv", sep="\t", index=False
    )
    si_wrappers.write_bombcell_phy_labels(tmp_path, {"b": "mua", "a": "good"})
    rows = pd.read_csv(tmp_path / "cluster_bc_unitType.tsv", sep="\t")
    assert rows.to_dict("list") == {
        "cluster_id": [0, 1],
        "bc_unitType": ["good", "mua"],
    }


# ------------------------------------------------------------------------------ analyzer


def test_bombcell_labels_the_units_and_leaves_the_curation_alone(
    tmp_path, ground_truth
):
    recording, sorting = ground_truth
    output = tmp_path / "kilosort4_output"
    output.mkdir()
    curation = "cluster_id\tgroup\n0\tgood\n"
    (output / "cluster_group.tsv").write_text(curation)

    spec = bombcell_spec(job_kwargs={"n_jobs": 1, "progress_bar": False})
    result = sw.SortResult(output, recording=recording, sorting=sorting)
    context = ppw.postprocess_main(spec, tmp_path / "raw", tmp_path / "catgt", result)

    labels = context.bombcell_labels
    assert sorted(labels) == sorted(sorting.unit_ids)
    assert set(labels.values()) <= BOMBCELL_LABELS

    si_dir = output / "spikeinterface"
    assert (si_dir / "analyzer").is_dir()
    for name in ("labeling_results_wide.csv", "labeling_results_narrow.csv"):
        assert (si_dir / "bombcell" / name).is_file()
    thresholds = json.loads((si_dir / "bombcell" / "thresholds.json").read_text())
    assert set(thresholds) == {"noise", "mua", "non-somatic"}
    assert (si_dir / "quality_metrics.csv").is_file()
    assert (si_dir / "template_metrics.csv").is_file()

    phy = pd.read_csv(output / "cluster_bc_unitType.tsv", sep="\t")
    assert [str(c) for c in phy["cluster_id"]] == [str(u) for u in labels]
    assert phy["bc_unitType"].tolist() == list(labels.values())
    # the curation the element loads, and its "QC ran" marker, are untouched
    assert (output / "cluster_group.tsv").read_text() == curation
    assert not (output / "metrics.csv").exists()

    # bombcell's metrics were computed: the noise and mua sections had data to threshold
    qm = pd.read_csv(si_dir / "quality_metrics.csv")
    for column in ("snr", "amplitude_median", "isolation_distance", "drift_ptp"):
        assert column in qm.columns
    tm = pd.read_csv(si_dir / "template_metrics.csv")
    assert "exp_decay" in tm.columns


def test_a_rerun_reuses_the_analyzer_of_the_same_sort(tmp_path, ground_truth):
    recording, sorting = ground_truth
    job_kwargs = {"n_jobs": 1, "progress_bar": False}
    params = {
        "extensions": {"templates": {}, "noise_levels": {}},
        "job_kwargs": job_kwargs,
    }

    first = context_for(tmp_path, recording, sorting)
    si_wrappers.spikeinterface_postproc.run(first, params)
    templates = first.si_dir / "analyzer" / "extensions" / "templates"
    stamp = {p.name: p.stat().st_mtime_ns for p in templates.iterdir()}

    again = context_for(tmp_path, recording, sorting)
    analyzer = again.compute(
        {"templates": {}, "noise_levels": {}, "spike_amplitudes": {}}, job_kwargs
    )
    assert {p.name: p.stat().st_mtime_ns for p in templates.iterdir()} == stamp
    assert analyzer.has_extension("spike_amplitudes")  # only the missing one was added

    # another sort (a rerun that sorted again) gets a new analyzer
    other = si.generate_sorting(
        num_units=4, durations=[20.0], sampling_frequency=FS, seed=1
    )
    fresh = context_for(tmp_path, recording, other).analyzer(job_kwargs)
    assert list(fresh.unit_ids) == list(other.unit_ids)
    assert not fresh.has_extension("templates")


def test_a_quality_metrics_step_before_bombcell_is_topped_up(tmp_path, ground_truth):
    recording, sorting = ground_truth
    job_kwargs = {"n_jobs": 1, "progress_bar": False}
    context = context_for(tmp_path, recording, sorting)
    si_wrappers.spikeinterface_postproc.run(
        context,
        {
            "extensions": {"quality_metrics": {"metric_names": ["num_spikes"]}},
            "job_kwargs": job_kwargs,
        },
    )
    si_wrappers.bombcell_postproc.run(
        context, job_spec.normalize_bombcell({"job_kwargs": job_kwargs})
    )
    columns = context.analyzer(job_kwargs).get_extension("quality_metrics").get_data()
    assert {"num_spikes", "snr", "presence_ratio", "l_ratio"} <= set(columns.columns)


def test_legacy_kilosort_folder_is_read_back_at_the_recording_rate(
    tmp_path, ground_truth, monkeypatch
):
    """A legacy sort leaves only its folder; Kilosort wrote `sample_rate = 30000.0`."""

    recording, sorting = ground_truth
    job_kwargs = {"n_jobs": 1, "progress_bar": False}
    source = si.create_sorting_analyzer(sorting, recording, sparse=True)
    source.compute(["random_spikes", "templates"], **job_kwargs)
    output = tmp_path / "kilosort4_output"
    si.export_to_phy(
        source,
        output,
        compute_pc_features=False,
        compute_amplitudes=False,
        copy_binary=False,
        verbose=False,
        **job_kwargs,
    )
    params_py = output / "params.py"
    params_py.write_text(
        "\n".join(
            "sample_rate = 30000.0" if line.startswith("sample_rate") else line
            for line in params_py.read_text().splitlines()
        )
    )
    (output / "cluster_si_unit_ids.tsv").unlink()  # as in a Kilosort folder
    (output / "cluster_group.tsv").write_text(
        "cluster_id\tgroup\n" + "".join(f"{i}\tgood\n" for i in range(6))
    )
    monkeypatch.setattr(si_wrappers, "read_recording", lambda directory: recording)

    spec = job_spec.build_job_spec(
        [],
        {"clustering_method": "kilosort4", "n_chan_bin": 385},
        [
            {
                "spikeinterface": {
                    "extensions": {"templates": {}},
                    "job_kwargs": job_kwargs,
                }
            }
        ],
    )
    context = ppw.postprocess_main(
        spec, tmp_path / "raw", tmp_path / "catgt_output", sw.SortResult(output)
    )

    analyzer = context.analyzer(job_kwargs)
    assert analyzer.sampling_frequency == pytest.approx(FS)
    assert analyzer.has_extension("templates")
    assert sorted(int(u) for u in analyzer.unit_ids) == list(range(6))
    assert analyzer.get_num_channels() == recording.get_num_channels()
