

from glob import iglob
import pathlib
import subprocess
import u19_sorting.config as config

def preprocess_main(raw_data_directory, processed_data_directory, preprocess_parameters):

    if 'cat_gt' in preprocess_parameters and preprocess_parameters['cat_gt']['use_cat_gt']:
        cat_gt.run_cat_gt(raw_data_directory, processed_data_directory, preprocess_parameters['cat_gt']['cat_gt_params'])


class cat_gt():

    #This library directory
    cat_gt_directory = pathlib.Path(config.preprocess_libs_dir, "CatGT-linux")


    @staticmethod
    def run_cat_gt(raw_data_directory, processed_data_directory, cat_gt_params):

        cat_gt_params['dir']  = raw_data_directory
        cat_gt_params['dir']  = cat_gt_params['dir'].parents[1]
        cat_gt_params['dest'] = processed_data_directory
        #Create the final cat_gt_command
        cat_gt_command = cat_gt.create_cat_gt_command(cat_gt_params)
        print(cat_gt_command)
        p = subprocess.Popen(cat_gt_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.wait()
        stdout, stderr = p.communicate()
        print(stdout.decode('UTF-8'))
        print(stderr.decode('UTF-8'))

    @staticmethod
    def create_cat_gt_command(cat_gt_params):

        cat_gt_command = []
        cat_gt_command.append("sh")
        cat_gt_command.append((pathlib.Path(cat_gt.cat_gt_directory, "runit.sh").as_posix()))

        for key, value in cat_gt_params.items():
            if key == "extras":
                extra_params = ["-"+i for i in value]
                cat_gt_command.extend(extra_params)
            else:
                if isinstance(value, list):
                    str_value = [str(i) for i in value]
                    cat_gt_command.append("-"+str(key)+"="+",".join(str_value))
                else:
                    cat_gt_command.append("-"+str(key)+"="+str(value))
                
        return cat_gt_command
