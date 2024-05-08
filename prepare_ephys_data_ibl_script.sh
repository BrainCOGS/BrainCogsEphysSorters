
#!/bin/bash 

#module load anaconda3/2022.5
#read -t 5
conda init
conda activate iblenv
#conda info

echo ${PWD}
echo ....................
echo $1
python $1 $2 $3 $4
