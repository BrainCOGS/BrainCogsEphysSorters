"""The job-spec loader: two parameter files in, one normalized spec out."""

import json

import pytest

from u19_sorting import config, job_spec
from u19_sorting.job_spec import JobSpecError

CATGT = {
    "apfilter": ["biquad", 2, 300, 0],
    "gfix": [0.4, 0.1, 0.02],
    "extras": ["prb_fld", "t_miss_ok", "ap", "gblcar", "out_prb_fld"],
}
SI_STEPS = {
    "steps": [
        {"name": "phase_shift", "kwargs": {}},
        {"name": "highpass_filter", "kwargs": {"freq_min": 300}},
        {
            "name": "common_reference",
            "kwargs": {"operator": "median", "reference": "global"},
        },
    ]
}
LEGACY_KS4 = {"clustering_method": "kilosort4", "n_chan_bin": 385}
NEW_KS4 = {
    "clustering_method": "kilosort4",
    "sorter_version": "kilosort4@4.1.7",
    "sorter_params": {"Th_universal": 9, "nblocks": 1},
    "si_params": {"save_preprocessed_copy": True},
    "postprocessing": {"extensions": {"quality_metrics": {}}, "export": "phy"},
}


def build(pre, proc):
    return job_spec.build_job_spec(pre, proc)


# --------------------------------------------------------------------------- preprocessing


def test_production_catgt_job_is_one_catgt_step():
    spec = build([{"catgt": CATGT}], LEGACY_KS4)
    assert [(s.method, s.params) for s in spec.preprocessing] == [("catgt", CATGT)]
    assert spec.sorting.disable_drift is False


def test_production_nothing_step_is_a_noop():
    """499 production jobs use the 'Nothing' method (with leftover CatGT params)."""
    spec = build([{"Nothing": CATGT}], LEGACY_KS4)
    assert spec.preprocessing == []


@pytest.mark.parametrize("raw", [None, []])
def test_no_preprocessing(raw):
    assert build(raw, LEGACY_KS4).preprocessing == []


def test_steps_keep_file_order():
    spec = build(
        [{"spikeinterface": SI_STEPS}, {"dredge": {}}, {"catgt": CATGT}], LEGACY_KS4
    )
    assert [s.method for s in spec.preprocessing] == [
        "spikeinterface",
        "dredge",
        "catgt",
    ]


def test_legacy_element_with_catgt_and_dredge_runs_catgt_first():
    """preprocess_main checked 'catgt' then 'dredge' inside one list element."""
    spec = build([{"dredge": {}, "catgt": CATGT}], LEGACY_KS4)
    assert [s.method for s in spec.preprocessing] == ["catgt", "dredge"]


def test_unknown_method_fails():
    with pytest.raises(JobSpecError, match="spikeinterfce"):
        build([{"spikeinterfce": SI_STEPS}], LEGACY_KS4)


@pytest.mark.parametrize("raw", ["catgt", {"catgt": CATGT}, [["catgt"]], [{}]])
def test_malformed_preprocess_file_fails(raw):
    with pytest.raises(JobSpecError):
        build(raw, LEGACY_KS4)


def test_null_dredge_params_become_empty():
    spec = build([{"dredge": None}], LEGACY_KS4)
    assert spec.preprocessing[0].params == {}


# ----------------------------------------------------------------- spikeinterface step list


def test_spikeinterface_steps_are_normalized_in_order():
    spec = build([{"spikeinterface": SI_STEPS}], LEGACY_KS4)
    (step,) = spec.preprocessing
    assert [s["name"] for s in step.params["steps"]] == [
        "phase_shift",
        "highpass_filter",
        "common_reference",
    ]
    assert step.params["steps"][0]["kwargs"] == {}
    assert step.params["steps"][1]["kwargs"] == {"freq_min": 300}


def test_empty_step_list_is_allowed():
    spec = build([{"spikeinterface": {"steps": []}}], LEGACY_KS4)
    assert spec.preprocessing[0].params["steps"] == []


@pytest.mark.parametrize(
    "step", [{"name": "phase_shift"}, {"name": "phase_shift", "kwargs": None}]
)
def test_missing_or_null_kwargs_become_empty(step):
    spec = build([{"spikeinterface": {"steps": [step]}}], LEGACY_KS4)
    assert spec.preprocessing[0].params["steps"] == [
        {"name": "phase_shift", "kwargs": {}}
    ]


def test_unknown_step_name_fails():
    with pytest.raises(JobSpecError, match="highpas_filter"):
        build([{"spikeinterface": {"steps": [{"name": "highpas_filter"}]}}], LEGACY_KS4)


@pytest.mark.parametrize(
    "params",
    [
        None,
        {},
        {"steps": None},
        {"steps": {"phase_shift": {}}},
        {"steps": ["phase_shift"]},
        {"steps": [{"kwargs": {}}]},
        {"steps": [{"name": "phase_shift", "kwargs": []}]},
        {"steps": [{"name": "phase_shift", "kwarg": {}}]},
        {"steps": [], "stepz": []},
        {"steps": [], "job_kwargs": 4},
        {"steps": [], "materialize": "yes"},
    ],
)
def test_malformed_spikeinterface_params_fail(params):
    with pytest.raises(JobSpecError):
        build([{"spikeinterface": params}], LEGACY_KS4)


