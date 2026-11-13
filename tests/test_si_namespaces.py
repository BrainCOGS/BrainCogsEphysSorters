"""validate_sorter_namespaces: which keys a namespaced paramset may put in sorter_params
and which in si_params. Needs SpikeInterface and Kilosort 4 (their default params are the
reference), so it is skipped where the sorting stack is not installed."""

import pytest

pytest.importorskip("spikeinterface")
pytest.importorskip("kilosort")

from u19_sorting import job_spec, si_wrappers

validate = si_wrappers.validate_sorter_namespaces


def test_kilosort4_settings_are_accepted_in_sorter_params():
    validate("kilosort4", {"Th_universal": 9, "nblocks": 0}, {})


@pytest.mark.parametrize(
    "si_params",
    [
        {"do_correction": False},
        {"skip_kilosort_preprocessing": True},
        {"save_preprocessed_copy": True},
        {"delete_recording_dat": False},
        {"n_jobs": 4},
        {"do_correction": False, "n_jobs": 4, "chunk_duration": "1s"},
    ],
)
def test_spikeinterface_options_and_job_kwargs_are_accepted_in_si_params(si_params):
    validate("kilosort4", {}, si_params)


def test_kilosort4_setting_in_si_params_is_refused():
    with pytest.raises(job_spec.JobSpecError, match=r"si_params: \['nblocks'\]") as e:
        validate("kilosort4", {}, {"nblocks": 0})
    assert "belong in sorter_params" in str(e.value)


@pytest.mark.parametrize("key", ["do_correction", "save_preprocessed_copy"])
def test_spikeinterface_option_in_sorter_params_is_refused(key):
    with pytest.raises(job_spec.JobSpecError, match="sorter_params") as e:
        validate("kilosort4", {key: True}, {})
    assert "belong in si_params" in str(e.value)


@pytest.mark.parametrize("key", ["n_jobs", "chunk_duration", "progress_bar"])
def test_job_kwargs_in_sorter_params_are_refused(key):
    # SpikeInterface lists the job kwargs among Kilosort 4's default params, but they are
    # not Kilosort settings
    with pytest.raises(job_spec.JobSpecError, match="belong in si_params"):
        validate("kilosort4", {key: 1}, {})


@pytest.mark.parametrize("key", ["n_chan_bin", "fs"])
def test_recording_derived_settings_are_refused_with_a_hint(key):
    with pytest.raises(job_spec.JobSpecError, match="come from the recording"):
        validate("kilosort4", {key: 385}, {})


@pytest.mark.parametrize(
    ("sorter_params", "si_params", "namespace"),
    [
        ({"no_such_setting": 1}, {}, "sorter_params"),
        ({}, {"no_such_option": 1}, "si_params"),
    ],
)
def test_unknown_keys_are_refused(sorter_params, si_params, namespace):
    with pytest.raises(job_spec.JobSpecError, match=namespace) as e:
        validate("kilosort4", sorter_params, si_params)
    assert "belong in" not in str(e.value)


def test_other_sorters_accept_their_own_params():
    validate("simple", {"clusterer": "kmeans", "detect_threshold": 6}, {})


def test_other_sorters_refuse_unknown_keys():
    with pytest.raises(job_spec.JobSpecError, match="simple"):
        validate("simple", {"Th_universal": 9}, {})


# ------------------------------------------------------------- what reaches run_sorter


@pytest.fixture
def run_sorter_kwargs(tmp_path, monkeypatch):
    """si_wrappers.run_sorter with the reader and SpikeInterface's run_sorter faked."""

    import spikeinterface.sorters as ss

    seen = {}

    def fake_run_sorter(recording, **kwargs):
        seen.update(kwargs)
        (tmp_path / kwargs["folder"] / "sorter_output").mkdir(parents=True)
        return "sorting"

    monkeypatch.setattr(si_wrappers, "read_recording", lambda raw: "recording")
    monkeypatch.setattr(si_wrappers, "apply_steps", lambda rec, steps, **kw: rec)
    monkeypatch.setattr(ss, "run_sorter", fake_run_sorter)

    def run(clustering_method, sorter_params=None, si_params=None):
        spec = job_spec.SortingSpec(
            clustering_method,
            legacy=False,
            sorter_params=sorter_params or {},
            si_params=si_params or {},
        )
        seen.clear()
        si_wrappers.run_sorter(spec, None, tmp_path / "raw", tmp_path / "out")
        return dict(seen)

    return run


@pytest.mark.parametrize("method", ["kilosort4", "kilosort3", "kilosort2_5"])
def test_kilosort_recording_copy_is_deleted_by_default(run_sorter_kwargs, method):
    # the copy would otherwise land in the phy folder, as large as the raw recording
    assert run_sorter_kwargs(method)["delete_recording_dat"] is True


def test_kilosort_recording_copy_is_kept_on_request(run_sorter_kwargs):
    kwargs = run_sorter_kwargs("kilosort4", si_params={"delete_recording_dat": False})
    assert kwargs["delete_recording_dat"] is False
    kwargs = run_sorter_kwargs(
        "kilosort3", sorter_params={"delete_recording_dat": False}
    )
    assert kwargs["delete_recording_dat"] is False


def test_other_sorters_get_no_recording_copy_option(run_sorter_kwargs):
    kwargs = run_sorter_kwargs("simple", sorter_params={"clusterer": "kmeans"})
    assert "delete_recording_dat" not in kwargs
    assert kwargs["clusterer"] == "kmeans"
