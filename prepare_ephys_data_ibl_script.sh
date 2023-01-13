
#!/bin/bash 

#module load anaconda3/2022.5
#read -t 5
#conda activate iblenv
#conda info

echo ${PWD}
echo ....................
echo $1
/home/u19prod/.conda/envs/iblenv/bin/python $1 $2 $3 $4
