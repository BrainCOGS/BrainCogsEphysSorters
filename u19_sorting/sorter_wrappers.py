import importlib.metadata
import json
import pathlib
import subprocess

from u19_sorting import apptainer_exec, config, job_spec, si_wrappers, sorter_registry
from u19_sorting.utils import write_file

# Written next to the sorter output when the job pinned a "sorter_version".
PROVENANCE_FILENAME = "sorter_provenance.json"

# Python package whose installed version a native registry entry pins.
NATIVE_PACKAGES = {"kilosort4": "kilosort"}

# Legacy sorters with a runner of their own in this module (MATLAB or the Kilosort 4
# package). Any other legacy sorter needs a container sorter_version.
NATIVE_RUNNERS = {"kilosort2", "kilosort3", "kilosort4"}


def sorter_main(recording_process_id, raw_directory, processed_directory, spec=None):
    """Main function to call appropiate sorter
    Args:
        recording_process_id        (int):   Job id; names the parameter and chanmap files
        raw_directory               (str):   Directory where raw (or preprocessed) data is located
        processed_directory         (str):   Directory where processed data will be stored
        spec                        (JobSpec): The job spec, if the caller already loaded it

    A legacy (flat) paramset runs exactly as it always has: the native Kilosort 4 call or
    the MATLAB Kilosort 2/3 scripts, or a pinned container if `sorter_version` names one.
    A namespaced paramset (one with `sorter_params`) runs through SpikeInterface.
    Either way the result is `<processed_directory>/<clustering_method>_output`.
    """

    if spec is None:
        spec = job_spec.load_job_spec(recording_process_id, missing_preprocess_ok=True)
    sorting = spec.sorting
    clustering_method = sorting.clustering_method

    if clustering_method == "SpikeInterface":
        raise job_spec.JobSpecError(
            'clustering_method "SpikeInterface" is not a sorter. Name the sorter itself '
            f"({sorted(config.si_sorters)}) and put its settings under sorter_params to "
            "run it through SpikeInterface."
        )
    if sorting.legacy and clustering_method not in config.sorters_names:
        raise job_spec.JobSpecError(
            f"clustering_method {clustering_method!r} is not a legacy sorter "
            f"({sorted(config.sorters_names)}). Sorters run through SpikeInterface need a "
            "namespaced paramset (settings under sorter_params)."
        )
    if not sorting.legacy:
        si_wrappers.si_sorter_name(
            clustering_method
        )  # unknown sorter: fail before sorting

    # Optional pinned sorter version: an allow-listed key from sorter_registry.json. Resolved
    # before anything runs so an unknown key, a drifted env or an uncached image fails the job
    # right away instead of silently running something else.
    resolved = resolve_sorter_version(clustering_method, sorting.sorter_version)

    in_container = resolved is not None and resolved.entry.mode == "container"
    if sorting.legacy and not in_container and clustering_method not in NATIVE_RUNNERS:
        raise job_spec.JobSpecError(
            f"{clustering_method} only runs in a container: pin a container "
            "sorter_version from sorter_registry.json"
        )

    sorter_processed_directory = pathlib.Path(
        processed_directory, clustering_method + "_output"
    )
    pathlib.Path(sorter_processed_directory).mkdir(parents=True, exist_ok=True)

    if sorting.legacy:
        run_legacy_sorter(
            recording_process_id,
            sorting,
            resolved,
            raw_directory,
            sorter_processed_directory,
        )
    else:
        run_spikeinterface_sorter(
            spec, resolved, raw_directory, sorter_processed_directory
        )

    if resolved is not None:
        write_provenance(resolved, sorter_processed_directory)

    print(clustering_method, " this is the sorter")
    params_file_for_different_os(sorter_processed_directory)

    return sorter_processed_directory


