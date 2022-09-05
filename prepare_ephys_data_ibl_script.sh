
#!/bin/bash

module load anaconda3/5.3.1
conda activate iblenv

echo ${PWD}
echo ....................
echo $1
python $1 $2 $3 $4
