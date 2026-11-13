"""The SpikeInterface path: reading SpikeGLX runs, the preprocessing step list, running a
sorter through `run_sorter`, postprocessing, and the output layout.

Whatever runs here, the result has to end up at `<processed_dir>/<clustering_method>_output`
as a Kilosort/phy folder, because that is what U19-pipeline-python hands to the DataJoint
element (`element_array_ephys/readers/kilosort.py`) and what the IBL atlas step opens.
Everything SpikeInterface adds (its run log, motion info, the sorting analyzer, quality
metrics) goes in the `spikeinterface/` subfolder, out of the element's way. In particular no
`metrics.csv` is written next to the phy files: the element reads that as "ecephys quality
control was run" and then expects a `mean_waveforms.npy` this path does not produce.

spikeinterface and torch are imported inside the functions, so legacy CatGT/Kilosort jobs
and the test suite never pay for (or need) them.
"""

import os
import pathlib
import re
import shutil

from u19_sorting import config, job_spec

# Subfolder of <clustering_method>_output that holds SpikeInterface's own files.
SI_SUBDIR = "spikeinterface"

# Extensions `export_to_phy` needs; computed even when the paramset does not list them.
PHY_EXTENSIONS = (
    "random_spikes",
    "waveforms",
    "templates",
    "noise_levels",
    "spike_amplitudes",
    "principal_components",
    "template_similarity",
)

# phy's own label for a cluster nobody has looked at. The element only knows
# good / ok / mua / noise (ClusterQualityLabel), so it is replaced on export.
PHY_UNSORTED = "unsorted"
DEFAULT_CLUSTER_LABEL = "mua"


def with_default_job_kwargs(job_kwargs):
    """SpikeInterface job kwargs with `n_jobs` defaulting to the CPUs slurm gave the job.

    A paramset is shared by every job that selects it, so it should not have to know how
    many cores the cluster job asked for: without `n_jobs`, SLURM_CPUS_PER_TASK is used
    (with 1 s chunks, unless the paramset sets a chunk size). Outside slurm, or in a job
    with a single CPU, nothing is added and SpikeInterface's own defaults apply.
    """

    job_kwargs = dict(job_kwargs or {})
    cpus = os.environ.get("SLURM_CPUS_PER_TASK", "")
    if "n_jobs" not in job_kwargs and cpus.isdigit() and int(cpus) > 1:
        job_kwargs["n_jobs"] = int(cpus)
        if not {"chunk_duration", "chunk_size", "chunk_memory", "total_memory"} & set(
            job_kwargs
        ):
            job_kwargs["chunk_duration"] = "1s"
    return job_kwargs


# ------------------------------------------------------------------ SpikeGLX reading/writing


def locate_spikeglx_ap(raw_directory):
    """(ap.meta path, file stem, neo stream id) of the SpikeGLX ap stream in a folder."""

    raw_directory = pathlib.Path(raw_directory)
    meta_files = sorted(raw_directory.glob("*ap.meta"))
    if not meta_files:
        raise ValueError("No *ap.meta found in " + raw_directory.as_posix())
    src_meta = meta_files[0]
    stem = src_meta.name[: -len(".ap.meta")]

    probe_match = re.search(r"imec([0-9]+)", src_meta.name)
    stream_id = ("imec" + probe_match.group(1) + ".ap") if probe_match else "imec0.ap"
    return src_meta, stem, stream_id


def read_recording(raw_directory):
    """Open the SpikeGLX ap stream in raw_directory (a raw run, or a preprocessing output).

    neo exposes the 384 probe channels here; the sync channel (SY0) is a separate stream.
    """

    import spikeinterface.extractors as se

    _, _, stream_id = locate_spikeglx_ap(raw_directory)
    return se.read_spikeglx(
        folder_path=pathlib.Path(raw_directory).as_posix(), stream_id=stream_id
    )


