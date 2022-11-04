
import pathlib
import json
import subprocess
import u19_sorting.config as config


def post_process_main(raw_data_directory, processed_data_directory, sorter_processed_directory):
   
    # For the moment we just call ibl_data transformation to run atlas
    ibl_atlas_post_processing.run_ibl_atlas_post_processing(raw_data_directory, processed_data_directory, sorter_processed_directory)





class ibl_atlas_post_processing():

    #This library directory
    cat_gt_directory = pathlib.Path(config.preprocess_libs_dir, "CatGT-linux")


    @staticmethod
    def run_ibl_atlas_post_processing(raw_data_directory, processed_data_directory, sorter_processed_directory):

        ## ibl post processing
        ibl_output_dir = pathlib.Path(processed_data_directory, 'ibl_data')
        pathlib.Path(ibl_output_dir).mkdir(parents=True, exist_ok=True)

        command = config.ibl_atlas_shell_script.as_posix() + ' ' +\
            config.ibl_atlas_script.as_posix() + ' ' + raw_data_directory.as_posix() +\
            ' ' + sorter_processed_directory.as_posix() + ' ' + ibl_output_dir.as_posix()

        p = subprocess.run(command, shell=True, capture_output=True)

        if p.stderr:

            print('type(p.stderr)')
            stderr = p.stderr.decode('UTF-8')

            # Strange libarrow error that does not affect final result (Apparently)
            if not '/site-packages/pyarrow/libarrow.so' in stderr:
                raise Exception(stderr)

