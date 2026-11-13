"""End-to-end run of the SpikeInterface path on a small synthetic SpikeGLX recording.

No real data and no GPU: a few seconds of a 384-channel NP1 recording with the sync channel,
sorted by SpikeInterface's built-in `simple` sorter. Skipped where the sorting stack is not
installed (CI's lightweight leg).
"""

import json
import pathlib
import re

import pytest

np = pytest.importorskip("numpy")
si = pytest.importorskip("spikeinterface.full")
probeinterface = pytest.importorskip("probeinterface")
ibllib = pytest.importorskip("ibllib")

import u19_sorting.preprocess_wrappers as pw  # noqa: E402
import u19_sorting.sorter_wrappers as sw  # noqa: E402
from u19_sorting import config, job_spec, si_wrappers  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")

UV_PER_COUNT = 0.195  # NP1 AP gain 500 -> ~0.195 uV/bit
FS = 30000.390639481  # imSampRate of the meta fixture
DURATION = 6.0
NP1_META = (
    pathlib.Path(ibllib.__file__).parent
    / "tests"
    / "fixtures"
    / "pipes"
    / "sample3B_g0_t0.imec1.ap.meta"
)

# What element_array_ephys/readers/kilosort.py refuses to load a folder without.
ELEMENT_CORE_FILES = [
    "params.py",
    "amplitudes.npy",
    "channel_map.npy",
    "channel_positions.npy",
    "pc_features.npy",
    "pc_feature_ind.npy",
    "similar_templates.npy",
    "spike_templates.npy",
    "spike_times.npy",
    "templates.npy",
    "templates_ind.npy",
    "whitening_mat.npy",
    "whitening_mat_inv.npy",
    "spike_clusters.npy",
]

STEPS = {
    "steps": [
        {"name": "phase_shift", "kwargs": {}},
        {"name": "highpass_filter", "kwargs": {"freq_min": 300}},
        {
            "name": "common_reference",
            "kwargs": {"operator": "median", "reference": "global"},
        },
    ]
}


