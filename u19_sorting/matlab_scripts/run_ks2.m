function run_ks2(parameter_file, raw_directory, processed_directory, channel_map_file, dir_pattern)
    % rootZ is the directory containing the raw AP traces, one probe per folder
    % rootH is the scratch directory, SSD drive, to memmap binary data
    %
    % Example below:
    % rootZ = '/mnt/s0/Data/Subjects/ZM_1150/2019-05-07/001/raw_ephys_data/probe_right';
    % rootH = '/mnt/h0';  # temporary folder if different than main
    % run_ks2_ibl(rootZ, rootH)
    % run_ks2_ibl(rootZ, rootH, dir_pattern, channel_map_file)
    
    try
        
        this_dir = fileparts(which('run_ks2'));
        braincogs_ephys_sorters_dir = fileparts(fileparts(this_dir));

        disp(this_dir)
        
        
        %% 1) Set paths and get ks2 commit hash
        kilosort2_dir = fullfile(braincogs_ephys_sorters_dir, 'sorters', 'Kilosort2');
        npy_matlab_dir = fullfile(braincogs_ephys_sorters_dir, 'sorters', 'npy-matlab');
        addpath(genpath(kilosort2_dir)) % path to kilosort folder
        addpath(genpath(npy_matlab_dir))
        %[~, hash] = unix(['git --git-dir=' fullfile(kilosort2_dir, '.git') ' rev-parse --verify HEAD'])
        %disp(["ks2 version: " hash])
        
        %% 2) Parse input arguments
        rootZ = raw_directory;
        rootH = processed_directory;
        
        if nargin <= 3
            channel_map_file = fullfile(kilosort2_dir, 'configFiles' ,'neuropixPhase3B1_kilosortChanMap.mat'); 
        end
    
        if nargin <= 4
            dir_pattern = '*.ap.bin'; 
        end
        
        %% 3) get IBL params
        %ops = ks2_custom_params(channel_map_file, rootH);
        [ops, success] = loadJSONfile(parameter_file);
        if ~success
            error('Parameter file cannot be read, try again')
        end
        % Two params not from param file
        if ops.trange(2) > 99999999
            ops.trange(2) = Inf
        end
        ops.chanMap     = channel_map_file;
        disp(channel_map_file)
        ops.fproc       = fullfile(processed_directory, 'temp_wh.dat'); % proc file on a fast SSD
        
        %% 4) KS2 run
        fprintf('Looking for data inside %s \n', rootZ)
        disp(raw_directory)
        
        % find the binary file
        ops.fbinary = fullfile(raw_directory, getfield(dir(fullfile(raw_directory, dir_pattern)), 'name'));
        
        % preprocess data to create temp_wh.dat
        rez = preprocessDataSub(ops);
        
        % time-reordering as a function of drift
        rez = clusterSingleBatches(rez);
        save(fullfile(processed_directory, 'rez.mat'), 'rez', '-v7.3');
        
        % main tracking and template matching algorithm
        rez = learnAndSolve8b(rez);
        
        % final merges
        rez = find_merges(rez, 1);
        
        % final splits by SVD
        rez = splitAllClusters(rez, 1);
        
        % final splits by amplitudes
        rez = splitAllClusters(rez, 0);
        
        % decide on cutoff
        rez = set_cutoff(rez);
        
        fprintf('found %d good units \n', sum(rez.good>0))
        
        % write to Phy
        fprintf('Saving results to Phy  \n')
        rezToPhy(rez, processed_directory);
        
        %% 5) WRAP-UP
        fid = fopen([processed_directory filesep 'spike_sorting_ks2.log'], 'w+');
        for ff = fieldnames(ops)'
            val = ops.(ff{1});
            if isnumeric(val) | islogical(val)
                str = mat2str(val);
            else
                str = val;
            end
            fwrite(fid,['ops.' ff{1} ' = ' str ';' newline]);
        end
        fclose(fid);
        
    catch exception
        str=[exception.message newline];
        for m=1:length(exception.stack)
            str = [str 'Error in ' exception.stack(m).file ' line : ' num2str(exception.stack(m).line) newline];
        end
        fprintf(str)
        %disp(str)
        %disp('run_ks2.m failed') % this is used to find out that matlab failed in stdout
        throw(exception)
    end
    
    end
    
    function [json, success] = loadJSONfile(file)
    
    success = 1;
    
    try
        fid = fopen(file);
        json = jsondecode(char(fread(fid,inf)'));
        fclose(fid);
    catch
        success = 0;
        json    = struct;
        fclose(fid);
    end
    
    end
    
    
    function ops = ks2_custom_params(channel_map_file, rootH)
    ops.chanMap = channel_map_file;
    ops.fs = 30000;   % sample rate
    ops.fshigh = 300;    % frequency for high pass filtering (150)
    ops.minfr_goodchannels = 0;  % minimum firing rate on a "good" channel (0 to skip)
    ops.Th = [10 4];   % threshold on projections (like in Kilosort1, can be different for last pass like [10 4])
    ops.lam = 10;  % how important is the amplitude penalty (like in Kilosort1, 0 means not used, 10 is average, 50 is a lot)
    ops.AUCsplit = 0.9; % splitting a cluster at the end requires at least this much isolation for each sub-cluster (max = 1)
    ops.minFR = 1/50; % minimum spike rate (Hz), if a cluster falls below this for too long it gets removed
    ops.momentum = [20 400]; % number of samples to average over (annealed from first to second value)
    ops.sigmaMask = 30; % spatial constant in um for computing residual variance of spike
    ops.ThPre = 8;  % threshold crossings for pre-clustering (in PCA projection space)
    ops.CAR = true;  % Common Average Referencing (median)
    % DANGER ZONE: changing these settings can lead to fatal errors
    % options for determining PCs
    ops.spkTh           = -6;      % spike threshold in standard deviations (-6)
    ops.reorder         = 1;       % whether to reorder batches for drift correction.
    ops.nskip           = 25;  % how many batches to skip for determining spike PCs
    ops.GPU                 = 1; % has to be 1, no CPU version yet, sorry
    % ops.Nfilt               = 1024; % max number of clusters
    ops.nfilt_factor        = 4; % max number of clusters per good channel (even temporary ones)
    ops.ntbuff              = 64;    % samples of symmetrical buffer for whitening and spike detection
    ops.NT                  = 32*1024+ ops.ntbuff; % 64*1024+ ops.ntbuff; % must be multiple of 32 + ntbuff. This is the batch size (try decreasing if out of memory).
    ops.whiteningRange      = 32; % number of channels to use for whitening each channel
    ops.nSkipCov            = 25; % compute whitening matrix from every N-th batch
    ops.scaleproc           = 200;   % int16 scaling of whitened data
    ops.nPCs                = 3; % how many PCs to project the spikes into
    ops.useRAM              = 0; % not yet available
    ops.trange = [0 Inf]; % time range to sort
    ops.NchanTOT    = 384; % total number of channels in your recording
    % you need to change most of the paths in this block
    ops.fproc       = fullfile(rootH, 'temp_wh.dat'); % proc file on a fast SSD
    ops.trange = [0 Inf]; % time range to sort
    ops.NchanTOT    = 385; % total number of channels in your recording
    end
    