def test_step_kwargs_may_not_pass_a_recording():
    with pytest.raises(JobSpecError, match="recording"):
        build(
            [
                {
                    "spikeinterface": {
                        "steps": [{"name": "phase_shift", "kwargs": {"recording": 1}}]
                    }
                }
            ],
            LEGACY_KS4,
        )


# --------------------------------------------------------------- legacy / namespaced split


def test_legacy_flat_paramset_passes_everything_but_the_method():
    spec = build([], {"clustering_method": "kilosort4", "n_chan_bin": 385, "Th": 9})
    s = spec.sorting
    assert s.legacy is True
    assert s.clustering_method == "kilosort4"
    assert s.sorter_params == {"n_chan_bin": 385, "Th": 9}
    assert s.sorter_version is None
    assert s.si_params == {}
    assert spec.postprocessing == {}


def test_legacy_flat_paramset_may_pin_a_version():
    """PR #7 shape: flat params plus sorter_version, which never reaches the sorter."""
    spec = build(
        [],
        {
            "clustering_method": "kilosort3",
            "sorter_version": "kilosort3@3.0.2",
            "detect_threshold": 6,
        },
    )
    assert spec.sorting.legacy is True
    assert spec.sorting.sorter_version == "kilosort3@3.0.2"
    assert spec.sorting.sorter_params == {"detect_threshold": 6}


def test_legacy_keys_that_look_new_are_still_sorter_params():
    """Without `sorter_params` nothing is interpreted: it all goes to the sorter as today."""
    spec = build([], {"clustering_method": "kilosort4", "postprocessing": {"a": 1}})
    assert spec.sorting.sorter_params == {"postprocessing": {"a": 1}}
    assert spec.postprocessing == {}


def test_namespaced_paramset_is_split():
    spec = build([], NEW_KS4)
    s = spec.sorting
    assert s.legacy is False
    assert s.sorter_version == "kilosort4@4.1.7"
    assert s.sorter_params == {"Th_universal": 9, "nblocks": 1}
    assert s.si_params == {"save_preprocessed_copy": True}
    assert spec.postprocessing == {
        "extensions": {"quality_metrics": {}},
        "export": "phy",
        "job_kwargs": {},
    }


def test_minimal_namespaced_paramset():
    spec = build([], {"clustering_method": "kilosort4", "sorter_params": {}})
    s = spec.sorting
    assert (s.legacy, s.sorter_version, s.sorter_params, s.si_params) == (
        False,
        None,
        {},
        {},
    )
    assert spec.postprocessing == {}


@pytest.mark.parametrize(
    "key", ["sorter_version", "sorter_params", "si_params", "postprocessing"]
)
def test_null_namespaced_values_are_defaults(key):
    params = {**NEW_KS4, key: None}
    spec = build([], params)
    assert spec.sorting.legacy is False
    if key == "sorter_version":
        assert spec.sorting.sorter_version is None
    elif key == "postprocessing":
        assert spec.postprocessing == {}
    else:
        assert getattr(spec.sorting, key) == {}


def test_namespaced_unknown_key_fails():
    with pytest.raises(JobSpecError, match="Th_universal"):
        build([], {**NEW_KS4, "Th_universal": 9})


@pytest.mark.parametrize(
    "bad",
    [
        {"sorter_params": [1]},
        {"si_params": "x"},
        {"postprocessing": []},
        {"sorter_version": 4},
        {"postprocessing": {"metrics": {}}},
        {"postprocessing": {"export": "nwb"}},
        {"postprocessing": {"extensions": ["waveforms"]}},
        {"postprocessing": {"extensions": {"waveforms": 3}}},
    ],
)
def test_malformed_namespaced_values_fail(bad):
    with pytest.raises(JobSpecError):
        build([], {**NEW_KS4, **bad})


def test_null_extension_kwargs_become_empty():
    spec = build([], {**NEW_KS4, "postprocessing": {"extensions": {"templates": None}}})
    assert spec.postprocessing["extensions"] == {"templates": {}}
    assert spec.postprocessing["export"] is None


def test_si_params_may_not_set_run_sorter_arguments():
    with pytest.raises(JobSpecError, match="singularity_image"):
        build([], {**NEW_KS4, "si_params": {"singularity_image": "x.sif"}})


def test_sorter_params_and_si_params_may_not_overlap():
    with pytest.raises(JobSpecError, match="do_correction"):
        build(
            [],
            {
                **NEW_KS4,
                "sorter_params": {"do_correction": False},
                "si_params": {"do_correction": True},
            },
        )


