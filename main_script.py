
from concurrent.futures import process
import json
import pathlib
import os

import u19_sorting.config as config
import u19_sorting.preprocess_wrappers as pw
import u19_sorting.sorter_wrappers as sw


#sbatch --export=recording_process_id=26,raw_data_directory='jjulian/jjulian_jj048/01162022/jjulian_jj048_01162022_g0/jjulian_jj048_01162022_g0_imec0',processed_data_directory='jjulian/jjulian_jj048/01162022/jjulian_jj048_01162022_g0/jjulian_jj048_01162022_g0_imec0/recording_process_id_26',repository_dir='/scratch/gpfs/BRAINCOGS/electorphysiology_processing/BrainCogsEphysSorters',process_script_path='main_script.py' slurm_real.slurm
# sacct --job 8193599
#conda activate /home/alvaros/.conda/envs/BrainCogsEphysSorters_env/


# Get recording process and data directories
recording_process_id = os.environ['recording_process_id']
raw_data_directory = os.environ['raw_data_directory']
processed_data_directory = os.environ['processed_data_directory']

# Get absolute paths to raw and processed
raw_data_directory = pathlib.Path(config.root_raw_data_dir,raw_data_directory)
processed_data_directory = pathlib.Path(config.root_processed_data_dir,processed_data_directory)

# Get params files
process_parameters_filename = config.process_parameter_file.format(recording_process_id)
with open(process_parameters_filename, 'r') as process_param_file:
    process_parameters = json.load(process_param_file)

preprocess_parameter_filename   = config.preprocess_parameter_file.format(recording_process_id)
with open(preprocess_parameter_filename, 'r') as preprocess_param_file:
    preprocess_parameters = json.load(preprocess_param_file)

#Preprocess main
pw.preprocess_main(raw_data_directory, processed_data_directory, preprocess_parameters)

#Sort main
sw.sorter_main(raw_data_directory, processed_data_directory, preprocess_parameters, process_parameters, preprocess_parameter_filename)