@pytest.fixture(scope="module")
def spikeglx_run(tmp_path_factory):
    """A SpikeGLX probe folder: int16 ap.bin (384 channels + SY0) and a matching ap.meta."""

    raw = tmp_path_factory.mktemp("raw") / "synth_g0_imec1"
    raw.mkdir()
    probe = probeinterface.read_spikeglx(NP1_META)
    recording, _ = si.generate_ground_truth_recording(
        durations=[DURATION],
        sampling_frequency=FS,
        num_channels=probe.get_contact_count(),
        num_units=12,
        probe=probe,
        seed=0,
    )
    traces = si.astype(
        si.scale(recording, gain=1 / UV_PER_COUNT), "int16", round=True
    ).get_traces()
    sync = ((np.arange(traces.shape[0]) // 3000) % 2 * 64).astype(np.int16)[:, None]
    bin_path = raw / "synth_g0_t0.imec1.ap.bin"
    np.concatenate([traces, sync], axis=1).tofile(bin_path)

    meta = NP1_META.read_text()
    meta = re.sub(
        r"fileSizeBytes=\d+", f"fileSizeBytes={bin_path.stat().st_size}", meta
    )
    meta = re.sub(r"fileTimeSecs=[\d.]+", f"fileTimeSecs={DURATION}", meta)
    meta = re.sub(r"firstSample=\d+", "firstSample=0", meta)
    (raw / "synth_g0_t0.imec1.ap.meta").write_text(meta)
    return raw, sync[:, 0]


@pytest.fixture
def job(tmp_path, monkeypatch):
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

    def write(pre, proc):
        (params_dir / "preprocess_paramset_1.json").write_text(json.dumps(pre))
        (params_dir / "process_paramset_1.json").write_text(json.dumps(proc))
        return tmp_path / "processed"

    return write


def run_job(raw, processed):
    """What main_script.py does, minus the IBL atlas step."""

    spec = job_spec.load_job_spec(1)
    sorter_input = pw.preprocess_main(1, raw, processed, spec)
    output = sw.sorter_main(1, sorter_input, processed, spec)
    pw.post_process_partial_results(1, raw, processed)
    return sorter_input, output


def test_written_spikeinterface_step_is_a_spikeglx_run_with_the_sync_channel(
    spikeglx_run, job
):
    raw, sync = spikeglx_run
    processed = job([{"spikeinterface": {**STEPS, "materialize": True}}], {})
    out = si_wrappers.spikeinterface_preproc.run(
        raw,
        processed / "spikeinterface_output",
        job_spec.normalize_spikeinterface_params(STEPS),
    )

    src_bin = raw / "synth_g0_t0.imec1.ap.bin"
    out_bin = out / "synth_g0_t0.imec1.ap.bin"
    assert out_bin.stat().st_size == src_bin.stat().st_size
    assert (out / "synth_g0_t0.imec1.ap.meta").read_text() == (
        raw / "synth_g0_t0.imec1.ap.meta"
    ).read_text()

    written = np.memmap(out_bin, dtype="int16").reshape(-1, 385)
    source = np.memmap(src_bin, dtype="int16").reshape(-1, 385)
    assert np.array_equal(written[:, 384], sync)  # sync channel untouched
    assert not np.array_equal(written[:, :384], source[:, :384])  # traces were filtered
    # common median reference: the median across channels is ~0 at every sample
    assert np.abs(np.median(written[:2000, :384], axis=1)).max() <= 1

    # the next step (or the sorter) opens it like a raw run, and a rerun skips the work
    assert si_wrappers.read_recording(out).get_num_channels() == 384
    assert si_wrappers.spikeglx_copy_complete(out, "spikeinterface") == 1


def test_namespaced_job_with_a_non_kilosort_sorter_lands_in_the_element_layout(
    spikeglx_run, job
):
    raw, _ = spikeglx_run
    processed = job(
        [{"spikeinterface": STEPS}],
        {
            "clustering_method": "simple",
            "sorter_version": None,
            # kmeans: the default clusterer needs hdbscan, which is not a dependency here
            "sorter_params": {
                "apply_preprocessing": False,
                "clusterer": "kmeans",
                "clusterer_kwargs": {"n_clusters": 8, "random_state": 0},
            },
            "si_params": {},
            "postprocessing": {
                "extensions": {"quality_metrics": {}},
                "export": "phy",
                "job_kwargs": {"n_jobs": 1, "progress_bar": False},
            },
        },
    )
    sorter_input, output = run_job(raw, processed)

    # the trailing step list was applied lazily: no preprocessed copy was written
    assert sorter_input == raw
    assert not (processed / "spikeinterface_output").exists()
    assert output == processed / "simple_output"

    missing = [f for f in ELEMENT_CORE_FILES if not (output / f).is_file()]
    assert missing == []
    assert not (output / "metrics.csv").exists()  # the element reads that as ecephys QC
    assert (output / "spikeinterface" / "quality_metrics.csv").is_file()
    assert (output / "spikeinterface" / "analyzer").is_dir()
    assert (output / "win_params.py").is_file()

    # --- what the element reader does with the folder
    params = {}
    for line in (output / "params.py").read_text().splitlines():
        key, value = line.strip("\n").split("=")
        params[key.strip()] = value.strip()
    assert params["n_channels_dat"] == "384"

    channel_map = np.load(output / "channel_map.npy").flatten()
    templates = np.load(output / "templates.npy")
    spike_templates = np.load(output / "spike_templates.npy").flatten()
    spike_clusters = np.load(output / "spike_clusters.npy").flatten()
    assert channel_map.tolist() == list(range(384))
    assert (
        templates.shape[2] == 384
    )  # dense, so argmax over channels indexes channel_map
    assert len(spike_templates) == len(spike_clusters) > 0
    # positive, as Kilosort writes them (the IBL step's noise_cutoff fails otherwise)
    amplitudes = np.load(output / "amplitudes.npy").flatten()
    assert len(amplitudes) == len(spike_templates)
    assert (amplitudes >= 0).all()

    groups = (output / "cluster_group.tsv").read_text().splitlines()
    assert groups[0].split("\t") == ["cluster_id", "group"]
    assert {line.split("\t")[1] for line in groups[1:]} <= {
        "good",
        "ok",
        "mua",
        "noise",
    }

    # extract_spike_depths: centre of mass of the first PC over each spike's channels
    pc_features = np.load(output / "pc_features.npy")[:, 0, :]
    pc_feature_ind = np.load(output / "pc_feature_ind.npy")
    ycoords = np.load(output / "channel_positions.npy")[:, 1]
    assert pc_features.shape[0] == len(spike_templates)
    assert ycoords[pc_feature_ind[spike_templates, :]].shape == pc_features.shape
    max_site = np.abs(templates).max(axis=1).argmax(axis=1)
    assert channel_map[max_site[spike_templates]].max() < 384