def run_legacy_sorter(
    recording_process_id, sorting, resolved, raw_directory, sorter_processed_directory
):
    """A flat paramset: every key but clustering_method goes to the sorter, as it always has."""

    process_parameters_filename = config.process_parameter_file.format(
        recording_process_id
    )
    chanmap_filename = config.chanmap_file.format(recording_process_id)
    sorter = config.sorters_names[sorting.clustering_method]
    in_container = resolved is not None and resolved.entry.mode == "container"

    process_parameters = dict(sorting.sorter_params)

    # If a motion-correction step ran in preprocessing, motion is already corrected. By
    # default disable Kilosort's own internal drift correction so motion is not corrected
    # twice; set "disable_sorter_drift": false in the motion step's params to keep both.
    if sorting.disable_drift:
        _, override = job_spec.drift_override(sorting.clustering_method, in_container)
        process_parameters.update(override)
        print(
            "motion-correction preprocessing detected: passing",
            override,
            "to",
            sorter,
        )

    # The MATLAB sorters and Kilosort 4 read their settings from this file, which must not
    # hold clustering_method / sorter_version (Kilosort 4 rejects unknown keys).
    params_text = json.dumps(process_parameters)
    print("new params")
    print(params_text)
    write_file(process_parameters_filename, params_text)

    if in_container:
        SpikeInterfaceContainer.run(
            resolved, raw_directory, sorter_processed_directory, process_parameters
        )
    elif sorter == config.sorters_names["kilosort2"]:
        Kilosort2.run_Kilosort2(
            raw_directory,
            sorter_processed_directory,
            process_parameters_filename,
            chanmap_filename,
        )
    elif sorter == config.sorters_names["kilosort3"]:
        Kilosort3.run_Kilosort3(
            raw_directory,
            sorter_processed_directory,
            process_parameters_filename,
            chanmap_filename,
        )
    elif sorter == config.sorters_names["kilosort4"]:
        print("running Kilosort 4 here xxxxxxxx")
        Kilosort4.run_Kilosort4(
            raw_directory,
            sorter_processed_directory,
            process_parameters_filename,
            chanmap_filename,
        )


def run_spikeinterface_sorter(
    spec, resolved, raw_directory, sorter_processed_directory
):
    """A namespaced paramset: sort through SpikeInterface, then its postprocessing."""

    sorter_name = si_wrappers.si_sorter_name(spec.sorting.clustering_method)
    recording, sorting_result = si_wrappers.run_sorter(
        spec.sorting, resolved, raw_directory, sorter_processed_directory
    )

    # A sorter that is not Kilosort leaves no phy folder, so one is always exported:
    # that folder is what the DataJoint element and the IBL step read.
    needs_phy = not si_wrappers.is_kilosort(sorter_name)
    wants_phy = spec.postprocessing.get("export") == "phy"
    if wants_phy and not needs_phy:
        print(sorter_name, "already wrote a phy folder; not exporting over it")
    if spec.postprocessing or needs_phy:
        si_wrappers.run_postprocessing(
            recording,
            sorting_result,
            sorter_processed_directory,
            spec.postprocessing,
            export_phy=needs_phy,
        )


def installed_version(package):
    """Installed version of a python package, or None if it isn't installed."""

    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def resolve_sorter_version(clustering_method, key):
    """Resolve the job's "sorter_version" registry key, or None when it doesn't pin one.

    Checks that the entry is for this clustering_method and that what is installed (the
    sorter package, or the host SpikeInterface for a container) matches the entry.
    """

    if key is None:
        return None

    resolved = sorter_registry.resolve(key)
    entry = resolved.entry

    if entry.sorter != clustering_method:
        raise sorter_registry.SorterRegistryError(
            f"sorter_version {key} runs {entry.sorter}, but clustering_method is {clustering_method}"
        )

    if entry.mode == "native":
        package = NATIVE_PACKAGES[entry.sorter]
        installed = installed_version(package)
        if installed is None:
            raise sorter_registry.SorterRegistryError(
                f"sorter_version {key}: {package} is not installed"
            )
        if installed != entry.version:
            raise sorter_registry.SorterRegistryError(
                f"sorter_version {key} pins {package} {entry.version}, but {installed} is installed"
            )
    else:
        # The host serializes the recording; the SpikeInterface baked into the image loads it.
        host_si = installed_version("spikeinterface")
        if host_si != entry.spikeinterface:
            raise sorter_registry.SorterRegistryError(
                f"sorter_version {key}: image has spikeinterface {entry.spikeinterface}, host has {host_si}"
            )

    print("sorter_version", key, "->", resolved.provenance())
    return resolved


def write_provenance(resolved, sorter_processed_directory):
    """Record exactly which sorter build produced this output."""

    provenance = resolved.provenance()
    if resolved.entry.mode == "native":
        provenance["installed_version"] = installed_version(
            NATIVE_PACKAGES[resolved.entry.sorter]
        )
    else:
        provenance["host_spikeinterface"] = installed_version("spikeinterface")

    provenance_file = pathlib.Path(sorter_processed_directory, PROVENANCE_FILENAME)
    with open(provenance_file, "w") as f:
        json.dump(provenance, f, indent=4)


