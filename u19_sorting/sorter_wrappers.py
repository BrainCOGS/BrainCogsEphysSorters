

import pathlib
import os
import re
import subprocess
import json
import importlib.metadata
import u19_sorting.config as config
import u19_sorting.preprocess_wrappers as pw
import u19_sorting.sorter_registry as sorter_registry
from u19_sorting.utils import write_file


# Written next to the sorter output when the job pinned a "sorter_version".
PROVENANCE_FILENAME = 'sorter_provenance.json'

# Python package whose installed version a native registry entry pins.
NATIVE_PACKAGES = {'kilosort4': 'kilosort'}


def sorter_main(recording_process_id, raw_directory, processed_directory):
    """ Main function to call appropiate sorter
        Args:
            raw_directory               (str):   Directory where raw (or preprocessed) data is located
            processed_directory         (str):   Directory where processed data will be stored
            preprocess_parameters       (dict):  Dictionary with preprocessing parameters and sorter algorithm selection
            process_parameters          (dict):  Dictionary with specific sorting parameters
            process_parameter_filename  (dict):  Filename of json with sorting parameters
    """

    # Get param file
    process_parameters_filename = config.process_parameter_file.format(recording_process_id)
    with open(process_parameters_filename, 'r') as process_param_file:
        process_parameters = json.load(process_param_file)

    # Get chanmap file
    chanmap_filename = config.chanmap_file.format(recording_process_id)

    sorter = config.sorters_names[process_parameters['clustering_method']]

    # Optional pinned sorter version: an allow-listed key from sorter_registry.json. Resolved
    # before anything runs so an unknown key, a drifted env or an uncached image fails the job
    # right away instead of silently running something else.
    resolved = resolve_sorter_version(process_parameters)

    # If DREDge ran as a preprocessing step, motion is already corrected. By default disable
    # Kilosort's own internal drift correction so motion is not corrected twice; set
    # "disable_sorter_drift": false in the dredge preprocess params to keep both.
    dredge_params = pw.preprocess_tool_params(recording_process_id, 'dredge')
    if dredge_params is not None:
        if dredge_params.get('disable_sorter_drift', True):
            in_container = resolved is not None and resolved.entry.mode == 'container'
            process_parameters = disable_internal_drift(process_parameters, sorter, in_container)
        else:
            print('DREDge preprocessing detected but disable_sorter_drift=false: keeping', sorter, 'internal drift correction')


    sorter_processed_directory = pathlib.Path(processed_directory, process_parameters['clustering_method']+'_output')
    pathlib.Path(sorter_processed_directory).mkdir(parents=True, exist_ok=True)

    l = process_parameters.pop("clustering_method")
    params_text = json.dumps(process_parameters)
    print('new params')
    print(params_text)
    write_file(process_parameters_filename, params_text)

    if resolved is not None and resolved.entry.mode == 'container':
        sorter_processed_directory = SpikeInterfaceContainer.run(resolved, raw_directory, sorter_processed_directory, process_parameters)
    elif sorter == config.sorters_names['kilosort2']:
        Kilosort2.run_Kilosort2(raw_directory, sorter_processed_directory, process_parameters_filename, chanmap_filename)
    elif sorter == config.sorters_names['kilosort3']:
        Kilosort3.run_Kilosort3(raw_directory, sorter_processed_directory, process_parameters_filename, chanmap_filename)
    elif sorter == config.sorters_names['kilosort4']:
        print('running Kilosort 4 here xxxxxxxx')
        Kilosort4.run_Kilosort4(raw_directory, sorter_processed_directory, process_parameters_filename, chanmap_filename)

    else:
        print("skipping")

    if resolved is not None:
        write_provenance(resolved, sorter_processed_directory)

    print(sorter, ' this is the sorter')
    if 'kilosort' in sorter.lower():
        print('params file different os function here', sorter_processed_directory)
        params_file_for_different_os(sorter_processed_directory)

    return sorter_processed_directory