def read_sync_channel(raw_directory, stream_id, num_probe_channels):
    """Return a 1-channel recording of the SpikeGLX sync channel (SY0), or None.

    Newer neo exposes it as its own "<stream>-SYNC" stream; older spikeinterface/neo
    only include it via read_spikeglx(load_sync_channel=True), as the last channel of
    the probe stream (with no probe attached). Handle both so the output keeps the
    nSavedChans column count regardless of the installed version.
    """

    import spikeinterface.full as si

    folder = pathlib.Path(raw_directory).as_posix()

    stream_ids = si.get_neo_streams("spikeglx", folder)[1]
    if stream_id + "-SYNC" in stream_ids:
        return si.read_spikeglx(folder_path=folder, stream_id=stream_id + "-SYNC")

    try:
        rec_with_sync = si.read_spikeglx(
            folder_path=folder, stream_id=stream_id, load_sync_channel=True
        )
    except TypeError:
        return None  # neither API offers a sync channel
    if rec_with_sync.get_num_channels() != num_probe_channels + 1:
        return None
    return rec_with_sync.channel_slice([rec_with_sync.channel_ids[-1]])


def meta_file_size(meta_path):
    """fileSizeBytes of a SpikeGLX meta, or None if the tag is missing."""

    expected = re.search(
        r"^fileSizeBytes=(\d+)", pathlib.Path(meta_path).read_text(), flags=re.MULTILINE
    )
    return int(expected.group(1)) if expected is not None else None


def write_spikeglx_copy(rec, sync_rec, src_meta, output_dir, job_kwargs, label):
    """Write `rec` as a SpikeGLX-style int16 ap.bin next to a copy of `src_meta`.

    The sync channel is appended back, untouched, so the file keeps the nSavedChans columns
    its meta (and Kilosort's n_chan_bin) describe. Float traces are rounded, not truncated.
    Raises if the file written is not the size the meta expects.
    """

    import spikeinterface.full as si

    src_meta = pathlib.Path(src_meta)
    output_dir = pathlib.Path(output_dir)
    stem = src_meta.name[: -len(".ap.meta")]

    # Materialize a SpikeGLX-style ap.bin. write_binary_recording (not save()) writes a
    # single flat binary; KS4's find_binary globs *.bin and prefers the 'ap.bin' tag.
    corrected_bin = output_dir / (stem + ".ap.bin")
    rec_out = si.astype(rec, dtype="int16", round=True)
    if sync_rec is not None:
        # The sync channel has no probe, and spikeinterface >= 0.105 refuses to aggregate
        # recordings with and without one. A flat binary carries no probe, so drop it from
        # the (lazy, local) probe-channel wrapper. Older versions have no remove_probe and
        # aggregate mixed recordings as they are.
        if hasattr(rec_out, "remove_probe"):
            rec_out.remove_probe()
        rec_out = si.aggregate_channels([rec_out, sync_rec])
    print(label, "writing", rec_out.get_num_channels(), "channels ->", corrected_bin)
    si.write_binary_recording(
        rec_out,
        file_paths=[corrected_bin.as_posix()],
        dtype="int16",
        **job_kwargs,
    )

    # Copy the ap.meta alongside (provenance + lets read_spikeglx re-open on requeue).
    # None of the allowed steps changes the sample count, so the meta stays valid.
    shutil.copy2(src_meta.as_posix(), (output_dir / (stem + ".ap.meta")).as_posix())

    # Fail here, with a useful message, rather than later in Kilosort's file reader if the
    # channel count we wrote does not match what the meta (and KS4's n_chan_bin) describe.
    expected = meta_file_size(src_meta)
    if expected is not None and corrected_bin.stat().st_size != expected:
        raise ValueError(
            label
            + " wrote "
            + str(corrected_bin.stat().st_size)
            + " bytes ("
            + str(rec_out.get_num_channels())
            + " channels) but "
            + src_meta.name
            + " expects "
            + str(expected)
            + " bytes; channel count mismatch"
        )
    return corrected_bin


def spikeglx_copy_complete(output_dir, label):
    """True only if a complete written recording is present: an ap.bin next to an ap.meta
    whose fileSizeBytes matches the ap.bin on disk. A wrong-sized file (killed job, or an
    earlier run that dropped the sync channel) is removed so the next run regenerates it
    instead of feeding it to the sorter.
    """

    output_dir = pathlib.Path(output_dir)
    metas = sorted(output_dir.glob("*ap.meta")) if output_dir.is_dir() else []
    if not metas:
        return 0

    meta = metas[0]
    bin_file = meta.with_name(meta.name[: -len(".ap.meta")] + ".ap.bin")
    if not bin_file.is_file():
        return 0

    expected = meta_file_size(meta)
    if expected is None:
        return 1  # meta without size info: fall back to existence check

    if bin_file.stat().st_size == expected:
        return 1

    print(
        label + " output",
        bin_file,
        "is",
        bin_file.stat().st_size,
        "bytes, meta expects",
        str(expected),
        "-> discarding incomplete output",
    )
    bin_file.unlink()
    meta.unlink()
    return 0


