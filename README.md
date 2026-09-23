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

#### DREDge motion correction (optional, runs after CatGT and before the sorter)

Add a `dredge` entry as a later preprocessing step (in the DB: a `PreClusterParamSteps.Step` with a higher
`step_number` than the CatGT step). `run_dredge` reads the `*ap.bin/*ap.meta` produced by the previous step,
estimates and applies motion with SpikeInterface's `dredge` preset on the GPU, and writes a corrected SpikeGLX-style
`ap.bin` into `dredge_output/`, which the sorter then consumes exactly like a CatGT output.

```
{
  "dredge": {
    "preset": "dredge",
    "device": "cuda",
    "motion_kwargs": {},
    "job_kwargs": {"n_jobs": 8},
    "disable_sorter_drift": true
  }
}
```

- **preset:** SpikeInterface `correct_motion` preset (`dredge`, `dredge_fast`, `kilosort_like`, ...).
- **device:** `cuda` (falls back to `cpu` if no GPU) or `cpu`.
- **motion_kwargs / job_kwargs:** forwarded to `correct_motion` (estimation options / parallel chunk options).
- **disable_sorter_drift:** (bool, default `true`) when true the sorter stage sets `nblocks=0` (KS3/KS4) or
  `reorder=0` (KS2) so motion is corrected only once. Set to `false` to keep Kilosort's own drift correction
  on top of DREDge.

### Process parameter file

Process parameter file is a json file to configure sorter.
To configure this file refer to each sorter documentation:

- [Kilosort2](https://github.com/MouseLand/Kilosort#parameters)

#### Pinned sorter versions (optional `sorter_version`)

A process parameter file can pin the sorter build with a `sorter_version` key from
[`sorter_registry.json`](sorter_registry.json), the allow-list of versions a job can run:

```
{
  "clustering_method": "kilosort3",
  "sorter_version": "kilosort3@3.0.2",
  "detect_threshold": 6
}
```

- No `sorter_version` (or `null`): unchanged behavior (KS4 from the job env, KS2/KS3 through MATLAB).
- `native` entries (e.g. `kilosort4@4.1.7`) run in the job env, and the job fails if the installed
  `kilosort` isn't that exact version, so a shared env can't be upgraded silently.
- `container` entries run the sorter through SpikeInterface inside a cached Apptainer image, so KS2/2.5/3
  don't need a MATLAB license. The remaining params are **SpikeInterface** sorter params (`detect_threshold`, ...), not Kilosort
  `ops`, and the probe comes from the SpikeGLX `.meta` rather than the chanmap file. The Kilosort/phy files end up in
  `<clustering_method>_output/sorter_output/`.
- Unknown keys, a `clustering_method` that doesn't match the key, or an image that isn't cached fail the job
  before sorting starts. What ran is recorded in `sorter_provenance.json` next to the sorter output.

##### Caching container images (login node)

Compute nodes have no internet, so they never pull images. Build them once on a login node into shared storage:

```
python -m u19_sorting.apptainer_cache --dry-run   # what's missing
python -m u19_sorting.apptainer_cache             # build all missing images (or pass keys)
python -m u19_sorting.apptainer_cache --check     # exit 1 if any image is missing
```

Each image is the digest-pinned SpikeInterface docker image with the pinned `spikeinterface[full]` installed on top
(jobs run with `installation_mode="no-install"`, so nothing is pip-installed at run time). The host's
`spikeinterface` must match the entry's `spikeinterface` version. Images are built next to their final
location and renamed into place read-only; existing images are never rebuilt. Add `--fakeroot` if the
cluster requires it for `apptainer build`.

| Setting | Default | Override |
|---|---|---|
| Registry | `sorter_registry.json` in this repo | `U19_SORTER_REGISTRY` |
| Images (`.sif`) | `/scratch/gpfs/BRAINCOGS/electrophysiology_processing/apptainer/sif` | `U19_APPTAINER_SIF_DIR` |
| Apptainer layer cache | `/scratch/gpfs/BRAINCOGS/electrophysiology_processing/apptainer/cache` | `U19_APPTAINER_CACHEDIR` |

To add a version: append a new key to `sorter_registry.json` (never edit or reuse an existing key, since past
jobs' provenance points at it), then run `python -m u19_sorting.apptainer_cache <key>` on a login node.
An image is only rebuilt when its `.sif` file is missing, so if the build recipe in `apptainer_cache.py` changes,
new entries need new `.sif` names.


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