def installed_version(package):
    """ Installed version of a python package, or None if it isn't installed. """

    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def resolve_sorter_version(process_parameters):
    """ Pop "sorter_version" from the process params and resolve it against the registry.

        Returns None when the job doesn't pin a version (legacy behavior). The key is always
        removed so it never reaches the sorter settings (KS4 rejects unknown keys).
    """

    key = process_parameters.pop('sorter_version', None)
    if key is None:
        return None

    resolved = sorter_registry.resolve(key)
    entry = resolved.entry

    clustering_method = process_parameters['clustering_method']
    if entry.sorter != clustering_method:
        raise sorter_registry.SorterRegistryError(
            f'sorter_version {key} runs {entry.sorter}, but clustering_method is {clustering_method}')

    if entry.mode == 'native':
        package = NATIVE_PACKAGES[entry.sorter]
        installed = installed_version(package)
        if installed is None:
            raise sorter_registry.SorterRegistryError(f'sorter_version {key}: {package} is not installed')
        if installed != entry.version:
            raise sorter_registry.SorterRegistryError(
                f'sorter_version {key} pins {package} {entry.version}, but {installed} is installed')
    else:
        # The host serializes the recording; the SpikeInterface baked into the image loads it.
        host_si = installed_version('spikeinterface')
        if host_si != entry.spikeinterface:
            raise sorter_registry.SorterRegistryError(
                f'sorter_version {key}: image has spikeinterface {entry.spikeinterface}, host has {host_si}')

    print('sorter_version', key, '->', resolved.provenance())
    return resolved


def write_provenance(resolved, sorter_processed_directory):
    """ Record exactly which sorter build produced this output. """

    provenance = resolved.provenance()
    if resolved.entry.mode == 'native':
        provenance['installed_version'] = installed_version(NATIVE_PACKAGES[resolved.entry.sorter])
    else:
        provenance['host_spikeinterface'] = installed_version('spikeinterface')

    provenance_file = pathlib.Path(sorter_processed_directory, PROVENANCE_FILENAME)
    with open(provenance_file, 'w') as f:
        json.dump(provenance, f, indent=4)


def disable_internal_drift(process_parameters, sorter, in_container=False):
    """ Turn off a Kilosort sorter's built-in motion/drift correction.

        Used when DREDge has already corrected motion in preprocessing. The mechanism differs
        per Kilosort version:
          - KS4 (python): nblocks=0 in the settings dict (KS4 rejects unknown keys, so no
            extra flag is added).
          - KS3 (matlab kilosortbatch): ops.nblocks=0 (kilosortbatch.m honors this to skip
            datashift2).
          - KS2 (matlab run_ks2): ops.reorder=0 (KS2 uses batch reordering, not nblocks).
          - Any sorter run through SpikeInterface in a container: SpikeInterface params, i.e.
            do_correction=False (KS2.5/3/4); SpikeInterface's KS2 has no drift parameter.
    """

    if in_container:
        if sorter == config.sorters_names['kilosort2']:
            print('DREDge preprocessing detected: SpikeInterface kilosort2 has no drift correction to disable')
            return process_parameters
        process_parameters['do_correction'] = False
    elif sorter == config.sorters_names['kilosort4']:
        process_parameters['nblocks'] = 0
    elif sorter == config.sorters_names['kilosort3']:
        process_parameters['nblocks'] = 0
    elif sorter == config.sorters_names['kilosort2']:
        process_parameters['reorder'] = 0

    print('DREDge preprocessing detected: disabled internal drift correction for', sorter)
    return process_parameters


