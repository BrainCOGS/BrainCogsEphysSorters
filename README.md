# BrainCogsEphysSorters
Compilation of electrophysiology sorters supported in the U19 Ephys Pipeline

## Instructions to clone and setup the repository
Since this is a repository with submodules it is needed to add `--recurse-submodules` when cloning it. So log into tiger and execute:
```
git clone --recurse-submodules git@github.com:BrainCOGS/BrainCogsEphysSorters.git
```

## Set up python environment:
First, make an environment that slurm can fire up:
```
module load anaconda3/2020.11
conda create --name sorter-env numpy scipy matplotlib --channel conda-forge
```
Test by executing
```
conda activate sorter-env
```
You can choose a different version/name for your environment, but make sure to adjust them in the `slurm.job` file as well.

## Set up CatGT
For preprocessing, we currently support CatGT:
```
wget https://billkarsh.github.io/SpikeGLX/Support/CatGTLnxApp.zip
unzip ./CatGTLnxApp.zip
cd ./CatGT-linux/
chmod +x ./install.sh
./install.sh
```