class Kilosort2:
    """Kilosort2 caller functions"""

    # This library directory
    ks2_directory = pathlib.Path(
        config.sorters_dir, config.sorters_names["kilosort2"]
    ).as_posix()

    @staticmethod
    def run_Kilosort2(
        raw_directory, processed_directory, process_parameter_filename, chanmap_filename
    ):
        """Function that calls Kilosort2

        Args:
            raw_directory               (str):   Directory where raw (or preprocessed) data is located
            processed_directory         (str):   Directory where processed data will be stored
            process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        ks2_command = Kilosort2.create_Kilosort2_command(
            raw_directory,
            processed_directory,
            process_parameter_filename,
            chanmap_filename,
        )
        print("ks2_command .....", ks2_command)
        p = subprocess.run(ks2_command, text=True, shell=True, capture_output=True)

        print("stderr here", p.stderr)
        print("stdout", p.stdout)

        if p.returncode:
            raise Exception(p.stderr)

    '''
    @staticmethod
    def create_Kilosort2_run_script(raw_directory, processed_directory, process_parameter_filename, chanmap_filename):
        """ Function that creates the a .m script that add paths and run kilosort2 script

            Args:
                raw_directory               (str):   Directory where raw (or preprocessed) data is located
                processed_directory         (str):   Directory where processed data will be stored
                process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        matlab_command = "addpath(genpath('" + Kilosort2.ks2_directory + "'));\n \
        addpath('" + config.matlab_scripts.as_posix() + "');\n \
        run_ks2('" + process_parameter_filename + "','" \
            + raw_directory.as_posix() + "','"  + processed_directory.as_posix() + "','"\
                + chanmap_filename + "'); exit"
        with open(config.run_ks_filepath, "w") as f:
            f.write(matlab_command)
    '''

    @staticmethod
    def create_Kilosort2_command(
        raw_directory, processed_directory, process_parameter_filename, chanmap_filename
    ):
        """Function that creates the command to call matlab kilosort2 script

        Args:
            raw_directory               (str):   Directory where raw (or preprocessed) data is located
            processed_directory         (str):   Directory where processed data will be stored
            process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        # ks2_command =  ['matlab', '-nodisplay', '-nosplash', '-r', "' disp(pwd); addpath(genpath(pwd)); " + config.run_ks_script + "; exit'"]
        # ks2_command = ' '.join(ks2_command)

        matlab_command = (
            "addpath(genpath('"
            + Kilosort2.ks2_directory
            + "'));  \
        addpath('"
            + config.matlab_scripts.as_posix()
            + "'); \
        run_ks2('"
            + process_parameter_filename
            + "','"
            + raw_directory.as_posix()
            + "','"
            + processed_directory.as_posix()
            + "','"
            + chanmap_filename
            + "'); exit"
        )

        ks2_command = ["matlab", "-nodisplay", "-nosplash", "-r"]
        ks2_command = " ".join(ks2_command)
        ks2_command += ' "'
        ks2_command += matlab_command
        ks2_command += '"'

        return ks2_command


class Kilosort3:
    """Kilosort caller functions"""

    # This library directory
    ks_directory = pathlib.Path(
        config.sorters_dir, config.sorters_names["kilosort3"]
    ).as_posix()

    @staticmethod
    def run_Kilosort3(
        raw_directory, processed_directory, process_parameter_filename, chanmap_filename
    ):
        """Function that calls Kilosort

        Args:
            raw_directory               (str):   Directory where raw (or preprocessed) data is located
            processed_directory         (str):   Directory where processed data will be stored
            process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        ks_command = Kilosort3.create_Kilosort3_command(
            raw_directory,
            processed_directory,
            process_parameter_filename,
            chanmap_filename,
        )
        print("ks_command .....", ks_command)
        print("kilosort3 here .............................")
        p = subprocess.run(ks_command, text=True, shell=True, capture_output=True)

        print("stderr here", p.stderr)
        print("stdout", p.stdout)

        if p.returncode:
            raise Exception(p.stderr)

    @staticmethod
    def create_Kilosort3_command(
        raw_directory, processed_directory, process_parameter_filename, chanmap_filename
    ):
        """Function that creates the command to call matlab kilosort2 script

        Args:
            raw_directory               (str):   Directory where raw (or preprocessed) data is located
            processed_directory         (str):   Directory where processed data will be stored
            process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        matlab_command = (
            "addpath(genpath('"
            + Kilosort3.ks_directory
            + "'));  \
        addpath('"
            + config.matlab_scripts.as_posix()
            + "'); \
        kilosortbatch('"
            + process_parameter_filename
            + "','"
            + raw_directory.as_posix()
            + "','"
            + processed_directory.as_posix()
            + "','"
            + chanmap_filename
            + "'); exit"
        )

        ks_command = ["matlab", "-nodisplay", "-nosplash", "-r"]
        ks_command = " ".join(ks_command)
        ks_command += ' "'
        ks_command += matlab_command
        ks_command += '"'

        return ks_command


class Kilosort4:
    """Kilosort caller functions"""

    # This library directory
    # ks_directory = pathlib.Path(config.sorters_dir, config.sorters_names['kilosort4']).as_posix()

    @staticmethod
    def run_Kilosort4(
        raw_directory, processed_directory, process_parameter_filename, chanmap_filename
    ):
        """Function that calls Kilosort

        Args:
            raw_directory               (str):   Directory where raw (or preprocessed) data is located
            processed_directory         (str):   Directory where processed data will be stored
            process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        import importlib.metadata

        import kilosort

        # Get the version of the package kilosort
        package_name = "kilosort"
        version = importlib.metadata.version(package_name)

        with open(process_parameter_filename) as process_param_file:
            settings = json.load(process_param_file)

        # ( path to drive if mounted: /content/drive/MyDrive/ )
        settings["data_dir"] = raw_directory

        print(f"Kilosort4 version {version}")
        print(f"Kilosort4 location {kilosort.__path__}")
        print("settings kilosort4 here .......", settings)

        kilosort.run_kilosort(
            settings=settings,
            data_dir=raw_directory,
            results_dir=processed_directory,
            probe_name=chanmap_filename,
            save_preprocessed_copy=True,
        )


class SpikeInterfaceContainer:
    """Runs a sorter inside an allow-listed, pre-cached Apptainer image through SpikeInterface.

    The image comes from sorter_registry.resolve() as an absolute local .sif path, and
    SpikeInterface is already installed in it (see apptainer_cache.py), so the compute node
    never pulls an image or pip installs anything. Sorter params are SpikeInterface sorter
    params (e.g. `detect_threshold`), not raw Kilosort ops; the probe comes from the
    SpikeGLX meta, not the chanmap file.
    """

    # run_sorter / run_sorter_container arguments a params file must not override.
    RESERVED_PARAMS = job_spec.RESERVED_RUN_SORTER_PARAMS

    # Recording extra_requirements already in the image (installed with spikeinterface).
    IMAGE_PACKAGES = si_wrappers.IMAGE_PACKAGES

    @staticmethod
    def run_sorter_kwargs(resolved, folder, sorter_params):

        reserved = sorted(SpikeInterfaceContainer.RESERVED_PARAMS & set(sorter_params))
        if reserved:
            raise ValueError(
                f"sorter params may not set run_sorter arguments: {reserved}"
            )

        # SpikeInterface's Kilosort wrappers copy the recording to recording.dat; phy reads
        # temp_wh.dat, so drop the raw-sized copy unless the paramset asks to keep it.
        sorter_params = {"delete_recording_dat": True, **sorter_params}

        return dict(
            sorter_name=resolved.entry.sorter,
            folder=str(folder),
            remove_existing_folder=True,
            verbose=True,
            raise_error=True,
            singularity_image=str(resolved.sif_path),
            delete_container_files=True,
            installation_mode="no-install",
            **sorter_params,
        )

    @staticmethod
    def read_recording(raw_directory):
        """Open the SpikeGLX ap stream in raw_directory (raw run or CatGT/DREDge output)."""

        return si_wrappers.read_recording(raw_directory)

    @staticmethod
    def run(resolved, raw_directory, output_directory, sorter_params):
        """Sort in the container. The phy files end up directly in output_directory
        (`<clustering_method>_output`, where U19-pipeline-python loads them from);
        SpikeInterface's own files go in its `spikeinterface/` subfolder.
        """

        import spikeinterface.sorters as ss

        output_directory = pathlib.Path(output_directory)
        recording = SpikeInterfaceContainer.read_recording(raw_directory)
        si_wrappers.drop_image_requirements(recording, resolved.entry.key)

        # run_sorter empties its folder first, so it gets a scratch folder of its own.
        work = output_directory.with_name(output_directory.name + "_si_work")
        kwargs = SpikeInterfaceContainer.run_sorter_kwargs(
            resolved, work, sorter_params
        )
        print("running", resolved.entry.key, "in", resolved.sif_path)
        with apptainer_exec.exec_instead_of_instances():
            ss.run_sorter(recording=recording, **kwargs)

        if not (work / "sorter_output").is_dir():
            raise RuntimeError(
                f"{resolved.entry.key}: no sorter_output folder in {work}"
            )
        si_wrappers.adopt_sorter_folder(work, output_directory, flatten=True)
        return output_directory


def params_file_for_different_os(kilosort_output_dir):

    linux_path = "/mnt/cup/braininit"
    windows_path = "//cup.pni.princeton.edu/braininit"
    mac_path = "/Volumes/braininit"

    if kilosort_output_dir.is_dir():
        params_file = pathlib.Path(kilosort_output_dir, "params.py")
        if params_file.is_file():
            with open(params_file.as_posix()) as file:
                params_text = file.read()

            try:
                windows_params = params_text.replace(linux_path, windows_path)
                windows_param_file = pathlib.Path(kilosort_output_dir, "win_params.py")
                with open(windows_param_file, "w") as file:
                    file.write(windows_params)

                mac_params = params_text.replace(linux_path, mac_path)
                mac_param_file = pathlib.Path(kilosort_output_dir, "mac_params.py")
                with open(mac_param_file, "w") as file:
                    file.write(mac_params)
            except Exception as e:
                print(e)
