% Manuel kilosort wrapper.
% Inspired by main_kilosort.m
% Original Source: https://github.com/MouseLand/Kilosort2/blob/master/main_kilosort.m
% Tested with with:
% git clone npy-matlab hash:  b7b0a4ef6ba26d98a8c54e651d5444083c88311c
% git clone kilosort   hash:  1a1fd3ae07a49c042b4128d6c2e79d6ab55872e5
%
%% Example use case:
% ksdir = 'C:\Users\ms81\Desktop\Kilosort\';
% phydir = 'C:\Users\ms81\Desktop\npy-matlab';
% data = 'D:\NPX_DATA\manuel\tmp\tmp_M012\imec0_catgt_2021-12-10_g0';
% tmp = 'D:\NPX_DATA\manuel\tmp';
% config = 'C:\Users\ms81\Desktop\code\config_manuel.m';
% chanmap = 'C:\Users\ms81\Desktop\code\chanMap_npx1_staggered.mat';
% numchans = 384;
% start = 0;
% stop = inf;
% highpass = 300;
% blocks = 5;
% sig = 20; % spatial smoothness function for regression.
%% Then just run:
% kilosortbatch(ksdir, phydir, data, tmp, config, chanmap, numchans, start, stop, sig, highpass, blocks)

function kilosortbatch(parameter_file, raw_directory, processed_directory, channel_map_file, dir_pattern)

    this_dir = fileparts(which('kilosortbatch'));
    braincogs_ephys_sorters_dir = fileparts(fileparts(this_dir));

    disp(this_dir)

    % Import dependencies.
    kilosort_dir = fullfile(braincogs_ephys_sorters_dir, 'sorters', 'Kilosort');
    npy_matlab_dir = fullfile(braincogs_ephys_sorters_dir, 'sorters', 'npy-matlab');
    addpath(genpath(kilosort_dir)) % path to kilosort folder
    addpath(genpath(npy_matlab_dir))

    if nargin <= 3
        channel_map_file = fullfile(kilosort2_dir, 'configFiles' ,'neuropixPhase3B1_kilosortChanMap.mat'); 
    end

    if nargin <= 4
        dir_pattern = '*.ap.bin'; 
    end

    % Silly CUDA 9 Error workaround (only happens on Turing and above cards)
    % See https://www.mathworks.com/matlabcentral/answers/437756-how-can-i-recompile-the-gpu-libraries
    % Program will break at the following line otherwise:
    % rez                = template_learning(rez, tF, st3);
    warning off parallel:gpu:device:DeviceLibsNeedsRecompiling
    try
	gpuArray.eye(2)^2;
    catch ME
    end
    try
        nnet.internal.cnngpu.reluForward(1);
    catch ME
    end

    % Actual program here.    
    % Set up config.
    [ops, success] = loadJSONfile(parameter_file);
    % trange cannot be inf
    if ops.trange(2) > 99999999
        ops.trange(2) = Inf
    end

    ops.fproc = fullfile(processed_directory, 'temp_wh.dat');
    ops.chanMap = channel_map_file;
    
    % Run Kilosort
    fprintf('Looking for data inside %s \n', raw_directory);
    % fs = dir(fullfile(raw_directory, 'chan*.mat'));
    % if ~isempty(fs)
    % 	ops.chanMap = fullfile(raw_directory, fs(1).name);
    % end

    %ops.sig        = sig;  % spatial smoothness constant for registration
    %ops.fshigh     = fshigh; % high-pass more aggresively
    %ops.nblocks    = nblocks; % blocks for registration. 0 turns it off, 1 does rigid registration. Replaces "datashift" option. 

    % find the binary file
    fs          = [dir(fullfile(raw_directory, '*.bin')) dir(fullfile(raw_directory, '*.dat'))];
    ops.fbinary = fullfile(raw_directory, fs(1).name);
    
    rez                = preprocessDataSub(ops);
    rez                = datashift2(rez, 1);

    [rez, st3, tF]     = extract_spikes(rez);

    rez                = template_learning(rez, tF, st3);

    [rez, st3, tF]     = trackAndSort(rez);

    rez                = final_clustering(rez, tF, st3);

    rez                = find_merges(rez, 1);

    % save final results as rez2
    fprintf('Saving final results in phy \n')
    rezToPhy2(rez, processed_directory);
    
    % saving figures
    h(1) = figure(1);
    h(2) = figure(2);
    h(3) = figure(3);
    savefig(h, fullfile(processed_directory, 'kilosort_overview.fig'))
    close(h);
    
end