"""One normalized description of a job, built from its two parameter files.

U19-pipeline-python writes `preprocess_paramset_<id>.json` (an ordered list of
`{method: params}`) and `process_paramset_<id>.json` (the clustering paramset plus
`clustering_method`). `load_job_spec` reads both and returns a `JobSpec` with
`preprocessing` (ordered steps), `sorting` and `postprocessing`. Everything that depends
on more than one stage is decided here, once:

  - a motion-correction step ran, so the sorter's own drift correction is turned off
    (`sorting.disable_drift`, applied with `drift_override`);
  - a trailing `spikeinterface` step in front of a SpikeInterface sort is not written to
    disk: it is applied lazily in the sort stage (`sorting.lazy_steps`).

Sorting paramsets come in two shapes:

  legacy      no `sorter_params` key. Everything except `clustering_method` (and the
              optional `sorter_version`) is passed to the sorter exactly as before.
  namespaced  `sorter_params` is present. Only `sorter_version`, `sorter_params`,
              `si_params`, `preprocessing`, `postprocessing` and `resources` are allowed
              next to `clustering_method`, and only `sorter_params` reaches the sorter. Runs
              through SpikeInterface. With `preprocessing` (a step list), this one
              paramset describes the whole run.

This module only needs the standard library, so it can be tested without the sorting
stack installed.
"""

import copy
import dataclasses
import json
import pathlib

from u19_sorting import config

# `precluster_method` names (the key of each element of the preprocess file).
CATGT = "catgt"
DREDGE = "dredge"
SPIKEINTERFACE = "spikeinterface"

# Methods that are accepted and do nothing. "Nothing" is a row of PreClusterMethod in the
# production database ("Do Nothing method") and most 2026 jobs use it.
NOOP_METHODS = {"nothing"}

# SpikeInterface preprocessing functions a `spikeinterface` step list may name. They all
# keep the channel count and the sampling rate, which the rest of the job relies on: the
# written ap.bin must match its ap.meta, and Kilosort's channel map must still index the
# raw file's channels for the DataJoint element. `correct_motion` is the motion step.
MOTION_STEPS = {"correct_motion"}
SI_STEP_NAMES = MOTION_STEPS | {
    "bandpass_filter",
    "blank_saturation",
    "center",
    "clip",
    "common_reference",
    "detect_and_interpolate_bad_channels",
    "detect_and_remove_artifacts",
    "filter",
    "gaussian_filter",
    "highpass_filter",
    "highpass_spatial_filter",
    "interpolate_bad_channels",
    "normalize_by_quantile",
    "notch_filter",
    "phase_shift",
    "remove_artifacts",
    "scale",
    "silence_periods",
    "whiten",
    "zscore",
}

_SI_PREPROC_KEYS = {"steps", "job_kwargs", "materialize", "disable_sorter_drift"}
_SI_STEP_KEYS = {"name", "kwargs"}
_NAMESPACED_KEYS = {
    "clustering_method",
    "sorter_version",
    "sorter_params",
    "si_params",
    "preprocessing",
    "postprocessing",
    "resources",
}
_POSTPROCESSING_KEYS = {"extensions", "export", "job_kwargs"}
EXPORT_FORMATS = {"phy"}

# run_sorter / run_sorter_container arguments the job sets itself; a paramset may not.
RESERVED_RUN_SORTER_PARAMS = {
    "sorter_name",
    "recording",
    "folder",
    "remove_existing_folder",
    "delete_output_folder",
    "verbose",
    "raise_error",
    "with_output",
    "docker_image",
    "singularity_image",
    "delete_container_files",
    "extra_requirements",
    "installation_mode",
    "spikeinterface_version",
    "spikeinterface_folder_source",
}


class JobSpecError(ValueError):
    """A parameter file that cannot be turned into a job."""


@dataclasses.dataclass
class PreprocStep:
    method: str
    params: dict
    # Only meaningful for `spikeinterface`: False means nothing is written for this step
    # (it is empty, or it is applied lazily in the sort stage).
    materialize: bool = True
    # Folder (inside the job's processed dir) this step writes: `<method>_output`, with a
    # numeric suffix from the second step of the same method on.
    output_name: str = ""


