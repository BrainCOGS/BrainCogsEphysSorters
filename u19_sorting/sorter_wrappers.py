

import pathlib
import os
import subprocess
import u19_sorting.config as config


def sorter_main(raw_directory, processed_directory, preprocess_parameters, process_parameters, process_parameter_filename):
    """ Main function to call appropiate sorter
        Args:
            raw_directory               (str):   Directory where raw (or preprocessed) data is located 
            processed_directory         (str):   Directory where processed data will be stored
            preprocess_parameters       (dict):  Dictionary with preprocessing parameters and sorter algorithm selection
            process_parameters          (dict):  Dictionary with specific sorting parameters
            process_parameter_filename  (dict):  Filename of json with sorting parameters
    """

    hash = get_submodule_hash(preprocess_parameters['clustering_method'])
    print('hash submodule', hash)

    if preprocess_parameters['clustering_method'] == config.sorters_names['Kilosort2']:

        
        Kilosort2.run_Kilosort2(raw_directory, processed_directory, process_parameter_filename)

    else:
        print("skipping")


class Kilosort2():
    """ Kilosort2 caller functions """

    #This library directory
    ks2_directory = pathlib.Path(config.sorters_dir, config.sorters_names['Kilosort2']).as_posix()

    @staticmethod
    def run_Kilosort2(raw_directory, processed_directory, process_parameter_filename):
        """ Function that calls Kilosort2
                
            Args:
                raw_directory               (str):   Directory where raw (or preprocessed) data is located 
                processed_directory         (str):   Directory where processed data will be stored
                process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        ks2_command = Kilosort2.create_Kilosort2_command(raw_directory, processed_directory, process_parameter_filename)
        os.system(ks2_command)

        

    @staticmethod
    def create_Kilosort2_command(raw_directory, processed_directory, process_parameter_filename):
        """ Function that creates the command to call matlab kilosort2 script
                
            Args:
                raw_directory               (str):   Directory where raw (or preprocessed) data is located 
                processed_directory         (str):   Directory where processed data will be stored
                process_parameter_filename  (dict):  Filename of json with sorting parameters
        """

        matlab_command = "addpath(genpath('" + Kilosort2.ks2_directory + "'));  \
        addpath('" + config.matlab_scripts.as_posix() + "'); \
        run_ks2('" + process_parameter_filename + "','" + raw_directory.as_posix() + "','"  + processed_directory.as_posix() + "'); exit"

        ks2_command =  ['matlab', '-nodisplay', '-nosplash', '-r']
        ks2_command = ' '.join(ks2_command)
        ks2_command += ' "'
        ks2_command += matlab_command 
        ks2_command += '"'
        
        return ks2_command


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
        hash = output.split(' ')[0]
    else:
        raise Exception(sorter_submodule + " is not a supported submodule")

    return hash