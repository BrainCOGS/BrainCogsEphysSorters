#!/bin/bash
#SBATCH --job-name=spikesorter-job     # create a short name for your job
#SBATCH --nodes=1                # node count
#SBATCH --ntasks=1               # total number of tasks across all nodes
#SBATCH --time=2:00:00
#SBATCH --mem=200G
#SBATCH --gres=gpu:1
#SBATCH --mail-user=ms81@princeton.edu
#SBATCH --mail-type=begin
#SBATCH --mail-type=END
#SBATCH --output=kilojob.log

module purge
module load anaconda3/2020.11
module load matlab/R2020a

cd /tigress/ms81/
conda activate sorter-env

python run_job.py