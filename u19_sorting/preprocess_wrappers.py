
import re
import os
import pathlib
import subprocess
import json
import glob
import shutil

import u19_sorting.config as config
import u19_sorting.utils as utils


def preprocess_main(recording_process_id, raw_data_directory, processed_data_directory):

    preprocess_parameter_filename   = config.preprocess_parameter_file.format(recording_process_id)
    with open(preprocess_parameter_filename, 'r') as preprocess_param_file:
        preprocess_parameters = json.load(preprocess_param_file)

    #Create path structure if not in place
    print('processed_data_directory  ........', processed_data_directory)
    pathlib.Path(processed_data_directory).mkdir(parents=True, exist_ok=True)
    new_raw_data_directory = raw_data_directory
    print(new_raw_data_directory)

    for this_preparam in preprocess_parameters:
        print('this_preparam', this_preparam)
        if config.preproc_tools['catgt'] in this_preparam:
            catgt_output_dir = pathlib.Path(processed_data_directory, config.preproc_tools['catgt']+"_output")
            #pathlib.Path(catgt_output_dir).mkdir(parents=True, exist_ok=True)
            new_raw_data_directory = cat_gt.run_cat_gt(new_raw_data_directory, catgt_output_dir, this_preparam[config.preproc_tools['catgt']])
        if config.preproc_tools['dredge'] in this_preparam:
            dredge_output_dir = pathlib.Path(processed_data_directory, config.preproc_tools['dredge']+"_output")
            new_raw_data_directory = dredge.run_dredge(new_raw_data_directory, dredge_output_dir, this_preparam[config.preproc_tools['dredge']])

    return new_raw_data_directory


def preprocess_has_tool(recording_process_id, tool_key):
    """ Return True if the given preproc tool (e.g. 'dredge') is part of this job's preprocess params.

        Used by the sorter stage to decide whether to disable Kilosort's internal drift
        correction (so motion is not corrected twice).
    """

    preprocess_parameter_filename = config.preprocess_parameter_file.format(recording_process_id)
    if not pathlib.Path(preprocess_parameter_filename).is_file():
        return False

    with open(preprocess_parameter_filename, 'r') as preprocess_param_file:
        preprocess_parameters = json.load(preprocess_param_file)

    tool_name = config.preproc_tools[tool_key]
    return any(tool_name in this_preparam for this_preparam in preprocess_parameters)

def post_process_partial_results(recording_process_id, raw_data_directory, processed_data_directory):

    # Delete all unnecesary preprocessing tools results (to save storage)

    print('remove post processing partial results', processed_data_directory)

    for this_preproc_tool in config.preproc_tools_delete_post:
        this_tool_output_dir = pathlib.Path(processed_data_directory, this_preproc_tool+"_output")
        print('remove post processing partial results this_tool_output_dir ', this_tool_output_dir)
        if this_tool_output_dir.is_dir():
            shutil.rmtree(this_tool_output_dir)