class Kilosort2():
    """ Kilosort2 caller functions """

    #This library directory
    ks2_directory = pathlib.Path(config.sorters_dir, config.sorters_names['kilosort2']).as_posix()

    @staticmethod
    def run_Kilosort2(raw_directory, processed_directory, process_parameter_filename, chanmap_filename):
        """ Function that calls Kilosort2

            Args:
                raw_directory               (str):   Directory where raw (or preprocessed) data is located
                processed_directory         (str):   Directory where processed data will be stored
                process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        ks2_command = Kilosort2.create_Kilosort2_command(raw_directory, processed_directory, process_parameter_filename, chanmap_filename)
        print('ks2_command .....', ks2_command)
        p = subprocess.run(ks2_command, universal_newlines=True, shell=True, capture_output=True)

        print('stderr here', p.stderr)
        print('stdout', p.stdout)

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
    def create_Kilosort2_command(raw_directory, processed_directory, process_parameter_filename, chanmap_filename):
        """ Function that creates the command to call matlab kilosort2 script

            Args:
                raw_directory               (str):   Directory where raw (or preprocessed) data is located
                processed_directory         (str):   Directory where processed data will be stored
                process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        #ks2_command =  ['matlab', '-nodisplay', '-nosplash', '-r', "' disp(pwd); addpath(genpath(pwd)); " + config.run_ks_script + "; exit'"]
        #ks2_command = ' '.join(ks2_command)

        matlab_command = "addpath(genpath('" + Kilosort2.ks2_directory + "'));  \
        addpath('" + config.matlab_scripts.as_posix() + "'); \
        run_ks2('" + process_parameter_filename + "','" \
            + raw_directory.as_posix() + "','"  + processed_directory.as_posix() + "','"\
                + chanmap_filename + "'); exit"

        ks2_command =  ['matlab', '-nodisplay', '-nosplash', '-r']
        ks2_command = ' '.join(ks2_command)
        ks2_command += ' "'
        ks2_command += matlab_command
        ks2_command += '"'

        return ks2_command


class Kilosort3():
    """ Kilosort caller functions """

    #This library directory
    ks_directory = pathlib.Path(config.sorters_dir, config.sorters_names['kilosort3']).as_posix()

    @staticmethod
    def run_Kilosort3(raw_directory, processed_directory, process_parameter_filename, chanmap_filename):
        """ Function that calls Kilosort

            Args:
                raw_directory               (str):   Directory where raw (or preprocessed) data is located
                processed_directory         (str):   Directory where processed data will be stored
                process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        ks_command = Kilosort3.create_Kilosort3_command(raw_directory, processed_directory, process_parameter_filename, chanmap_filename)
        print('ks_command .....', ks_command)
        print('kilosort3 here .............................')
        p = subprocess.run(ks_command, universal_newlines=True, shell=True, capture_output=True)

        print('stderr here', p.stderr)
        print('stdout', p.stdout)

        if p.returncode:
            raise Exception(p.stderr)



    @staticmethod
    def create_Kilosort3_command(raw_directory, processed_directory, process_parameter_filename, chanmap_filename):
        """ Function that creates the command to call matlab kilosort2 script

            Args:
                raw_directory               (str):   Directory where raw (or preprocessed) data is located
                processed_directory         (str):   Directory where processed data will be stored
                process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        matlab_command = "addpath(genpath('" + Kilosort3.ks_directory + "'));  \
        addpath('" + config.matlab_scripts.as_posix() + "'); \
        kilosortbatch('" + process_parameter_filename + "','" \
            + raw_directory.as_posix() + "','"  + processed_directory.as_posix() + "','"\
                + chanmap_filename + "'); exit"

        ks_command =  ['matlab', '-nodisplay', '-nosplash', '-r']
        ks_command = ' '.join(ks_command)
        ks_command += ' "'
        ks_command += matlab_command
        ks_command += '"'

        return ks_command

