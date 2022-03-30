# BrainCogsEphysSorters
Compilation of electrophysiology sorters supported in the U19 Ephys Pipeline

## Repository directory organization

- /preprocess_libs → All libraries we are going to use for preprocessing (CatGt, etc)

- /sorters → All repositories from sorter algorithm libraries (Kilosort, SpikeInterface, etc.)

- /u19_sorting → Call to all preprocess and process (sorters) codes.
  - preprocess_wrappers.py  Wrappers to call all preprocess libraries with corresponding params
  - sorters_wrappers.py          Wrappers to call all sorters libraries with corresponding params

- main_script.py → Script that is executed on runtime

## Instructions to clone and setup the repository
Since this is a repository with submodules it is needed to add `--recurse-submodules` when cloning it. So log into tiger and execute:
```
git clone --recurse-submodules git@github.com:BrainCOGS/BrainCogsEphysSorters.git
```

And for branches, add the flag
```
git clone -b tmp --single-branch --recurse-submodules https://github.com/BrainCOGS/BrainCogsEphysSorters
```

## Set up CatGT
For preprocessing, we currently support CatGT:
```
cd ./CatGT-linux/
chmod +x ./install.sh
./install.sh
```