class cat_gt():

    #This library directory
    cat_gt_directory = pathlib.Path(config.preprocess_libs_dir, "CatGT-linux")


    @staticmethod
    def run_cat_gt(raw_data_directory, catgt_output_dir, cat_gt_params):

        processed_data_directory = catgt_output_dir.parents[0]
        already_processed = cat_gt.cat_gt_check_output(catgt_output_dir)

        #Don't do anything if we are on lazy mode
        if already_processed:
            return catgt_output_dir
        #if cat_gt_params['lazy'] == True and already_processed:
        #    return cat_gt_output_dir

        cat_gt_params['dir']  = raw_data_directory
        cat_gt_params['dir']  = cat_gt_params['dir'].parents[1]
        cat_gt_params['dest'] = catgt_output_dir.parents[0]

        print('cat_gt_params', cat_gt_params)

        #Get cat_gt params from probe dir name
        probe_path = pathlib.PurePath(raw_data_directory)
        probe_path = probe_path.name
        print('probe_path', probe_path)
        extra_cat_gt_params = cat_gt.append_cat_gt_params_from_probedir(probe_path)
        print('extra_cat_gt_params', extra_cat_gt_params)
        cat_gt_params = {**cat_gt_params, **extra_cat_gt_params}

        #Create the final cat_gt_command and run
        cat_gt_command = cat_gt.create_cat_gt_command(cat_gt_params)
        print(cat_gt_command)
        p = subprocess.Popen(cat_gt_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.wait()
        stdout, stderr = p.communicate()

        if p.returncode:
            error = stderr.decode('UTF-8')
            raise Exception(error)

        cat_gt.cat_gt_postprocess_directory(processed_data_directory, catgt_output_dir)

        return catgt_output_dir

    @staticmethod
    def create_cat_gt_command(cat_gt_params):

        cat_gt_command = []
        #cat_gt_command.append("sh")
        cat_gt_command.append((pathlib.Path(cat_gt.cat_gt_directory, "runit.sh").as_posix()))

        for key, value in cat_gt_params.items():
            if key == "extras":
                extra_params = ["-"+i for i in value]
                cat_gt_command.extend(extra_params)
            elif key == "lazy":
                continue
            else:
                if isinstance(value, list):
                    str_value = [str(i) for i in value]
                    cat_gt_command.append("-"+str(key)+"="+",".join(str_value))
                else:
                    cat_gt_command.append("-"+str(key)+"="+str(value))

        return cat_gt_command

    @staticmethod
    def append_cat_gt_params_from_probedir(probe_dirname):

        extra_cat_gt_params = dict()

        probe_match = re.search("_imec[0-9]$", probe_dirname)
        if probe_match:
            probe_text = probe_match.group()
            extra_cat_gt_params['prb'] = re.search(r'\d+',probe_text).group()
        else:
            raise ValueError(probe_dirname +' is not a valid probe directory')

        session_num_match = re.search("_g[0-9]_", probe_dirname)
        if session_num_match:
            extra_cat_gt_params['run'] = probe_dirname[:session_num_match.start()]
            session_text = session_num_match.group()
            extra_cat_gt_params['g'] = re.search(r'\d+',session_text).group()
        else:
            raise ValueError(probe_dirname +' is not a valid probe directory')

        trigger_num_match = re.search("_t[0-9]_", probe_dirname)
        if trigger_num_match:
            trigger_text = trigger_num_match.group()
            extra_cat_gt_params['t'] = re.search(r'\d+',trigger_text).group()
        else:
            extra_cat_gt_params['t'] = '0'

        return extra_cat_gt_params

    @staticmethod
    def cat_gt_postprocess_directory(processed_data_directory, cat_gt_output_dir):

        #Find catgt head directory in processed data dir
        catgt_dir = str()
        old_catgt_dir = str()
        path_process_dir = pathlib.Path(processed_data_directory)

        print('path_process_dir', path_process_dir)
        print('cat_gt_output_dir', cat_gt_output_dir)

        for x in path_process_dir.iterdir():
            if x.is_dir():
                dirname = x.name
                if dirname[0:5] == 'catgt':
                    old_catgt_dir = pathlib.Path(path_process_dir, dirname).as_posix()
                    catgt_dir = cat_gt_output_dir.as_posix()
                    os.rename(old_catgt_dir, catgt_dir)
                    break

        print('catgt_dir', catgt_dir)

        if not catgt_dir:
            raise ValueError('catgt directory not found')

        #Delete child directories and move catgt results straight into catgt directory
        utils.move_to_root_folder(catgt_dir, catgt_dir)


    @staticmethod
    def cat_gt_check_output(cat_gt_output_dir):

        file_patterns= ['/*ap.bin', '/*ap.meta']

        child_dirs = [x[0] for x in os.walk(cat_gt_output_dir)]
        patterns_found = 0
        for dir in child_dirs:
            for pat in file_patterns:
                found_file = glob.glob(dir+pat)
                if len(found_file) > 0:
                    patterns_found = 1
                    break

            if patterns_found:
                break

        if patterns_found:
            return 1
        else:
            return 0


class dredge():
    """ DREDge motion correction (via SpikeInterface) as a preprocessing step.

        Alternative to CatGT: reads the SpikeGLX run for a single probe, applies DREDge
        motion correction, and writes a SpikeGLX-style ``*.ap.bin`` + ``*.ap.meta`` pair into
        ``dredge_output``. The returned directory is a drop-in replacement for the CatGT output
        directory, so the existing Kilosort callers read it unchanged.

        DREDge replaces Kilosort's internal drift correction, so when this step runs the sorter
        stage disables the in-sorter motion correction (see ``preprocess_has_tool`` /
        ``sorter_wrappers``) to avoid correcting motion twice.
    """

    # SpikeInterface's "Official Dredge preset"; it sets estimate_motion method="dredge_ap".
    default_preset = "dredge"

    @staticmethod
    def run_dredge(raw_data_directory, dredge_output_dir, dredge_params):

        # Lazy mode: if a corrected binary already exists, reuse it (mirrors cat_gt).
        already_processed = cat_gt.cat_gt_check_output(dredge_output_dir)
        if already_processed:
            return dredge_output_dir

        # SpikeInterface (and torch) are heavy imports; only pay the cost when DREDge is used.
        import spikeinterface.full as si

        raw_data_directory = pathlib.Path(raw_data_directory)

        # The probe directory is the SpikeGLX run folder's '*_imecN' child; read_spikeglx wants
        # the run folder + the AP stream for that probe.
        probe_dirname = raw_data_directory.name
        run_folder = raw_data_directory.parent
        probe_num = dredge.probe_number_from_dirname(probe_dirname)
        stream_id = "imec{}.ap".format(probe_num)

        print('dredge run_folder', run_folder, 'stream_id', stream_id)

        recording = si.read_spikeglx(folder_path=run_folder.as_posix(), stream_id=stream_id)

        preset = dredge_params.get('preset', dredge.default_preset)
        motion_kwargs = dredge_params.get('motion_kwargs', {})
        print('dredge preset', preset, 'motion_kwargs', motion_kwargs)

        recording_corrected = si.correct_motion(recording, preset=preset, **motion_kwargs)

        dredge.write_spikeglx_style_output(
            recording_corrected, run_folder, stream_id, dredge_output_dir, dredge_params)

        return dredge_output_dir

    @staticmethod
    def probe_number_from_dirname(probe_dirname):
        """ Extract the probe number N from a '*_imecN' SpikeGLX probe directory name. """

        probe_match = re.search("_imec([0-9])$", probe_dirname)
        if not probe_match:
            raise ValueError(probe_dirname + ' is not a valid probe directory')
        return probe_match.group(1)

    @staticmethod
    def write_spikeglx_style_output(recording_corrected, run_folder, stream_id, dredge_output_dir, dredge_params):
        """ Write the motion-corrected recording as a SpikeGLX-style '*.ap.bin' + '*.ap.meta'.

            SpikeInterface's write produces a plain binary, so we name it with the SpikeGLX
            '*.ap.bin' convention and copy the original '*.ap.meta' next to it. Motion correction
            does not change channel count, sample count or sampling rate, so the source meta stays
            valid for the corrected binary.
        """

        import spikeinterface.full as si

        pathlib.Path(dredge_output_dir).mkdir(parents=True, exist_ok=True)

        # Locate the source SpikeGLX *.ap.bin / *.ap.meta for this probe to reuse the base name.
        probe_num = stream_id.replace('imec', '').replace('.ap', '')
        meta_matches = glob.glob(pathlib.Path(run_folder, "*_imec{}".format(probe_num), "*.ap.meta").as_posix())
        meta_matches += glob.glob(pathlib.Path(run_folder, "*.ap.meta").as_posix())
        if not meta_matches:
            raise ValueError('No source *.ap.meta found for ' + stream_id + ' under ' + run_folder.as_posix())
        source_meta = pathlib.Path(meta_matches[0])
        base_name = source_meta.name[:-len('.meta')]  # e.g. run_g0_t0.imec0.ap.bin

        out_bin = pathlib.Path(dredge_output_dir, base_name)
        out_meta = pathlib.Path(dredge_output_dir, source_meta.name)

        n_jobs = dredge_params.get('n_jobs', 1)
        dtype = recording_corrected.get_dtype()
        si.write_binary_recording(
            recording_corrected,
            file_paths=[out_bin.as_posix()],
            dtype=dtype,
            n_jobs=n_jobs,
        )

        shutil.copy2(source_meta.as_posix(), out_meta.as_posix())
        print('dredge wrote', out_bin, 'and', out_meta)