@dataclasses.dataclass
class SortingSpec:
    clustering_method: str
    legacy: bool
    sorter_version: str | None = None
    sorter_params: dict = dataclasses.field(default_factory=dict)
    si_params: dict = dataclasses.field(default_factory=dict)
    disable_drift: bool = False
    lazy_steps: list = dataclasses.field(default_factory=list)
    lazy_job_kwargs: dict = dataclasses.field(default_factory=dict)
    # A namespaced paramset's own `preprocessing` step list (normalized), or None. It is
    # what lets one paramset describe the whole run: read, preprocess, sort, postprocess.
    inline_preprocessing: dict | None = None


@dataclasses.dataclass
class JobSpec:
    preprocessing: list
    sorting: SortingSpec
    postprocessing: dict

    def step_params(self, method):
        """Params of the first `method` step, or None if the job has no such step."""

        for step in self.preprocessing:
            if step.method == method:
                return step.params
        return None


def _is_dict(value):
    return isinstance(value, dict)


def _dict_or_empty(value, what):
    if value is None:
        return {}
    if not _is_dict(value):
        raise JobSpecError(f"{what} must be an object, got {type(value).__name__}")
    return copy.deepcopy(value)


def normalize_spikeinterface_params(params):
    """Validate `{"steps": [{"name": ..., "kwargs": {...}}, ...]}` and fill the defaults."""

    if not _is_dict(params):
        raise JobSpecError(
            f'spikeinterface params must be {{"steps": [...]}}, got {type(params).__name__}'
        )
    unknown = sorted(set(params) - _SI_PREPROC_KEYS)
    if unknown:
        raise JobSpecError(
            f"spikeinterface params: unknown keys {unknown} (allowed: {sorted(_SI_PREPROC_KEYS)})"
        )
    if not isinstance(params.get("steps"), list):
        raise JobSpecError('spikeinterface params need a "steps" list')

    steps = []
    for index, step in enumerate(params["steps"]):
        where = f"spikeinterface step {index}"
        if not _is_dict(step):
            raise JobSpecError(
                f'{where} must be {{"name": ..., "kwargs": {{...}}}}, got {step!r}'
            )
        unknown = sorted(set(step) - _SI_STEP_KEYS)
        if unknown:
            raise JobSpecError(f"{where}: unknown keys {unknown}")
        name = step.get("name")
        if name not in SI_STEP_NAMES:
            raise JobSpecError(
                f"{where}: unknown step name {name!r} (allowed: {sorted(SI_STEP_NAMES)})"
            )
        kwargs = _dict_or_empty(step.get("kwargs"), f"{where} ({name}) kwargs")
        if "recording" in kwargs:
            raise JobSpecError(f"{where} ({name}): kwargs may not set 'recording'")
        steps.append({"name": name, "kwargs": kwargs})

    for flag in ("materialize", "disable_sorter_drift"):
        if flag in params and not isinstance(params[flag], bool):
            raise JobSpecError(f"spikeinterface params: {flag} must be true or false")

    return {
        "steps": steps,
        "job_kwargs": _dict_or_empty(
            params.get("job_kwargs"), "spikeinterface job_kwargs"
        ),
        "materialize": params.get("materialize", False),
        "disable_sorter_drift": params.get("disable_sorter_drift", True),
    }


def normalize_preprocessing(raw):
    """The preprocess file as an ordered list of PreprocStep."""

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise JobSpecError(
            f"preprocess params must be a list of {{method: params}}, got {type(raw).__name__}"
        )

    steps = []
    for index, element in enumerate(raw):
        if not _is_dict(element) or not element:
            raise JobSpecError(
                f"preprocess step {index} must be {{method: params}}, got {element!r}"
            )
        known = {CATGT, DREDGE, SPIKEINTERFACE}
        unknown = sorted(
            m for m in element if m not in known and str(m).lower() not in NOOP_METHODS
        )
        if unknown:
            raise JobSpecError(
                f"preprocess step {index}: unknown method {unknown} (known: {sorted(known)}, no-op: Nothing)"
            )
        if SPIKEINTERFACE in element and len(element) > 1:
            raise JobSpecError(
                f"preprocess step {index}: 'spikeinterface' must be alone in its list element"
            )

        # One element normally holds one method. The old loop checked 'catgt' and then
        # 'dredge' inside each element, so keep that order if both are there.
        if CATGT in element:
            steps.append(
                PreprocStep(CATGT, _dict_or_empty(element[CATGT], "catgt params"))
            )
        if DREDGE in element:
            steps.append(
                PreprocStep(DREDGE, _dict_or_empty(element[DREDGE], "dredge params"))
            )
        if SPIKEINTERFACE in element:
            steps.append(
                PreprocStep(
                    SPIKEINTERFACE,
                    normalize_spikeinterface_params(element[SPIKEINTERFACE]),
                )
            )
    return steps


