#!/bin/bash 
#!/usr/bin/env -S conda run -n iblenv


module load anacondapy/2023.07-cuda

#read -t 5
conda init bash
#conda activate iblenv
#conda info
#conda run -n iblenv python $1 $2 $3 $4
#conda info

#which python

#echo ${PWD}
#echo ....................
echo $1
#python $1 $2 $3 $4
