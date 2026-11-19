"""One normalized description of a job, built from its parameter files.

U19-pipeline-python writes `preprocess_paramset_<id>.json` (an ordered list of
`{method: params}`), `process_paramset_<id>.json` (the clustering paramset plus
`clustering_method`) and, for a job that selected a post-processing step list,
`postprocess_paramset_<id>.json` (an ordered list of `{method: params}` like the
preprocess file). `load_job_spec` reads them and returns a `JobSpec` with `preprocessing`
(ordered steps), `sorting` and `postprocessing` (ordered steps). Everything that depends
on more than one stage is decided here, once:

  - a motion-correction step ran, so the sorter's own drift correction is turned off
    (`sorting.disable_drift`, applied with `drift_override`);
  - a trailing `spikeinterface` step in front of a SpikeInterface sort is not written to
    disk: it is applied lazily in the sort stage (`sorting.lazy_steps`);
  - a namespaced paramset's own `postprocessing` object becomes the first postprocessing
    step (a `spikeinterface` one), ahead of the steps of the postprocess file;
  - which recording the sorting analyzer is built on (`analyzer_recording_steps`).

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

# `postcluster_method` names (the key of each element of the postprocess file).
# `spikeinterface` builds a sorting analyzer and computes its extensions; `bombcell` labels
# the units good / mua / noise / non_soma with SpikeInterface's port of bombcell.
BOMBCELL = "bombcell"
POSTPROCESS_METHODS = {SPIKEINTERFACE, BOMBCELL}

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
_POSTPROCESSING_KEYS = {"extensions", "export", "job_kwargs", "recording_steps"}
EXPORT_FORMATS = {"phy"}
_BOMBCELL_KEYS = {
    "thresholds",
    "split_non_somatic",
    "extensions",
    "job_kwargs",
    "recording_steps",
}
BOMBCELL_SECTIONS = {"noise", "mua", "non-somatic"}
_BOMBCELL_THRESHOLD_KEYS = {"greater", "less", "abs"}

# `recording_steps` of a postprocessing step: the analyzer is built on the recording the
# sorter read, with these SpikeInterface steps applied lazily on top. AUTO adds a 300 Hz
# high-pass and a global median reference when the sorter read the raw, unfiltered run
# (no preprocessing written and no lazy steps), since waveforms, templates and every
# amplitude metric need filtered traces; otherwise nothing.
AUTO = "auto"
AUTO_RECORDING_STEPS = [
    {"name": "highpass_filter", "kwargs": {"freq_min": 300.0}},
    {
        "name": "common_reference",
        "kwargs": {"operator": "median", "reference": "global"},
    },
]

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
class PostprocStep:
    method: str
    params: dict
    # Where the step came from: "paramset" (the `postprocessing` object of a namespaced
    # clustering paramset) or "file" (the postprocess parameter file).
    source: str = "file"


@dataclasses.dataclass
class JobSpec:
    preprocessing: list
    sorting: SortingSpec
    # Ordered PostprocStep list; empty when the job has no postprocessing.
    postprocessing: list = dataclasses.field(default_factory=list)
    # Steps applied on top of the sorter's input recording before the analyzer is built,
    # or AUTO (see AUTO_RECORDING_STEPS). Only used when there is an analyzer.
    analyzer_recording_steps: list | str = dataclasses.field(default_factory=list)

    def step_params(self, method):
        """Params of the first `method` step, or None if the job has no such step."""

        for step in self.preprocessing:
            if step.method == method:
                return step.params
        return None

    def postprocess_params(self, method):
        """Params of the first `method` postprocessing step, or None."""

        for step in self.postprocessing:
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

    steps = normalize_si_steps(params["steps"], "spikeinterface")

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


def normalize_si_steps(raw_steps, what, allowed=None):
    """Validate a list of `{"name": ..., "kwargs": {...}}` SpikeInterface steps."""

    allowed = SI_STEP_NAMES if allowed is None else allowed
    if not isinstance(raw_steps, list):
        raise JobSpecError(
            f"{what} steps must be a list, got {type(raw_steps).__name__}"
        )
    steps = []
    for index, step in enumerate(raw_steps):
        where = f"{what} step {index}"
        if not _is_dict(step):
            raise JobSpecError(
                f'{where} must be {{"name": ..., "kwargs": {{...}}}}, got {step!r}'
            )
        unknown = sorted(set(step) - _SI_STEP_KEYS)
        if unknown:
            raise JobSpecError(f"{where}: unknown keys {unknown}")
        name = step.get("name")
        if name not in allowed:
            raise JobSpecError(
                f"{where}: unknown step name {name!r} (allowed: {sorted(allowed)})"
            )
        kwargs = _dict_or_empty(step.get("kwargs"), f"{where} ({name}) kwargs")
        if "recording" in kwargs:
            raise JobSpecError(f"{where} ({name}): kwargs may not set 'recording'")
        steps.append({"name": name, "kwargs": kwargs})
    return steps


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


def _extensions(raw, what):
    extensions = _dict_or_empty(raw, f"{what} extensions")
    for name in extensions:
        extensions[name] = _dict_or_empty(
            extensions[name], f"{what} extension {name!r} kwargs"
        )
    return extensions


def _recording_steps(params, what):
    """A step's `recording_steps`: None (not set), AUTO, or a normalized step list."""

    raw = params.get("recording_steps")
    if raw is None:
        return None
    if raw == AUTO:
        return AUTO
    # Motion correction re-estimates the motion: it belongs in preprocessing, where the
    # sorter sees it too.
    return normalize_si_steps(
        raw, f"{what} recording_steps", allowed=SI_STEP_NAMES - MOTION_STEPS
    )


