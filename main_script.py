
from concurrent.futures import process
import json
import pathlib
import os

import u19_sorting.config as config
import u19_sorting.preprocess_wrappers as pw
import u19_sorting.postprocess_wrappers as ppw
import u19_sorting.sorter_wrappers as sw

import subprocess


#sbatch --export=recording_process_id=26,raw_data_directory='jjulian/jjulian_jj048/01162022/jjulian_jj048_01162022_g0/jjulian_jj048_01162022_g0_imec0',processed_data_directory='jjulian/jjulian_jj048/01162022/jjulian_jj048_01162022_g0/jjulian_jj048_01162022_g0_imec0/recording_process_id_26',repository_dir='/scratch/gpfs/BRAINCOGS/electorphysiology_processing/BrainCogsEphysSorters',process_script_path='main_script.py' slurm_real.slurm
# sacct --job 8193599
#conda activate /home/alvaros/.conda/envs/BrainCogsEphysSorters_env/

#sbatch --export=recording_process_id=29,raw_data_directory='ms81/ms81_M005/20210505/towers_task_g0/towers_task_g0_imec0',processed_data_directory='ms81/ms81_M005/20210505/towers_task_g0/towers_task_g0_imec0/recording_process_id_29',repository_dir='/scratch/gpfs/BRAINCOGS/electorphysiology_processing/BrainCogsEphysSorters',process_script_path='main_script.py' slurm_real.slurm

# Get recording process and data directories
recording_process_id = os.environ['recording_process_id']
raw_data_directory = os.environ['raw_data_directory']
processed_data_directory = os.environ['processed_data_directory']

# Get absolute paths to raw and processed
raw_data_directory = pathlib.Path(config.root_raw_data_dir,raw_data_directory)
processed_data_directory = pathlib.Path(config.root_processed_data_dir,processed_data_directory)

print('raw_data_directory', raw_data_directory)

print('recording_process_id', recording_process_id)

print('processed_data_directory', processed_data_directory)


print('finish now...')

#Preprocess main
#new_raw_data_directory = pw.preprocess_main(recording_process_id, raw_data_directory, processed_data_directory)

#Sort main
#sorter_processed_directory = sw.sorter_main(recording_process_id, new_raw_data_directory, processed_data_directory)

#Delete unnecesary results directory
#pw.post_process_partial_results(recording_process_id, raw_data_directory, processed_data_directory)

#sorter_processed_directory = pathlib.Path(processed_data_directory, 'kilosort_output')
#ppw.post_process_main(raw_data_directory, processed_data_directory, sorter_processed_directory)