# ------------------------------------------------------------------------ preprocessing


def default_torch_device(device=None):
    """'cuda' when asked for (or unset) and available, else 'cpu'."""

    import torch

    if device is None or device == "cuda":
        if torch.cuda.is_available():
            print("using CUDA device:", torch.cuda.get_device_name())
            return "cuda"
        print("CUDA not available, falling back to CPU")
        return "cpu"
    return device


def apply_correct_motion(recording, kwargs, motion_folder, job_kwargs):
    """The `correct_motion` step: DREDge by default, lazily interpolated."""

    import spikeinterface.full as si
    from spikeinterface.preprocessing.motion import correct_motion

    kwargs = dict(kwargs)
    kwargs.setdefault("preset", "dredge")
    estimate = dict(kwargs.pop("estimate_motion_kwargs", {}) or {})
    estimate["device"] = default_torch_device(estimate.get("device"))

    # InterpolateMotionRecording refuses integer traces.
    if recording.get_dtype().kind != "f":
        recording = si.astype(recording, dtype="float32")

    if motion_folder is not None:
        kwargs["folder"] = pathlib.Path(motion_folder).as_posix()
        kwargs["overwrite"] = True

    return correct_motion(
        recording, estimate_motion_kwargs=estimate, **kwargs, **job_kwargs
    )


def apply_steps(recording, steps, motion_folder=None, job_kwargs=None):
    """Chain SpikeInterface preprocessing functions, in the order of the list."""

    import spikeinterface.preprocessing as spre

    job_kwargs = job_kwargs or {}
    for step in steps:
        name, kwargs = step["name"], step["kwargs"]
        if name not in job_spec.SI_STEP_NAMES:
            raise job_spec.JobSpecError(f"unknown spikeinterface step {name!r}")
        print("spikeinterface step:", name, kwargs)
        if name in job_spec.MOTION_STEPS:
            recording = apply_correct_motion(
                recording, kwargs, motion_folder, job_kwargs
            )
        else:
            recording = getattr(spre, name)(recording, **kwargs)
    return recording


class spikeinterface_preproc:
    """The `spikeinterface` preprocessing method, written to disk.

    Reads the SpikeGLX ap stream of the previous step (or the raw run), applies the step
    list and writes the result as a SpikeGLX-style ap.bin + ap.meta in
    `spikeinterface_output`, so whatever comes next (CatGT, DREDge, any sorter) consumes it
    like a raw run. When the step list is the last preprocessing step of a namespaced sort
    nothing is written: the sort stage applies the steps lazily (see job_spec).
    """

    @staticmethod
    def run(raw_data_directory, output_dir, params):
        output_dir = pathlib.Path(output_dir)
        if spikeglx_copy_complete(output_dir, "spikeinterface"):
            print("spikeinterface output already present, skipping", output_dir)
            return output_dir

        raw_data_directory = pathlib.Path(raw_data_directory)
        output_dir.mkdir(parents=True, exist_ok=True)

        src_meta, _, stream_id = locate_spikeglx_ap(raw_data_directory)
        rec = read_recording(raw_data_directory)
        sync_rec = read_sync_channel(
            raw_data_directory, stream_id, rec.get_num_channels()
        )
        if sync_rec is None:
            print(
                "spikeinterface: no sync channel found for",
                stream_id,
                "- writing probe channels only",
            )

        job_kwargs = with_default_job_kwargs(params.get("job_kwargs"))
        rec = apply_steps(
            rec,
            params["steps"],
            motion_folder=output_dir / "motion",
            job_kwargs=job_kwargs,
        )
        write_spikeglx_copy(
            rec, sync_rec, src_meta, output_dir, job_kwargs, "spikeinterface"
        )
        return output_dir


# ------------------------------------------------------------------------------ sorting


def si_sorter_name(clustering_method):
    """SpikeInterface sorter name for a clustering_method, or a loud failure."""

    try:
        return config.si_sorters[clustering_method]
    except KeyError:
        raise job_spec.JobSpecError(
            f"clustering_method {clustering_method!r} has no SpikeInterface sorter "
            f"(known: {sorted(config.si_sorters)})"
        ) from None


