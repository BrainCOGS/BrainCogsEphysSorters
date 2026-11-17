"""run_postprocessing against the installed SpikeInterface, on a small generated recording."""

import warnings

import pytest

si = pytest.importorskip("spikeinterface.full")

from u19_sorting import si_wrappers  # noqa: E402

# SpikeInterface's FutureWarning for job (or sparsity) arguments given as keyword arguments
# of create_sorting_analyzer instead of in its job_kwargs (sparsity_kwargs) dict.
DEPRECATED_KWARGS = "via keyword arguments"


def test_analyzer_gets_job_kwargs_as_a_dict(tmp_path, monkeypatch):
    recording, sorting = si.generate_ground_truth_recording(
        durations=[2.0], num_channels=8, num_units=3, seed=0
    )
    create = si.create_sorting_analyzer
    calls = []

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return create(*args, **kwargs)

    monkeypatch.setattr(si, "create_sorting_analyzer", spy)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        analyzer = si_wrappers.run_postprocessing(
            recording,
            sorting,
            tmp_path / "kilosort2_output",
            {
                "extensions": {"quality_metrics": {}},
                "job_kwargs": {"n_jobs": 1, "chunk_duration": "1s"},
            },
            export_phy=False,
        )

    (kwargs,) = calls
    assert kwargs["job_kwargs"] == {"n_jobs": 1, "chunk_duration": "1s"}
    assert not {"n_jobs", "chunk_duration"} & set(kwargs)
    deprecated = [w for w in caught if DEPRECATED_KWARGS in str(w.message)]
    assert deprecated == []
    assert analyzer.has_extension("quality_metrics")
