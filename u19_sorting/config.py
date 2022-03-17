
import os
import pathlib


home_dir = '/scratch/gpfs/BRAINCOGS/'

root_raw_data_dir = home_dir+'Data/Raw/electrophysiology'
root_processed_data_dir = home_dir+'Data/Processed/electrophysiology'

parameter_dir = home_dir+'ParameterFiles/' 
process_parameter_file = parameter_dir+"process_paramset_{}.json"
preprocess_parameter_file = parameter_dir+"preprocess_paramset_{}.json"

#Repository dir is two up of this config file
repository_dir = os.path.abspath(os.path.realpath(__file__)+ "/../../")

#Main preprocess libs and sorters directories
preprocess_libs_dir = pathlib.Path(repository_dir, 'preprocess_libs')
sorters_dir = pathlib.Path(repository_dir, 'sorters')
matlab_scripts = pathlib.Path(repository_dir, "u19_sorting", "matlab_scripts")


sorters_names = {
    'Kilosort':      'Kilosort',
    'Kilosort2':     'Kilosort2',
    'SpikeInterface':'spike_interface'
}