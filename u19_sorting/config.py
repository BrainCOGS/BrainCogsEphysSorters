
import os
import pathlib
import u19_sorting.utils as utils

'''
this_hostname = utils.get_hostname()
princeton_computing_hosts = ['della', 'tiger']
pni_computing_hosts = ['spock', 'scotty']

# Home dir if in priceton computing hosts
if any(host in this_hostname for host in princeton_computing_hosts):
    home_dir = '/scratch/gpfs/BRAINCOGS/'
#Home dir in pni hosts
else:
    home_dir = '/mnt/cup/braininit/shared/repos/AutomaticPipelineProcessing/'
'''

#Home dir is 4 directories up from this file
home_dir = os.path.abspath(os.path.realpath(__file__)+ "/../../../../")

root_raw_data_dir = pathlib.Path(home_dir, 'Data', 'Raw', 'electrophysiology').as_posix()
root_processed_data_dir = pathlib.Path(home_dir, 'Data', 'Processed', 'electrophysiology').as_posix()

parameter_dir = pathlib.Path(home_dir, 'ParameterFiles').as_posix()
process_parameter_file = parameter_dir+"/process_paramset_{}.json"
preprocess_parameter_file = parameter_dir+"/preprocess_paramset_{}.json"

chanmap_dir = pathlib.Path(home_dir,'ChanMapFiles') .as_posix()
chanmap_file = chanmap_dir+"/chanmap_{}.mat"

#Repository dir is two up of this config file
repository_dir = os.path.abspath(os.path.realpath(__file__)+ "/../../")

#Repository dir is three up of this config file
ephys_processing_dir = os.path.abspath(os.path.realpath(__file__)+ "/../../..")
ibl_post_processing_dir =  pathlib.Path(ephys_processing_dir, 'ibl_atlas_post_processing', 'iblapps')
ibl_atlas_script = pathlib.Path(ibl_post_processing_dir, 'prepare_ephys_data_ibl.py')
ibl_atlas_shell_script = pathlib.Path(repository_dir, 'prepare_ephys_data_ibl_script.sh')


#Main preprocess libs and sorters directories
preprocess_libs_dir = pathlib.Path(repository_dir, 'preprocess_libs')
sorters_dir = pathlib.Path(repository_dir, 'sorters')
matlab_scripts = pathlib.Path(repository_dir, "u19_sorting", "matlab_scripts")


sorters_names = {
    'kilosort3':     'Kilosort3',
    'kilosort2':     'Kilosort2',
    'SpikeInterface':'spike_interface'
}

preproc_tools = {
    'catgt':      'catgt',
}

preproc_tools_delete_post = [
    'catgt'
]