def is_kilosort(sorter_name):
    return sorter_name.startswith("kilosort")


def validate_sorter_namespaces(sorter_name, sorter_params, si_params):
    """Fail before sorting if a key is not one the sorter (or SpikeInterface) takes.

    For Kilosort 4 the two namespaces are checked separately: `sorter_params` may only hold
    Kilosort settings, `si_params` only SpikeInterface's wrapper options and job kwargs.
    Kilosort 4 rejects unknown settings, and SpikeInterface silently routes by key name, so
    without this a wrapper option in the wrong namespace would not be noticed.
    """

    import spikeinterface.sorters as ss
    from spikeinterface.core.job_tools import job_keys

    defaults = set(ss.get_default_sorter_params(sorter_name))
    job_kwargs = set(job_keys)
    sorter_class = ss.sorter_dict[sorter_name]
    si_only = set(getattr(sorter_class, "_si_default_params", {}))

    if si_only:
        # The default params of a sorter that needs a binary file include the job kwargs
        # (n_jobs, chunk_duration, ...); those are SpikeInterface's, not the sorter's.
        allowed_sorter = defaults - si_only - job_kwargs
        allowed_si = si_only | job_kwargs
    else:
        allowed_sorter = defaults
        allowed_si = defaults | job_kwargs

    bad_sorter = sorted(set(sorter_params) - allowed_sorter)
    if bad_sorter:
        hint = ""
        if set(bad_sorter) & {"n_chan_bin", "fs"}:
            hint = " (n_chan_bin and fs come from the recording)"
        elif set(bad_sorter) & allowed_si:
            hint = " (SpikeInterface options belong in si_params)"
        raise job_spec.JobSpecError(
            f"sorter_params: {bad_sorter} are not {sorter_name} settings{hint}"
        )
    bad_si = sorted(set(si_params) - allowed_si)
    if bad_si:
        hint = (
            " (sorter settings belong in sorter_params)"
            if set(bad_si) & allowed_sorter
            else ""
        )
        raise job_spec.JobSpecError(
            f"si_params: {bad_si} are not SpikeInterface options for {sorter_name}{hint}"
        )


def run_sorter(sorting_spec, resolved, raw_directory, output_directory):
    """Sort through SpikeInterface's `run_sorter`; returns (recording, sorting).

    `resolved` is the pinned registry entry or None. A container entry runs in its cached
    Apptainer image; anything else runs in this environment. The phy files of a Kilosort
    sorter are moved up into output_directory (`<clustering_method>_output`); every other
    file SpikeInterface wrote goes in its `spikeinterface/` subfolder.
    """

    import spikeinterface.sorters as ss

    output_directory = pathlib.Path(output_directory)
    sorter_name = si_sorter_name(sorting_spec.clustering_method)

    sorter_params = dict(sorting_spec.sorter_params)
    si_params = dict(sorting_spec.si_params)
    if sorting_spec.disable_drift:
        namespace, override = job_spec.drift_override(
            sorting_spec.clustering_method, True
        )
        if namespace is None:
            print("motion already corrected;", sorter_name, "has no drift option")
        else:
            si_params.update(override)
            print("motion already corrected: passing", override, "to", sorter_name)
    # SpikeInterface's Kilosort wrappers copy the recording to recording.dat, which would
    # end up in the phy folder; phy reads temp_wh.dat, so drop the raw-sized copy unless
    # the paramset asks to keep it (as the container path of a legacy paramset does).
    if is_kilosort(sorter_name) and "delete_recording_dat" not in sorter_params:
        si_params.setdefault("delete_recording_dat", True)
    validate_sorter_namespaces(sorter_name, sorter_params, si_params)
    # Sorters that take a binary file (the Kilosorts) accept job kwargs for writing it.
    if "n_jobs" in ss.get_default_sorter_params(sorter_name):
        si_params = with_default_job_kwargs(si_params)

    si_dir = output_directory / SI_SUBDIR
    si_dir.mkdir(parents=True, exist_ok=True)

    recording = read_recording(raw_directory)
    recording = apply_steps(
        recording,
        sorting_spec.lazy_steps,
        motion_folder=si_dir / "motion",
        job_kwargs=with_default_job_kwargs(sorting_spec.lazy_job_kwargs),
    )

    work = output_directory.with_name(output_directory.name + "_si_work")
    kwargs = dict(
        sorter_name=sorter_name,
        folder=work.as_posix(),
        remove_existing_folder=True,
        verbose=True,
        raise_error=True,
    )
    if resolved is not None and resolved.entry.mode == "container":
        kwargs.update(
            singularity_image=str(resolved.sif_path),
            delete_container_files=True,
            installation_mode="no-install",
        )
        drop_image_requirements(recording, resolved.entry.key)
        print("running", resolved.entry.key, "in", resolved.sif_path)
    kwargs.update(sorter_params)
    kwargs.update(si_params)

    sorting = ss.run_sorter(recording=recording, **kwargs)
    adopt_sorter_folder(work, output_directory, flatten=is_kilosort(sorter_name))
    return recording, sorting


