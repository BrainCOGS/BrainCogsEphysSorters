"""The two stages after the sort.

postprocess_main      the job's postprocessing steps (`spikeinterface`, `bombcell`), on the
                      sorter's output and the recording it read. Runs right after the sort,
                      before the preprocessing outputs are deleted.
post_process_main     the IBL atlas step, the fixed last step of every job.
"""

import functools
import pathlib
import subprocess
import sys

from u19_sorting import config, job_spec, si_wrappers


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


def needs_phy_export(spec):
    """A sorter run through SpikeInterface that is not Kilosort leaves no phy folder, so
    one is always exported: it is what the DataJoint element and the IBL step read."""

    if spec.sorting.legacy:
        return False
    sorter_name = si_wrappers.si_sorter_name(spec.sorting.clustering_method)
    return not si_wrappers.is_kilosort(sorter_name)


def postprocess_main(spec, raw_data_directory, sorter_input_directory, sort_result):
    """Run the job's postprocessing steps in order; returns the PostprocessContext, or None.

    Args:
        spec                     (JobSpec):    the job spec
        raw_data_directory       (Path):       the raw SpikeGLX run
        sorter_input_directory   (Path):       what the sorter read (the raw run or the last
                                               preprocessing output); still on disk here
        sort_result              (SortResult): from sorter_wrappers.run_sort

    Every step shares one sorting analyzer (see si_wrappers.PostprocessContext). For a
    SpikeInterface sort it is built on the in-memory recording and sorting; for a legacy
    sort the Kilosort folder is read back with `read_kilosort` and the recording with
    `read_recording`. A job without postprocessing steps (and with a Kilosort sorter) does
    nothing here and imports nothing.
    """

    output_directory = pathlib.Path(sort_result.output_directory)
    export_phy = needs_phy_export(spec)
    if not spec.postprocessing and not export_phy:
        print("no postprocessing steps")
        return None

    if sort_result.sorting is not None:
        recording, sorting = sort_result.recording, sort_result.sorting
    else:
        recording = functools.partial(
            si_wrappers.read_recording, sorter_input_directory
        )
        sorting = functools.partial(si_wrappers.read_sorter_output, output_directory)
    sorter_read_raw = (
        pathlib.Path(sorter_input_directory) == pathlib.Path(raw_data_directory)
        and not spec.sorting.lazy_steps
    )
    context = si_wrappers.PostprocessContext(
        output_directory,
        recording,
        sorting,
        recording_steps=spec.analyzer_recording_steps,
        sorter_read_raw=sorter_read_raw,
    )

    for step in spec.postprocessing:
        print("this_postparam", {step.method: step.params})
        if step.method == job_spec.SPIKEINTERFACE:
            if step.params.get("export") == "phy" and not export_phy:
                print(
                    spec.sorting.clustering_method,
                    "already wrote a phy folder; not exporting over it",
                )
            si_wrappers.spikeinterface_postproc.run(context, step.params)
        elif step.method == job_spec.BOMBCELL:
            si_wrappers.bombcell_postproc.run(context, step.params)

    si_wrappers.finish_postprocessing(context, export_phy=export_phy)
    if export_phy:
        # The phy export wrote params.py; give it its Windows / Mac copies, as the sort
        # stage does for a Kilosort folder.
        import u19_sorting.sorter_wrappers as sw

        sw.params_file_for_different_os(output_directory)
    return context


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
