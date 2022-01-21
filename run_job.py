import os
import sys

# script that is called by the slurm engine, and performs the computation.

def preprocessing(method = 'CatGT'):
    """ Function to run preprocessing on the ePhys files

    Args:
        method (str, optional): [description]. Defaults to 'CatGT'.
    """
    
    match method:
        case 'CatGT':
            preprocessing_string = """./runit.sh '-dir=/tigress/ms81/M010/20211119/ -run=TowersTask -g=0 -t=0 -prb_fld -prb=0 -t_miss_ok -ap -apfilter=biquad,2,300,0 -gblcar -gfix=0.40,0.10,0.02 -dest=/tigress/ms81/tmp/ -out_prb_fld'"""
            print("Running preprocessing...")
            print(preprocessing)

            os.system(preprocessing_string)
            print("Finished preprocessing")
        case _:
            print("skipping")


def run_sorter(method = 'ks2'):
    """ Function to do spike sorting

    Args:
        method (str, optional): [description]. Defaults to 'ks2'.

    Returns:
        [type]: [description]
    """

    match method:
        case 'ks2':
            start_matlab = "module load matlab/R2020a"  # Alvaro, should we load the module here, or in the slurm file? 
            folder = "cd /tigress/ms81/"
            matlab_command = """matlab -singleCompThread -nodisplay -nosplash -r "addpath('/tigress/ms81/spikesorters/'); run_ks2('/tigress/ms81/catgt_towers_task_g0/','/tigress/ms81/tmp/'); exit" """
            final_touch = "touch /tigress/ms81/catgt_towers_task_g0/slurm_sorting.flag"
            processing_string = start_matlab + folder + matlab_command + final_touch
            print("Running kilosort 2")
            os.system(processing_string)
            print("Finished kilosort 2")
        case _:
            print("skipping")

def main():
    try:
        preprocessing('CatGT')
        run_sorter('ks2')
        return 0
    except:
        return 1

if __name__ == "__main__":
    sys.exit(main())