def normalize_postprocessing(raw):
    """`{}` when there is nothing to do, else extensions / export / job_kwargs."""

    params = _dict_or_empty(raw, "postprocessing")
    if not params:
        return {}
    unknown = sorted(set(params) - _POSTPROCESSING_KEYS)
    if unknown:
        raise JobSpecError(
            f"postprocessing: unknown keys {unknown} (allowed: {sorted(_POSTPROCESSING_KEYS)})"
        )

    extensions = _dict_or_empty(params.get("extensions"), "postprocessing extensions")
    for name in extensions:
        extensions[name] = _dict_or_empty(
            extensions[name], f"postprocessing extension {name!r} kwargs"
        )

    export = params.get("export") or None
    if export is not None and export not in EXPORT_FORMATS:
        raise JobSpecError(
            f"postprocessing export must be one of {sorted(EXPORT_FORMATS)} or null, got {export!r}"
        )

    return {
        "extensions": extensions,
        "export": export,
        "job_kwargs": _dict_or_empty(
            params.get("job_kwargs"), "postprocessing job_kwargs"
        ),
    }


def normalize_sorting(raw):
    """The process file as (SortingSpec, postprocessing dict)."""

    if not _is_dict(raw):
        raise JobSpecError(
            f"process params must be an object with clustering_method, got {type(raw).__name__}"
        )
    clustering_method = raw.get("clustering_method")
    if not isinstance(clustering_method, str) or not clustering_method:
        raise JobSpecError(
            f"process params need a clustering_method, got {clustering_method!r}"
        )

    sorter_version = raw.get("sorter_version")
    if sorter_version is not None and not isinstance(sorter_version, str):
        raise JobSpecError(
            f"sorter_version must be a registry key or null, got {sorter_version!r}"
        )

    if "sorter_params" not in raw:
        # Legacy: every other key is a sorter setting, whatever it is called.
        sorter_params = {
            key: copy.deepcopy(value)
            for key, value in raw.items()
            if key not in ("clustering_method", "sorter_version")
        }
        return (
            SortingSpec(
                clustering_method=clustering_method,
                legacy=True,
                sorter_version=sorter_version,
                sorter_params=sorter_params,
            ),
            {},
        )

    unknown = sorted(set(raw) - _NAMESPACED_KEYS)
    if unknown:
        raise JobSpecError(
            f"namespaced process params: unknown keys {unknown}. Sorter settings go inside "
            f"sorter_params; allowed top-level keys are {sorted(_NAMESPACED_KEYS)}"
        )

    sorter_params = _dict_or_empty(raw["sorter_params"], "sorter_params")
    si_params = _dict_or_empty(raw.get("si_params"), "si_params")

    for name, params in (("sorter_params", sorter_params), ("si_params", si_params)):
        reserved = sorted(RESERVED_RUN_SORTER_PARAMS & set(params))
        if reserved:
            raise JobSpecError(f"{name} may not set run_sorter arguments: {reserved}")
    overlap = sorted(set(sorter_params) & set(si_params))
    if overlap:
        raise JobSpecError(f"keys in both sorter_params and si_params: {overlap}")

    # `resources` (cores, GPUs, memory, time) is for U19-pipeline-python, which turns it
    # into the job's slurm request before the job exists. Nothing here uses it: the
    # granted cores are read back from SLURM_CPUS_PER_TASK.
    _dict_or_empty(raw.get("resources"), "resources")

    inline_preprocessing = None
    if raw.get("preprocessing") is not None:
        if _is_dict(raw["preprocessing"]) and "materialize" in raw["preprocessing"]:
            raise JobSpecError(
                "preprocessing in a clustering paramset is always applied lazily; "
                "'materialize' only applies to a spikeinterface preprocess step"
            )
        inline_preprocessing = normalize_spikeinterface_params(raw["preprocessing"])

    return (
        SortingSpec(
            clustering_method=clustering_method,
            legacy=False,
            sorter_version=sorter_version,
            sorter_params=sorter_params,
            si_params=si_params,
            inline_preprocessing=inline_preprocessing,
        ),
        normalize_postprocessing(raw.get("postprocessing")),
    )