# Recording extra_requirements already in the sorter images (installed with spikeinterface).
IMAGE_PACKAGES = {"neo"}


def drop_image_requirements(recording, key):
    """SpikeInterface pip installs a recording's extra_requirements from PyPI inside the
    container (every neo reader, SpikeGLX included, asks for "neo"). Compute nodes are
    offline, so drop what the image already has and refuse anything else.
    """

    missing = sorted(set(recording.extra_requirements) - IMAGE_PACKAGES)
    if missing:
        raise ValueError(
            f"{key}: recording needs {missing}, which the image does not provide"
        )
    recording.extra_requirements = []


def adopt_sorter_folder(work, output_directory, flatten):
    """Move a `run_sorter` folder into the job's output layout.

    flatten=True (Kilosort): `work/sorter_output/*` are the phy files and go straight into
    output_directory; `params.py` is repointed at the new location of the data file.
    Everything else goes under `output_directory/spikeinterface/`.
    """

    work = pathlib.Path(work)
    output_directory = pathlib.Path(output_directory)
    si_dir = output_directory / SI_SUBDIR
    si_dir.mkdir(parents=True, exist_ok=True)

    sorter_output = work / "sorter_output"
    if not sorter_output.is_dir():
        raise RuntimeError(f"no sorter_output folder in {work}")

    if flatten:
        for item in sorted(sorter_output.iterdir()):
            _move_over(item, output_directory / item.name)
        sorter_output.rmdir()
        repoint_params_py(
            output_directory / "params.py", sorter_output, output_directory
        )
    for item in sorted(work.iterdir()):
        _move_over(item, si_dir / item.name)
    work.rmdir()


def _move_over(source, destination):
    """shutil.move that replaces what a previous (requeued) run left behind."""

    if destination.is_dir() and not destination.is_symlink():
        shutil.rmtree(destination)
    elif destination.exists():
        destination.unlink()
    shutil.move(source.as_posix(), destination.as_posix())


def repoint_params_py(params_file, old_dir, new_dir):
    """Kilosort wrote absolute paths under old_dir into params.py; they now live in new_dir."""

    params_file = pathlib.Path(params_file)
    if not params_file.is_file():
        return
    text = params_file.read_text()
    old = pathlib.Path(old_dir).as_posix()
    if old in text:
        params_file.write_text(text.replace(old, pathlib.Path(new_dir).as_posix()))


# -------------------------------------------------------------------------- postprocessing


def order_extensions(requested):
    """Add the extensions the requested ones depend on and order parents first."""

    from spikeinterface.core.sortinganalyzer import get_extension_class

    ordered = {}

    def add(name, kwargs):
        if name in ordered:
            return
        for dependency in get_extension_class(name).depend_on:
            options = dependency.split("|")
            if not any(o in ordered or o in requested for o in options):
                add(options[0], {})
            for option in options:
                if option in requested:
                    add(option, requested[option])
        ordered[name] = kwargs

    for name, kwargs in requested.items():
        add(name, kwargs)
    return ordered