@pytest.mark.parametrize(
    "proc", [None, [], "kilosort4", {"n_chan_bin": 385}, {"clustering_method": 4}]
)
def test_process_file_needs_a_clustering_method(proc):
    with pytest.raises(JobSpecError):
        build([], proc)


def test_inputs_are_not_mutated():
    pre = [{"dredge": {}}]
    proc = json.loads(json.dumps(NEW_KS4))
    before = json.dumps([pre, proc], sort_keys=True)
    build(pre, proc)
    assert json.dumps([pre, proc], sort_keys=True) == before


# -------------------------------------------------------------------- cross-stage: motion


def test_dredge_turns_off_sorter_drift():
    assert build([{"dredge": {}}], LEGACY_KS4).sorting.disable_drift is True


def test_dredge_can_keep_sorter_drift():
    spec = build([{"dredge": {"disable_sorter_drift": False}}], LEGACY_KS4)
    assert spec.sorting.disable_drift is False


def test_spikeinterface_motion_step_turns_off_sorter_drift():
    params = {"steps": [{"name": "correct_motion", "kwargs": {"preset": "dredge"}}]}
    assert build([{"spikeinterface": params}], NEW_KS4).sorting.disable_drift is True
    params["disable_sorter_drift"] = False
    assert build([{"spikeinterface": params}], NEW_KS4).sorting.disable_drift is False


def test_filter_only_spikeinterface_step_keeps_sorter_drift():
    spec = build([{"spikeinterface": SI_STEPS}], NEW_KS4)
    assert spec.sorting.disable_drift is False


@pytest.mark.parametrize(
    ("method", "via_si", "expected"),
    [
        ("kilosort4", False, ("sorter_params", {"nblocks": 0})),
        ("kilosort3", False, ("sorter_params", {"nblocks": 0})),
        ("kilosort2", False, ("sorter_params", {"reorder": 0})),
        ("kilosort4", True, ("si_params", {"do_correction": False})),
        ("kilosort2_5", True, ("si_params", {"do_correction": False})),
        ("kilosort2", True, (None, {})),
        ("spykingcircus2", True, (None, {})),
    ],
)
def test_drift_override_per_sorter(method, via_si, expected):
    assert job_spec.drift_override(method, via_si) == expected


# ------------------------------------------------------- cross-stage: lazy SI preprocessing


def test_trailing_spikeinterface_step_is_lazy_for_a_namespaced_sort():
    spec = build([{"catgt": CATGT}, {"spikeinterface": SI_STEPS}], NEW_KS4)
    assert [s.materialize for s in spec.preprocessing] == [True, False]
    assert spec.sorting.lazy_steps == spec.preprocessing[1].params["steps"]


def test_spikeinterface_step_is_written_out_for_a_legacy_sort():
    spec = build([{"spikeinterface": SI_STEPS}], LEGACY_KS4)
    assert spec.preprocessing[0].materialize is True
    assert spec.sorting.lazy_steps == []


def test_spikeinterface_step_before_another_tool_is_written_out():
    spec = build([{"spikeinterface": SI_STEPS}, {"dredge": {}}], NEW_KS4)
    assert spec.preprocessing[0].materialize is True
    assert spec.sorting.lazy_steps == []


def test_materialize_can_be_forced():
    spec = build([{"spikeinterface": {**SI_STEPS, "materialize": True}}], NEW_KS4)
    assert spec.preprocessing[0].materialize is True
    assert spec.sorting.lazy_steps == []


def test_empty_trailing_step_list_writes_nothing_and_defers_nothing():
    spec = build([{"spikeinterface": {"steps": []}}], NEW_KS4)
    assert spec.preprocessing[0].materialize is False
    assert spec.sorting.lazy_steps == []


# ------------------------------------------------------------------------------ file loader


@pytest.fixture
def param_files(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config, "process_parameter_file", str(tmp_path / "process_paramset_{}.json")
    )
    monkeypatch.setattr(
        config,
        "preprocess_parameter_file",
        str(tmp_path / "preprocess_paramset_{}.json"),
    )

    def write(pre, proc, rp_id=7):
        (tmp_path / f"preprocess_paramset_{rp_id}.json").write_text(json.dumps(pre))
        (tmp_path / f"process_paramset_{rp_id}.json").write_text(json.dumps(proc))

    return write


def test_load_job_spec_reads_both_files(param_files):
    param_files([{"catgt": CATGT}], LEGACY_KS4)
    spec = job_spec.load_job_spec(7)
    assert spec.preprocessing[0].method == "catgt"
    assert spec.sorting.sorter_params == {"n_chan_bin": 385}


def test_load_job_spec_missing_file(param_files):
    with pytest.raises(FileNotFoundError):
        job_spec.load_job_spec(8)


def test_load_job_spec_rejects_nan_file(param_files, tmp_path):
    """Three production files hold a bare NaN."""
    param_files([], LEGACY_KS4)
    (tmp_path / "process_paramset_7.json").write_text("NaN")
    with pytest.raises(JobSpecError):
        job_spec.load_job_spec(7)
