

import pathlib
import os
import subprocess
import json
import u19_sorting.config as config


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


    sorter_processed_directory = pathlib.Path(processed_directory, process_parameters['clustering_method']+'_output')
    pathlib.Path(sorter_processed_directory).mkdir(parents=True, exist_ok=True)

    hash = get_submodule_hash(sorter)
    print('hash submodule', hash)

    if sorter == config.sorters_names['kilosort2']:
        Kilosort2.run_Kilosort2(raw_directory, sorter_processed_directory, process_parameters_filename, chanmap_filename)
    elif sorter == config.sorters_names['kilosort3']:
        Kilosort3.run_Kilosort3(raw_directory, sorter_processed_directory, process_parameters_filename, chanmap_filename)

    else:
        print("skipping")

    return sorter_processed_directory


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

        if  p.stderr:
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
        p = subprocess.run(ks_command, universal_newlines=True, shell=True, capture_output=True)

        print('stderr here', p.stderr)
        print('stdout', p.stdout)

        if  p.stderr:
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

def get_submodule_hash(sorter_submodule):
    """ Get specific submodule current hash commit
        Args:
            sorter_submodule            (str):   Submodule name to search hash commit
    """

    sorter_submodule_dir = pathlib.Path(config.sorters_dir, sorter_submodule).as_posix()

    submodule_hash_command = ['git', 'submodule', 'status', sorter_submodule_dir]
    p = subprocess.Popen(submodule_hash_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.wait()
    stdout, stderr = p.communicate()
    output = stdout.decode('UTF-8')
    
    if len(output) > 0:
        hash = output.split(' ')[1]
    else:
        raise Exception(sorter_submodule + " is not a supported submodule")

    return hash