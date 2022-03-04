

import pathlib
import subprocess
import u19_sorting.config as config

def sorter_main(raw_directory, processed_directory, preprocess_parameters, process_parameters):

    if preprocess_parameters['clustering_method'] == 'kilosort2':
        kilosort2.run_kilosort2(raw_directory, processed_directory, process_parameters)

    else:
        print("skipping")


class kilosort2():

    @staticmethod
    def run_kilosort2(raw_directory, processed_directory, process_parameters):

        print('running kilosort2')
        #Create the final cat_gt_command
        '''
        cat_gt_command = kilosort2.create_kilosort2_command(process_parameters)
        print(cat_gt_command)
        p = subprocess.Popen(cat_gt_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.wait()
        stdout, stderr = p.communicate()
        print(stdout.decode('UTF-8'))
        print(stderr.decode('UTF-8'))
        '''

    @staticmethod
    def create_kilosort2_command(kilosort2_params):

        pass


'''
def run_sorter(method = 'ks2'):
    """ Function to do spike sorting

    Args:
        method (str, optional): [description]. Defaults to 'ks2'.

    Returns:
        [type]: [description]
    """

    match method:
        case 'ks2':
            start_matlab = "module load matlab/R2020a\n"  # Alvaro, should we load the module here, or in the slurm file? 
            folder = "cd /tigress/ms81/\n"
            matlab_command = """matlab -singleCompThread -nodisplay -nosplash -r "addpath('/tigress/ms81/spikesorters/'); run_ks2('/tigress/ms81/catgt_towers_task_g0/','/tigress/ms81/tmp/'); exit" \n"""
            final_touch = "touch /tigress/ms81/catgt_towers_task_g0/slurm_sorting.flag\n"
            processing_string = start_matlab + folder + matlab_command + final_touch

            print("Running kilosort 2")
            os.system(processing_string)
            print("Finished kilosort 2")
        case _:
            print("skipping")


'''