def normalize_postprocessing(raw):
    """`{}` when there is nothing to do, else extensions / export / job_kwargs.

    The params of a `spikeinterface` postprocessing step, and the `postprocessing` object
    of a namespaced clustering paramset (which takes the same keys).
    """

    params = _dict_or_empty(raw, "postprocessing")
    if not params:
        return {}
    unknown = sorted(set(params) - _POSTPROCESSING_KEYS)
    if unknown:
        raise JobSpecError(
            f"postprocessing: unknown keys {unknown} (allowed: {sorted(_POSTPROCESSING_KEYS)})"
        )

    export = params.get("export") or None
    if export is not None and export not in EXPORT_FORMATS:
        raise JobSpecError(
            f"postprocessing export must be one of {sorted(EXPORT_FORMATS)} or null, got {export!r}"
        )

    normalized = {
        "extensions": _extensions(params.get("extensions"), "postprocessing"),
        "export": export,
        "job_kwargs": _dict_or_empty(
            params.get("job_kwargs"), "postprocessing job_kwargs"
        ),
    }
    recording_steps = _recording_steps(params, "postprocessing")
    if recording_steps is not None:
        normalized["recording_steps"] = recording_steps
    return normalized


def normalize_bombcell_thresholds(raw):
    """Threshold overrides, `{section: {metric: {"greater", "less", "abs"} | null}}`.

    They are applied on top of SpikeInterface's bombcell defaults when the job runs: a
    metric given here replaces the default one, and `null` drops it.
    """

    thresholds = _dict_or_empty(raw, "bombcell thresholds")
    unknown = sorted(set(thresholds) - BOMBCELL_SECTIONS)
    if unknown:
        raise JobSpecError(
            f"bombcell thresholds: unknown sections {unknown} (allowed: {sorted(BOMBCELL_SECTIONS)})"
        )
    for section, metrics in thresholds.items():
        metrics = _dict_or_empty(metrics, f"bombcell thresholds {section!r}")
        for metric, threshold in metrics.items():
            where = f"bombcell threshold {section}.{metric}"
            if threshold is None:
                continue
            if not _is_dict(threshold):
                raise JobSpecError(
                    f'{where} must be {{"greater": ..., "less": ...}} or null, got {threshold!r}'
                )
            bad = sorted(set(threshold) - _BOMBCELL_THRESHOLD_KEYS)
            if bad:
                raise JobSpecError(
                    f"{where}: unknown keys {bad} (allowed: {sorted(_BOMBCELL_THRESHOLD_KEYS)})"
                )
            for bound in ("greater", "less"):
                value = threshold.get(bound)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int | float)
                ):
                    raise JobSpecError(
                        f"{where}.{bound} must be a number or null, got {value!r}"
                    )
            if "abs" in threshold and not isinstance(threshold["abs"], bool):
                raise JobSpecError(f"{where}.abs must be true or false")
        thresholds[section] = metrics
    return thresholds


