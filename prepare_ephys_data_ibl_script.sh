#!/bin/bash 
#!/usr/bin/env -S conda run -n iblenv

echo $(whereis conda)

module load anacondapy/2023.07-cuda

echo $(whereis conda)

#read -t 5
echo $1
conda init
conda activate iblenv
#conda info
#conda run -n iblenv python $1 $2 $3 $4
#conda info

#which python

#echo ${PWD}
#echo ....................
echo $1
python $1 $2 $3 $4
