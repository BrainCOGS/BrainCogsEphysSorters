#!/bin/bash
#SBATCH --job-name=kilosort2     # create a short name for your job
#SBATCH --nodes=1                # node count
#SBATCH --ntasks=1               # total number of tasks across all nodes
#SBATCH --time=5:00:00
#SBATCH --mem=200G
#SBATCH --gres=gpu:1
#SBATCH --mail-user=alvaros@princeton.edu
#SBATCH --mail-type=begin
#SBATCH --mail-type=END
#SBATCH --output=kilojob.log
module load matlab/R2020a
cd /tigress/alvaros/
matlab -singleCompThread -nodisplay -nosplash -r "addpath('/tigress/alvaros/run_kilosort/spikesorters/'); run_ks2('/tigress/alvaros/ephys_raw/Thomas/T170/T170_2018_03_16/','/tigress/alvaros/run_kilosrt/tmp/'); exit"
touch /tigress/alvaros/run_kilosort/slurm_sorting.flag

