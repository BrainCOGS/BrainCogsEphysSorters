import pathlib
import subprocess

from u19_sorting import config


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
        """Prepare the IBL atlas alignment GUI inputs in <processed>/ibl_data.

        Optional: the sort has already finished when this runs, so a missing LF
        file or a failing IBL script is logged and the job carries on. The IBL
        script needs an `*lf.bin`, which SpikeGLX doesn't write when LF saving is
        off and Neuropixels 2.0 probes never record.
        """
        raw_data_directory = pathlib.Path(raw_data_directory)
        if not any(raw_data_directory.glob("*lf.bin")):
            print(
                f"Skipping IBL atlas post processing: no *lf.bin in {raw_data_directory}"
            )
            return

        ## ibl post processing
        ibl_output_dir = pathlib.Path(processed_data_directory, "ibl_data")
        pathlib.Path(ibl_output_dir).mkdir(parents=True, exist_ok=True)

        command = (
            "bash "
            + config.ibl_atlas_shell_script.as_posix()
            + " "
            + config.ibl_atlas_script.as_posix()
            + " "
            + raw_data_directory.as_posix()
            + " "
            + pathlib.Path(sorter_processed_directory).as_posix()
            + " "
            + ibl_output_dir.as_posix()
        )

        print("command run ibl atlas", command)

        p = subprocess.run(command, shell=True, capture_output=True)

        stdout = p.stdout.decode("UTF-8")
        stderr = p.stderr.decode("UTF-8")

        print(f"{stdout = }")

        if p.returncode:
            print(
                f"IBL atlas post processing failed (exit code {p.returncode}), "
                f"continuing without it. {stderr = }"
            )


# /home/u19prod/.conda/envs/iblenv/bin/python /scratch/gpfs/BRAINCOGS/electrophysiology_processing/ibl_atlas_post_processing/iblapps/prepare_ephys_data_ibl.py /scratch/gpfs/BRAINCOGS/Data/Raw/electrophysiology/ms81/ms81_M020/20221110_g0/towersTask_g0/towersTask_g0_imec0 /scratch/gpfs/BRAINCOGS/Data/Processed/electrophysiology/ms81/ms81_M020/20221110_g0/towersTask_g0/towersTask_g0_imec0/job_id_320/kilosort_output /scratch/gpfs/BRAINCOGS/Data/Processed/electrophysiology/ms81/ms81_M020/20221110_g0/towersTask_g0/towersTask_g0_imec0/job_id_320/ibl_data
