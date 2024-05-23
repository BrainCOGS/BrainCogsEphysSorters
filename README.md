# BrainCogsEphysSorters
Compilation of electrophysiology sorters and preprocessing tools supported in the U19 Ephys Pipeline

## User documentation

### What to run to test the code:

Example of a slurm command to preprocess and process an ephys session (Normally all parameters will be generated from the automation pipeline):

```
sbatch --export=recording_process_id=28,raw_data_directory='ms81/ms81_M004/20210507/towersTask_g0/towersTask_g0_imec0',processed_data_directory='ms81/ms81_M004/20210507/towersTask_g0/towersTask_g0_imec0/recording_process_id_28',repository_dir='/scratch/gpfs/BRAINCOGS/electrophysiology_processing/BrainCogsEphysSorters',process_script_path='main_script.py' slurm_real.slurm
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

### Preprocess parameter file

Preprocess parameter file is a json file to configure preprocessing steps and select the desired sorter, main parameters are:

- **clustering_method:** (str) Which sorter will be used (Kilosort2, Kilosort, SpikeInterface).
- **cat_gt:** (dict) All parameters corresponding to catGT preprocessing.
  - **use_cat_gt:** (bool) 0 if cat_gt will not be used, 1 otherwise.
  - **"cat_gt_params"**: (dict) Cat_GT params that are included in command line when it is called
- **process_cluster:** (str) NA, Choose which available cluster will be used for processing (tiger, spock, etc)

Example:
Next preprocess param file will run Kilosort2 and use catGT:

```
{
"process_cluster": "tiger",
"clustering_method": "Kilosort2",
 "cat_gt": {
    "use_cat_gt": 1,
    "cat_gt_params": {
      "dir": "",
      "run": "towersTask",
      "g": 0,
      "t": 0,
      "apfilter": ["biquad",2,300,0],
      "gfix": [0.40,0.10,0.02],
      "extras": ["prb_3A", "prb_fld", "t_miss_ok", "ap", "gblcar", "out_prb_fld"],
      "dest": ""
   }
 }
}
```
The catGT command from these params is:

```./runit.sh '-dir=raw_data_directory -run=towersTask -g=0 -t=0 -prb_fld -prb=0 -t_miss_ok -ap -apfilter=biquad,2,300,0 -gblcar -gfix=0.40,0.10,0.02 -dest=processed_data_directory -out_prb_fld```

### Process parameter file

Process parameter file is a json file to configure sorter.
To configure this file refer to each sorter documentation:

- [Kilosort2](https://github.com/MouseLand/Kilosort#parameters)


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

### Revised sorter:

1. User config files (channel maps and sorting config files) should be deposited in `user_config_files`.

1. The two example channel maps `chanMap_npx1_staggered.mat` and `chanMap_npx2_hStripe_bottom2.mat` were written for staggered Neuropixel 1.0 probes, and the bottom horizontal strip of a 4-shank Neuropixel 2.0 probe. 

1. The example config file `config_manuel.m` is adjusted and mildly optimized from the file `\eMouse_drift\config_eMouse_drift_KS2.m`, which is part of the kilosort repository.

1. A test script that uses `kilosortbatch`, a wrapper around kilosort, is in the folder `/sandbox/`. It plays well with `npy-matlab` version `b7b0a4e` and `kilosort` version  `1a1fd3a`.

1. Once kilosort has run, waveforms should be inspected with phy, e.g. `phy template-gui D:\NPX_DATA\manuel\tmp\TowersTask_g0_imec2\params.py`

1. TODO: ks2_run is not needed anymore. Some general cleanup.