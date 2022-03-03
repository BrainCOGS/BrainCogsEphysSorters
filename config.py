
import os
import pathlib


home_dir = '/scratch/gpfs/BRAINCOGS/'

root_raw_data_dir = home_dir+'Data/Raw/electrophysiology'
root_processed_data_dir = home_dir+'Data/Processed/electrophysiology'

parameter_dir = home_dir+'ParameterFiles/' 
process_parameter_file = parameter_dir+"process_paramset_{}.json"
preprocess_parameter_file = parameter_dir+"preprocess_paramset_{}.json"

#Repository dir is one up of this config file
repository_dir = os.path.abspath(os.path.realpath(__file__)+ "/../")
cat_gt_directory = (pathlib.Path(repository_dir, "preprocessing", "CatGT-linux")).as_posix()