def _has_motion_step(si_params):
    return any(step["name"] in MOTION_STEPS for step in si_params["steps"])


def motion_disables_sorter_drift(preprocessing, inline_preprocessing=None):
    """True if a motion-correction step ran and did not ask to keep the sorter's own.

    The first motion step decides: the preprocess steps in order, then the clustering
    paramset's own `preprocessing` list.
    """

    for step in preprocessing:
        if step.method == DREDGE:
            return bool(step.params.get("disable_sorter_drift", True))
        if step.method == SPIKEINTERFACE and _has_motion_step(step.params):
            return bool(step.params["disable_sorter_drift"])
    if inline_preprocessing is not None and _has_motion_step(inline_preprocessing):
        return bool(inline_preprocessing["disable_sorter_drift"])
    return False


def drift_override(clustering_method, via_spikeinterface):
    """How to switch off a sorter's built-in drift correction.

    Returns (namespace, params): the params to merge into `sorter_params` or `si_params`,
    or (None, {}) when the sorter has nothing to switch off.

      - Kilosort 4 called directly, and MATLAB Kilosort 3: `nblocks = 0`.
      - MATLAB Kilosort 2: `reorder = 0` (it reorders batches instead).
      - Kilosort 2.5 / 3 / 4 run through SpikeInterface: SpikeInterface's own
        `do_correction = False`. Its Kilosort 2 wrapper has no drift parameter.
    """

    if via_spikeinterface:
        if clustering_method in ("kilosort2_5", "kilosort3", "kilosort4"):
            return "si_params", {"do_correction": False}
        return None, {}
    if clustering_method in ("kilosort3", "kilosort4"):
        return "sorter_params", {"nblocks": 0}
    if clustering_method == "kilosort2":
        return "sorter_params", {"reorder": 0}
    return None, {}


def build_job_spec(preprocess_parameters, process_parameters):
    """Normalize the contents of the two parameter files into a JobSpec."""

    preprocessing = normalize_preprocessing(preprocess_parameters)
    sorting, postprocessing = normalize_sorting(process_parameters)
    sorting.disable_drift = motion_disables_sorter_drift(
        preprocessing, sorting.inline_preprocessing
    )

    for index, step in enumerate(preprocessing):
        if step.method != SPIKEINTERFACE:
            continue
        steps = step.params["steps"]
        is_last = index == len(preprocessing) - 1
        lazy = is_last and not sorting.legacy and not step.params["materialize"]
        if lazy:
            sorting.lazy_steps = steps
            sorting.lazy_job_kwargs = step.params["job_kwargs"]
        step.materialize = bool(steps) and not lazy

    # The paramset's own step list runs after whatever the preprocess file left lazy.
    if sorting.inline_preprocessing is not None:
        sorting.lazy_steps = sorting.lazy_steps + sorting.inline_preprocessing["steps"]
        sorting.lazy_job_kwargs = {
            **sorting.lazy_job_kwargs,
            **sorting.inline_preprocessing["job_kwargs"],
        }

    seen = {}
    for step in preprocessing:
        seen[step.method] = seen.get(step.method, 0) + 1
        suffix = "" if seen[step.method] == 1 else f"_{seen[step.method]}"
        step.output_name = f"{config.preproc_tools[step.method]}_output{suffix}"

    return JobSpec(
        preprocessing=preprocessing, sorting=sorting, postprocessing=postprocessing
    )


def _read_json(filename):
    with open(filename) as f:
        return json.load(f)


def load_job_spec(recording_process_id, missing_preprocess_ok=False):
    """Read this job's two parameter files and return its JobSpec.

    missing_preprocess_ok: treat a job without a preprocess file as one without
    preprocessing (the sort stage always did; the preprocess stage needs the file).
    """

    preprocess_filename = pathlib.Path(
        config.preprocess_parameter_file.format(recording_process_id)
    )
    if missing_preprocess_ok and not preprocess_filename.is_file():
        preprocess_parameters = None
    else:
        preprocess_parameters = _read_json(preprocess_filename)
    process_parameters = _read_json(
        config.process_parameter_file.format(recording_process_id)
    )
    return build_job_spec(preprocess_parameters, process_parameters)
