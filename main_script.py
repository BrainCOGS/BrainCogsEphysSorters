
from concurrent.futures import process
import json
import pathlib
import os
import subprocess

import preprocess_utils as pu
import config


#"sbatch --export=recording_process_id=26,raw_data_directory='jjulian/jjulian_jj048/01162022/jjulian_jj048_01162022_g0/jjulian_jj048_01162022_g0_imec0',processed_data_directory='jjulian/jjulian_jj048/01162022/jjulian_jj048_01162022_g0/jjulian_jj048_01162022_g0_imec0/recording_process_id_26',repository_dir='/scratch/gpfs/BRAINCOGS/electorphysiology_processing/BrainCogsEphysSorters',process_script_path='main_script.py' slurm_real.slurm"
#    ",repository_dir="+cluster_vars['home_dir']+
#    ",process_script_path="+str(pathlib.Path(cluster_vars['home_dir'],cluster_vars['script_path'])), slurm_location


#export recording_process_id=26
#export raw_data_directory=jjulian/jjulian_jj048/01162022/jjulian_jj048_01162022_g0/jjulian_jj048_01162022_g0_imec0
#export processed_data_directory=jjulian/jjulian_jj048/01162022/jjulian_jj048_01162022_g0/jjulian_jj048_01162022_g0_imec0/ecording_process_id_26


# Get recording process and data directories
recording_process_id = os.environ['recording_process_id']
raw_data_directory = os.environ['raw_data_directory']
processed_data_directory = os.environ['processed_data_directory']

# Get params files
process_parameters_filename = config.process_parameter_file.format(recording_process_id)
with open(process_parameters_filename, 'r') as process_param_file:
    process_parameters = json.load(process_param_file)

preprocess_parameter_filename   = config.preprocess_parameter_file.format(recording_process_id)
with open(preprocess_parameter_filename, 'r') as preprocess_param_file:
    preprocess_parameters = json.load(preprocess_param_file)



