import pathlib
import subprocess
import sys

from u19_sorting import config


def ibl_atlas_python():
    """The python for the IBL atlas step when the job runs from the uv environment, else None.

    The uv environment (<repository_dir>/.venv, built from uv.lock) has ibllib, so the step
    runs with the job's own python. Any other environment (the conda env
    u19_pipeline_python_env3) keeps running it with the conda env iblenv, through
    prepare_ephys_data_ibl_script.sh.
    """

    venv = pathlib.Path(config.repository_dir, ".venv")
    try:
        in_venv = pathlib.Path(sys.prefix).resolve() == venv.resolve()
    except OSError:
        in_venv = False
    return sys.executable if in_venv else None


def post_process_main(
    raw_data_directory, processed_data_directory, sorter_processed_directory
):

    # For the moment we just call ibl_data transformation to run atlas
    ibl_atlas_post_processing.run_ibl_atlas_post_processing(
        raw_data_directory, processed_data_directory, sorter_processed_directory
    )


class ibl_atlas_post_processing:
    # This library directory
    cat_gt_directory = pathlib.Path(config.preprocess_libs_dir, "CatGT-linux")

    @staticmethod
    def run_ibl_atlas_post_processing(
        raw_data_directory, processed_data_directory, sorter_processed_directory
    ):

        ## ibl post processing
        ibl_output_dir = pathlib.Path(processed_data_directory, "ibl_data")
        pathlib.Path(ibl_output_dir).mkdir(parents=True, exist_ok=True)

        python = ibl_atlas_python()
        if python is not None:
            ibl_atlas_post_processing.run_with_python(
                python, raw_data_directory, sorter_processed_directory, ibl_output_dir
            )
            return

        command = (
            "bash "
            + config.ibl_atlas_shell_script.as_posix()
            + " "
            + config.ibl_atlas_script.as_posix()
            + " "
            + raw_data_directory.as_posix()
            + " "
            + sorter_processed_directory.as_posix()
            + " "
            + ibl_output_dir.as_posix()
        )

        print("command run ibl atlas", command)

        p = subprocess.run(command, shell=True, capture_output=True)

        stderr = p.stderr.decode("UTF-8")
        stdout = p.stderr.decode("UTF-8")

        print(f"{stdout = }")

        if p.returncode:
            print(f"{type(p.stderr) = }")
            print(f"{stderr = }")
            raise Exception(stderr)

    @staticmethod
    def run_with_python(
        python, raw_data_directory, sorter_processed_directory, ibl_output_dir
    ):
        """Run prepare_ephys_data_ibl.py with python; a failure stops the job.

        The output goes straight to the job log. The script imports atlaselectrophysiology
        from its own directory (iblapps), which python puts first on sys.path.
        """

        command = [
            python,
            "-u",
            config.ibl_atlas_script.as_posix(),
            pathlib.Path(raw_data_directory).as_posix(),
            pathlib.Path(sorter_processed_directory).as_posix(),
            pathlib.Path(ibl_output_dir).as_posix(),
        ]
        print("command run ibl atlas", command, flush=True)

        p = subprocess.run(command, cwd=config.ibl_post_processing_dir.as_posix())
        if p.returncode:
            raise RuntimeError(
                f"IBL atlas step failed with exit code {p.returncode}: {command} "
                "(its traceback is above in this log)"
            )


# /home/u19prod/.conda/envs/iblenv/bin/python /scratch/gpfs/BRAINCOGS/electrophysiology_processing/ibl_atlas_post_processing/iblapps/prepare_ephys_data_ibl.py /scratch/gpfs/BRAINCOGS/Data/Raw/electrophysiology/ms81/ms81_M020/20221110_g0/towersTask_g0/towersTask_g0_imec0 /scratch/gpfs/BRAINCOGS/Data/Processed/electrophysiology/ms81/ms81_M020/20221110_g0/towersTask_g0/towersTask_g0_imec0/job_id_320/kilosort_output /scratch/gpfs/BRAINCOGS/Data/Processed/electrophysiology/ms81/ms81_M020/20221110_g0/towersTask_g0/towersTask_g0_imec0/job_id_320/ibl_data