def run_postprocessing(
    recording, sorting, output_directory, postprocessing, export_phy
):
    """Build a sorting analyzer, compute the extensions, save metrics, optionally export phy.

    export_phy is forced by the caller for sorters that do not write a phy folder
    themselves. For Kilosort the native folder already is the phy folder, so nothing is
    exported over it.
    """

    import spikeinterface.full as si

    output_directory = pathlib.Path(output_directory)
    si_dir = output_directory / SI_SUBDIR
    si_dir.mkdir(parents=True, exist_ok=True)
    job_kwargs = with_default_job_kwargs(postprocessing.get("job_kwargs"))

    requested = dict(postprocessing.get("extensions") or {})
    if export_phy:
        for name in PHY_EXTENSIONS:
            requested.setdefault(name, {})
    extensions = order_extensions(requested)
    print("spikeinterface postprocessing extensions:", list(extensions))

    analyzer = si.create_sorting_analyzer(
        sorting,
        recording,
        format="binary_folder",
        folder=(si_dir / "analyzer").as_posix(),
        sparse=True,
        overwrite=True,
        **job_kwargs,
    )
    if extensions:
        analyzer.compute(extensions, **job_kwargs)

    for name in ("quality_metrics", "template_metrics"):
        if analyzer.has_extension(name):
            analyzer.get_extension(name).get_data().to_csv(
                si_dir / (name + ".csv"), index_label="unit_id"
            )

    if export_phy:
        phy_tmp = output_directory.with_name(output_directory.name + "_phy_tmp")
        si.export_to_phy(
            analyzer,
            phy_tmp.as_posix(),
            copy_binary=False,
            remove_if_exists=True,
            verbose=False,
            **job_kwargs,
        )
        for item in sorted(phy_tmp.iterdir()):
            _move_over(item, output_directory / item.name)
        phy_tmp.rmdir()
        make_phy_folder_element_compatible(output_directory)
    return analyzer


def make_phy_folder_element_compatible(folder, default_label=DEFAULT_CLUSTER_LABEL):
    """Turn a SpikeInterface `export_to_phy` folder into one the element reader accepts.

    The element's Kilosort reader (and the IBL step) were written against Kilosort's own
    output, which differs from SpikeInterface's phy export in five ways:

      - Kilosort writes `templates_ind.npy`; SpikeInterface writes `template_ind.npy`.
      - Kilosort's `templates.npy` is dense (unit x sample x all channels) and the reader
        takes the argmax over its channel axis as an index into `channel_map`.
        SpikeInterface's is sparse, so it is expanded here and the sparse index removed
        (phy would otherwise apply it to the dense array).
      - `whitening_mat.npy` / `whitening_mat_inv.npy` are required; identity is written.
      - `cluster_group.tsv` says "unsorted", which is not a ClusterQualityLabel.
      - `amplitudes.npy` is signed (negative for negative-going spikes); Kilosort's is
        positive, and the IBL step's `noise_cutoff` fails on negative amplitudes. Its
        absolute value is written.
    """

    import numpy as np
    import pandas as pd

    folder = pathlib.Path(folder)
    n_channels = int(np.load(folder / "channel_map.npy").size)

    sparse_ind_file = folder / "template_ind.npy"
    if sparse_ind_file.is_file():
        sparse_ind = np.load(sparse_ind_file)
        sparse = np.load(folder / "templates.npy")
        dense = np.zeros(
            (sparse.shape[0], sparse.shape[1], n_channels), dtype="float32"
        )
        for unit in range(sparse.shape[0]):
            used = sparse_ind[unit] >= 0
            dense[unit][:, sparse_ind[unit][used]] = sparse[unit][:, used]
        np.save(folder / "templates.npy", dense)
        sparse_ind_file.unlink()
    n_templates = int(np.load(folder / "templates.npy", mmap_mode="r").shape[0])
    np.save(
        folder / "templates_ind.npy",
        np.tile(np.arange(n_channels, dtype="int64"), (n_templates, 1)),
    )

    for name in ("whitening_mat.npy", "whitening_mat_inv.npy"):
        if not (folder / name).is_file():
            np.save(folder / name, np.eye(n_channels, dtype="float64"))

    amplitudes_file = folder / "amplitudes.npy"
    if amplitudes_file.is_file():
        np.save(amplitudes_file, np.abs(np.load(amplitudes_file)))

    group_file = folder / "cluster_group.tsv"
    if group_file.is_file():
        groups = pd.read_csv(group_file, sep="\t")
        if "group" in groups:
            groups["group"] = groups["group"].replace(PHY_UNSORTED, default_label)
            groups.to_csv(group_file, sep="\t", index=False)