if 'cat_gt' in preprocess_parameters and preprocess_parameters['cat_gt']['use_cat_gt']:
    cat_gt_params = preprocess_parameters['cat_gt']['cat_gt_params']
    cat_gt_params['dir'] = pathlib.Path(config.root_raw_data_dir,raw_data_directory)
    cat_gt_params['dir'] = cat_gt_params['dir'].parents[1]
    cat_gt_params['dest'] = pathlib.Path(config.root_processed_data_dir, processed_data_directory)
    cat_gt_command = pu.create_cat_gt_command(cat_gt_params)
    print(cat_gt_command)
    p = subprocess.Popen(cat_gt_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.wait()
    stdout, stderr = p.communicate()
    print(stdout.decode('UTF-8'))
    print(stderr.decode('UTF-8'))


'''

    
    print('aftercommand before comm')
    
    print('aftercommand after comm')
    print(stdout.decode('UTF-8'))
    print(stderr.decode('UTF-8'))



#Recording process key
rec_process_key = dict(recording_process_id=recording_process_id)
rec_process_str_key = 'recording_process_id_'+str(recording_process_id)

#Get fov key
rec_process = (imaging_rec.ImagingProcessing & rec_process_key).fetch1()
fov_key = rec_process.copy()
fov_key.pop('recording_process_id')

#Recording process extra info
recording_process_info = (lab.Location * recording.RecordingProcess * recording.Recording & rec_process_key).fetch(
    'acquisition_type', 'preprocess_paramset_idx', 'process_paramset_idx', as_dict=True)


#Paramset idx and key
paramset_idx = recording_process_info[0]['process_paramset_idx']
paramset_idx_key = dict()
paramset_idx_key['paramset_idx'] = paramset_idx
scanner = recording_process_info[0]['acquisition_type']


#Scan id always 0 because we will control that on recording_process 
scan_id = 0

#Get preprocess params
preprocess_params_key = dict()
preprocess_params_key['preprocess_paramset_idx'] = recording_process_info[0]['preprocess_paramset_idx']
preprocess_params = recording.PreprocessParamSet().get_preprocess_params(preprocess_params_key)
processing_method = preprocess_params['processing_method']
task_mode      = preprocess_params['task_mode']

print('got processing_method', processing_method)
print('got task_mode', task_mode)

print('got paramset_idx', paramset_idx)


#Get directories for kov
scan_filepaths = get_scan_image_files(fov_key)
scan_filepaths = scan_filepaths[:1]
print(scan_filepaths)

if rec_process_key not in scan_element.Scan():
    try: 
        #TODO: Can use tiffile function to loads
        print('LOADED Scan using Scanreader')
        loaded_scan = scanreader.read_scan(scan_filepaths)
        header = parse_scanimage_header(loaded_scan)
        #scanner = header['SI_imagingSystem'].strip('\'') #TODO: If using tiffile, hardcode it to `mesoscope`
    except Exception as e:
        print('LOADED Scan using Tifffile')
        scan_filepaths = scan_filepaths # TODO load all TIFF files from session possibly using TIFFSequence
        loaded_scan = tifffile.imread(scan_filepaths)
        #scanner = 'mesoscope'
    except: #TODO: Use except instead of else)
        print(f'ScanImage loading error')  #TODO: Modify the error message

    #Equipment.insert1({'scanner': scanner}, skip_duplicates=True)
    scan_element.Scan.insert1(
        {**rec_process_key, 'scan_id': scan_id, 'scanner': scanner, 'acq_software': acq_software})
    scan_element.ScanInfo.populate(rec_process_key, display_progress=True)

# output_dir = [x.rsplit('/', maxsplit=1)[0] for x in scan_filepaths]
# output_dir = [pathlib.Path(x) for x in output_dir]
# scan_folder = [x / process_method for x in output_dir]

fov_directory = (imaging_rec.FieldOfView & fov_key).fetch1('fov_directory')
#output_dir = pathlib.Path('/usr/people/gs6614/temp_output') / fov_directory / processing_method #TODO fix to possibly work with existing suite2p directories

recording_process_id_folder_found = True
generic_process_folder_found = True
# look firs for recording_process_id# directory
relative_output_dir = (pathlib.Path(fov_directory) / rec_process_str_key).as_posix()
output_dir = pathlib.Path(get_imaging_root_data_dir(), relative_output_dir)
if not output_dir.exists():
    recording_process_id_folder_found = False
    # look for suite2p directory
    relative_output_dir = (pathlib.Path(fov_directory) / processing_method).as_posix()
    output_dir = pathlib.Path(get_imaging_root_data_dir(), relative_output_dir)
if not output_dir.exists():
    generic_process_folder_found = False


# No results to load from
if task_mode == 'load' and not generic_process_folder_found:
    FileNotFoundError(processing_method + ' FOLDER NOT FOUND cannot load results!!!')

# Results from this specific recording_process_id already triggered
if task_mode == 'trigger' and recording_process_id_folder_found:
    print('Overwritting process output from original processing folder', output_dir)

#If trigger and not recording_process_id_folder_found make it
if task_mode == 'trigger':
    relative_output_dir = (pathlib.Path(fov_directory) / rec_process_str_key).as_posix()
    output_dir = pathlib.Path(get_imaging_root_data_dir(), relative_output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)


print('RELATIVE OUTPUT DIR')
print(relative_output_dir)
print(output_dir)
#output_dir.mkdir(parents=True,exist_ok=True)

#Check if found output dir is correct
if task_mode == 'load':
    if processing_method == 'suite2p':
        print('SUITE2P METHOD SELECTED')
        # output_dir = get_suite2p_dir(scan_key)
        p = pathlib.Path(output_dir).glob('**/*')
        plane_filepaths = [x for x in p if x.is_dir()]
        for plane_filepath in plane_filepaths:
            ops_fp = plane_filepath / 'ops.npy'
            iscell_fp = plane_filepath / 'iscell.npy'
            if not ops_fp.exists() or not iscell_fp.exists():
                raise FileNotFoundError(
                    'No "ops.npy" or "iscell.npy" found. Invalid suite2p plane folder: {}'.format(plane_filepath))

    elif processing_method == 'caiman':
        raise ValueError("caiman not supported yet")
#     _required_hdf5_fields = ['/motion_correction/reference_image',
#                             '/motion_correction/correlation_image',
#                             '/motion_correction/average_image',
#                             '/motion_correction/max_image',
#                             '/estimates/A']
# #TODO: Load Caiman output files
#     # pass
#     if not output_dir.exists():
#     # if not caiman_dir.exists():
#         print('CaImAn directory not found: {}'.format(output_dir))

#     for fp in output_dir.glob('*.hdf5'):
#         task_mode='trigger'
#         with h5py.File(fp, 'r') as h5f:
#             if all(s in h5f for s in _required_hdf5_fields):
#                 caiman_fp = fp
#                 break
#     # else:
#     #     raise FileNotFoundError(
#     #         'No CaImAn analysis output file found at {}'
#     #         ' containg all required fields ({})'.format(output_dir[0], _required_hdf5_fields))


if paramset_idx_key not in imaging_element.ProcessingParamSet():

    #Get all information from process params from recording.ProcessParamSet schema
    process_params_key = dict()
    process_params_key['process_paramset_idx'] = paramset_idx
    process_params_info = (recording.ProcessParamSet() & process_params_key).fetch(as_dict=True)
    process_params = recording.ProcessParamSet().get_process_params(process_params_key)

    #print('process_params_info', process_params_info)
    print('process_params', process_params)
    print('description', process_params_info[0]['process_paramset_desc'])

    #Insert in imaging element equivalent ProcessParamSet
    imaging_element.ProcessingParamSet.insert_new_params(
    processing_method=processing_method, paramset_idx=paramset_idx+1, paramset_desc=process_params_info[0]['process_paramset_desc'], params=process_params)

imaging_element.ProcessingTask.insert1(dict(**rec_process_key,
                                            scan_id=scan_id,
                                            paramset_idx=paramset_idx+1, 
                                            processing_output_dir=relative_output_dir, 
                                            task_mode=task_mode), 
                                        skip_duplicates=True)

imaging_element.Processing.populate(rec_process_key, display_progress=True)

processing_keys = imaging_element.Processing.fetch('KEY')
for processing_key in processing_keys:
    imaging_element.Curation().create1_from_processing_task(processing_key)

imaging_element.MotionCorrection.populate(rec_process_key, display_progress=True)
imaging_element.Segmentation.populate(rec_process_key, display_progress=True)

imaging_element.Fluorescence.populate(rec_process_key, display_progress=True)
imaging_element.Activity.populate(rec_process_key, display_progress=True)
'''