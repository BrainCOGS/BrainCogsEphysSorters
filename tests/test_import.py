"""Import smoke tests.

These run without a GPU and without the heavy sorting dependencies (torch,
kilosort, spikeinterface, ibllib): the package only imports those lazily,
inside the functions that need them.
"""

import importlib

import pytest

MODULES = [
    "u19_sorting",
    "u19_sorting.config",
    "u19_sorting.apptainer_exec",
    "u19_sorting.utils",
    "u19_sorting.preprocess_wrappers",
    "u19_sorting.sorter_wrappers",
    "u19_sorting.postprocess_wrappers",
    "u19_sorting.run_job",
    "u19_sorting.job_spec",
    "u19_sorting.si_wrappers",
    "u19_sorting.sorter_registry",
    "u19_sorting.apptainer_cache",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    assert importlib.import_module(name) is not None
