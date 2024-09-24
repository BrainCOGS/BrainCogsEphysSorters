
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

    return new_raw_data_directory

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

        if stderr:
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