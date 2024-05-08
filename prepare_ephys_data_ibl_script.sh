
#!/bin/bash 

module load anacondapy/2023.07-cuda
#read -t 5
#conda init
conda activate iblenv
#conda info

echo ${PWD}
echo ....................
echo $1
python $1 $2 $3 $4