class Kilosort4():
    """ Kilosort caller functions """

    #This library directory
    #ks_directory = pathlib.Path(config.sorters_dir, config.sorters_names['kilosort4']).as_posix()

    @staticmethod
    def run_Kilosort4(raw_directory, processed_directory, process_parameter_filename, chanmap_filename):
        """ Function that calls Kilosort

            Args:
                raw_directory               (str):   Directory where raw (or preprocessed) data is located
                processed_directory         (str):   Directory where processed data will be stored
                process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        import kilosort
        import importlib.metadata

        # Get the version of the package kilosort
        package_name = "kilosort"
        version = importlib.metadata.version(package_name)

        with open(process_parameter_filename, 'r') as process_param_file:
            settings = json.load(process_param_file)

        # ( path to drive if mounted: /content/drive/MyDrive/ )
        settings['data_dir'] = raw_directory

        print(f"Kilosort4 version {version}")
        print(f"Kilosort4 location {kilosort.__path__}")
        print('settings kilosort4 here .......', settings)

        kilosort.run_kilosort(settings=settings, data_dir=raw_directory, results_dir=processed_directory, probe_name=chanmap_filename, save_preprocessed_copy=True)



class SpikeInterfaceContainer():
    """ Runs a sorter inside an allow-listed, pre-cached Apptainer image through SpikeInterface.

        The image comes from sorter_registry.resolve() as an absolute local .sif path, and
        SpikeInterface is already installed in it (see apptainer_cache.py), so the compute node
        never pulls an image or pip installs anything. Sorter params are SpikeInterface sorter
        params (e.g. `detect_threshold`), not raw Kilosort ops; the probe comes from the
        SpikeGLX meta, not the chanmap file.
    """

    # run_sorter / run_sorter_container arguments a params file must not override.
    RESERVED_PARAMS = {
        'sorter_name', 'recording', 'folder', 'remove_existing_folder', 'delete_output_folder',
        'verbose', 'raise_error', 'with_output', 'docker_image', 'singularity_image',
        'delete_container_files', 'extra_requirements', 'installation_mode',
        'spikeinterface_version', 'spikeinterface_folder_source',
    }

    @staticmethod
    def run_sorter_kwargs(resolved, folder, sorter_params):

        reserved = sorted(SpikeInterfaceContainer.RESERVED_PARAMS & set(sorter_params))
        if reserved:
            raise ValueError(f'sorter params may not set run_sorter arguments: {reserved}')

        return dict(
            sorter_name=resolved.entry.sorter,
            folder=str(folder),
            remove_existing_folder=True,
            verbose=True,
            raise_error=True,
            singularity_image=str(resolved.sif_path),
            delete_container_files=True,
            installation_mode='no-install',
            **sorter_params,
        )

    @staticmethod
    def read_recording(raw_directory):
        """ Open the SpikeGLX ap stream in raw_directory (raw run or CatGT/DREDge output). """

        import spikeinterface.extractors as se

        raw_directory = pathlib.Path(raw_directory)
        meta_files = sorted(raw_directory.glob('*ap.meta'))
        if not meta_files:
            raise ValueError('No *ap.meta found in ' + raw_directory.as_posix())

        probe_match = re.search(r"imec([0-9]+)", meta_files[0].name)
        stream_id = ("imec" + probe_match.group(1) + ".ap") if probe_match else "imec0.ap"
        return se.read_spikeglx(folder_path=raw_directory.as_posix(), stream_id=stream_id)

    @staticmethod
    def run(resolved, raw_directory, output_directory, sorter_params):
        """ Sort in the container; returns the raw Kilosort output folder (phy files). """

        import spikeinterface.sorters as ss

        recording = SpikeInterfaceContainer.read_recording(raw_directory)
        kwargs = SpikeInterfaceContainer.run_sorter_kwargs(resolved, output_directory, sorter_params)
        print('running', resolved.entry.key, 'in', resolved.sif_path)
        ss.run_sorter(recording=recording, **kwargs)

        sorter_output = pathlib.Path(output_directory, 'sorter_output')
        if not sorter_output.is_dir():
            raise RuntimeError(f'{resolved.entry.key}: no sorter_output folder in {output_directory}')
        return sorter_output


def params_file_for_different_os(kilosort_output_dir):

    linux_path = '/mnt/cup/braininit'
    windows_path = '//cup.pni.princeton.edu/braininit'
    mac_path = '/Volumes/braininit'

    if kilosort_output_dir.is_dir():
        params_file = pathlib.Path(kilosort_output_dir,'params.py')
        if params_file.is_file():
            
            with open(params_file.as_posix(), "r") as file:
                params_text = file.read()
            
            try:
                windows_params = params_text.replace(linux_path,windows_path)
                windows_param_file = pathlib.Path(kilosort_output_dir,'win_params.py')
                with open(windows_param_file, "w") as file:
                    file.write(windows_params)

                mac_params = params_text.replace(linux_path,mac_path)
                mac_param_file = pathlib.Path(kilosort_output_dir,'mac_params.py')
                with open(mac_param_file, "w") as file:
                    file.write(mac_params)
            except Exception as e:
                print(e)
