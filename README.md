# BrainCogsEphysSorters
Compilation of electrophysiology sorters and preprocessing tools supported in the U19 Ephys Pipeline

## User documentation

### What to run to test the code:

Example of a slurm command to preprocess and process an ephys session (Normally all parameters will be generated from the automation pipeline):

```
sbatch --export=recording_process_id=28,raw_data_directory='ms81/ms81_M004/20210507/towersTask_g0/towersTask_g0_imec0',processed_data_directory='ms81/ms81_M004/20210507/towersTask_g0/towersTask_g0_imec0/recording_process_id_28',repository_dir='/scratch/gpfs/BRAINCOGS/electorphysiology_processing/BrainCogsEphysSorters',process_script_path='main_script.py' slurm_real.slurm
```
To test code for a new ephys session:

1. Go to directory ```/scratch/gpfs/BRAINCOGS```.
2. Check that the ephys session you want to process is located on ```/Data/Raw/electrophysiology/(netID)/subject_fullname/date/..``` (ask main developer if session is not there).
3. Copy parameters files (**preprocess_paramset_x.json & process_paramset_x.json**)located in ```/ParameterFiles``` (x is a number that reference the ephys session).
4. Rename copied parameter files with a new number (**preprocess_paramset_y.json & process_paramset_y.json**) (y could be any number)
5. Run sbatch command (from the top of this section) with following modifications:
  - recording_process_id     =y (Change the number to match the parameter file name modification
  - raw_data_directory       = Relative directory to the ephys session probe ```(netID)/subject_fullname/date/.../imec(z)```
  - processed_data_directory = Same as raw_data_directory but include recording_process_id_y (where y is the number from the parameter file)
 
Logs will be written:

- for Kilosort:
  ```/Output_log/kilosort_out.log```
- for CatGT:
  ```/BrainCogsEphysSortets/CatGT.log``` (appended every time)



### Tiger cluster directory organization

As BRAINCOGS we have a common directory in the Tiger Cluster for processing data:
```
/scratch/gpfs/BRAINCOGS
```
These are the main directories that can be found on it:

- ```/Data``` → Replicate /braininit/Data directory path (raw sessions, processed sessions, etc)

- ```/electrophysiology_processing``` → All repositories for processing ephys
  - ```/BrainCogsEphysSorters```  Common library to process ephys in all BrainCogs (this Repository)

- ```/ParameterFiles``` →  Preprocess and process params files for processing sessions (all modalities)

- ```/Output_log``` →  Output data from processing sessions (all modalities)


### Repository directory organization

These are the main directories of the repository

- ```/preprocess_libs``` → All libraries we are going to use for preprocessing (CatGt, etc)

- ```/sorters``` → All repositories from sorter algorithm libraries (Kilosort, SpikeInterface, etc.)

- ```/u19_sorting``` → Call to all preprocess and process (sorters) codes.
  - preprocess_wrappers.py  Wrappers to call all preprocess libraries with corresponding params
  - sorters_wrappers.py     Wrappers to call all sorters libraries with corresponding params

- main_script.py → Script that is executed on runtime



## Main developer documentation

### Instructions to clone and setup the repository
Since this is a repository with submodules it is needed to add `--recurse-submodules` when cloning it. So log into tiger and execute:
```
git clone --recurse-submodules git@github.com:BrainCOGS/BrainCogsEphysSorters.git
```

And for branches, add the flag
```
git clone -b tmp --single-branch --recurse-submodules https://github.com/BrainCOGS/BrainCogsEphysSorters
```

### Set up CatGT
For preprocessing, we currently support CatGT:
```
cd ./CatGT-linux/
chmod +x ./install.sh
./install.sh
```