def normalize_bombcell(raw):
    """The params of a `bombcell` postprocessing step."""

    params = _dict_or_empty(raw, "bombcell params")
    unknown = sorted(set(params) - _BOMBCELL_KEYS)
    if unknown:
        raise JobSpecError(
            f"bombcell params: unknown keys {unknown} (allowed: {sorted(_BOMBCELL_KEYS)})"
        )
    split = params.get("split_non_somatic", False)
    if not isinstance(split, bool):
        raise JobSpecError("bombcell params: split_non_somatic must be true or false")

    normalized = {
        "thresholds": normalize_bombcell_thresholds(params.get("thresholds")),
        "split_non_somatic": split,
        "extensions": _extensions(params.get("extensions"), "bombcell"),
        "job_kwargs": _dict_or_empty(params.get("job_kwargs"), "bombcell job_kwargs"),
    }
    recording_steps = _recording_steps(params, "bombcell")
    if recording_steps is not None:
        normalized["recording_steps"] = recording_steps
    return normalized


def normalize_postprocess_steps(raw):
    """The postprocess file as an ordered list of PostprocStep (`[]` without one)."""

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise JobSpecError(
            f"postprocess params must be a list of {{method: params}}, got {type(raw).__name__}"
        )

    steps = []
    for index, element in enumerate(raw):
        if not _is_dict(element) or not element:
            raise JobSpecError(
                f"postprocess step {index} must be {{method: params}}, got {element!r}"
            )
        methods = [m for m in element if str(m).lower() not in NOOP_METHODS]
        unknown = sorted(m for m in methods if m not in POSTPROCESS_METHODS)
        if unknown:
            raise JobSpecError(
                f"postprocess step {index}: unknown method {unknown} "
                f"(known: {sorted(POSTPROCESS_METHODS)}, no-op: Nothing)"
            )
        if len(methods) > 1:
            raise JobSpecError(
                f"postprocess step {index}: one method per list element, got {sorted(methods)}"
            )
        for method in methods:
            if method == SPIKEINTERFACE:
                params = normalize_postprocessing(element[method])
                if not params:
                    continue  # an empty spikeinterface step has nothing to do
            else:
                params = normalize_bombcell(element[method])
            steps.append(PostprocStep(method, params, source="file"))
    return steps


def resolve_analyzer_recording_steps(steps):
    """The `recording_steps` the job's analyzer is built with.

    Steps that set it must agree, since all of them share one analyzer. Unset, it is AUTO
    when the job has a postprocess file step, and nothing (the recording exactly as the
    sorter read it, as before this option existed) for a paramset-only job.
    """

    explicit = [
        step.params["recording_steps"]
        for step in steps
        if "recording_steps" in step.params
    ]
    for other in explicit[1:]:
        if other != explicit[0]:
            raise JobSpecError(
                "postprocessing steps set different recording_steps; they share one "
                f"sorting analyzer, so they must agree: {explicit[0]!r} vs {other!r}"
            )
    if explicit:
        return copy.deepcopy(explicit[0])
    if any(step.source == "file" for step in steps):
        return AUTO
    return []


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


def build_job_spec(
    preprocess_parameters, process_parameters, postprocess_parameters=None
):
    """Normalize the contents of the parameter files into a JobSpec."""

    preprocessing = normalize_preprocessing(preprocess_parameters)
    sorting, paramset_postprocessing = normalize_sorting(process_parameters)
    postprocessing = normalize_postprocess_steps(postprocess_parameters)
    if paramset_postprocessing:
        postprocessing.insert(
            0, PostprocStep(SPIKEINTERFACE, paramset_postprocessing, source="paramset")
        )
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
        preprocessing=preprocessing,
        sorting=sorting,
        postprocessing=postprocessing,
        analyzer_recording_steps=resolve_analyzer_recording_steps(postprocessing),
    )


def _read_json(filename):
    with open(filename) as f:
        return json.load(f)


def load_job_spec(recording_process_id, missing_preprocess_ok=False):
    """Read this job's parameter files and return its JobSpec.

    missing_preprocess_ok: treat a job without a preprocess file as one without
    preprocessing (the sort stage always did; the preprocess stage needs the file).
    The postprocess file is optional: U19-pipeline-python only writes it for a job that
    selected a post-processing step list, and without it the job has no postprocessing
    beyond what its clustering paramset asks for.
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
    postprocess_filename = pathlib.Path(
        config.postprocess_parameter_file.format(recording_process_id)
    )
    postprocess_parameters = (
        _read_json(postprocess_filename) if postprocess_filename.is_file() else None
    )
    return build_job_spec(
        preprocess_parameters, process_parameters, postprocess_parameters
    )
