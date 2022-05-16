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


function kilosortbatch(ksdir,phydir,data,tmp,config,chanmap,numchans,start,stop,sig,fshigh,nblocks)
    % Sanity checks
    if ~(exist('ksdir','var'))
        error(['ksdir not defined'])
    end
    if ~(exist('phydir','var'))
        error(['phydir not defined'])
    end
    if ~(exist('data','var'))
        error(['data not defined'])
    end
    if ~(exist('tmp','var'))
        error(['tmp not defined'])
    end
    if ~(exist('config','var'))
        error(['config not defined'])
    end
    if ~(exist('chanmap','var'))
        error(['chanmap not defined'])
    end
    if ~(exist('numchans','var'))
        error(['numchans not defined'])
    end
    if ~(exist('start','var'))
        error(['start not defined'])
    end
    if ~(exist('stop','var'))
        error(['stop not defined'])
    end
    if ~(exist('sig','var'))
        error(['sig not defined'])
    end
    if ~(exist('fshigh','var'))
        error(['fshigh not defined'])
    end
    if ~(exist('nblocks','var'))
        error(['nblocks not defined'])
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
    % Import dependencies.
    addpath(genpath(ksdir));
    addpath(phydir);
    
    % Set up config.
    ops.trange = [ start stop ];
    ops.NchanTOT = numchans;
    run(config);
    ops.fproc = fullfile(tmp, 'temp_wh.dat');
    ops.chanMap = chanmap;
    
    % Run Kilosort
    fprintf('Looking for data inside %s \n', data);
    fs = dir(fullfile(data, 'chan*.mat'));
    if ~isempty(fs)
    	ops.chanMap = fullfile(data, fs(1).name);
    end

    ops.sig        = sig;  % spatial smoothness constant for registration
    ops.fshigh     = fshigh; % high-pass more aggresively
    ops.nblocks    = nblocks; % blocks for registration. 0 turns it off, 1 does rigid registration. Replaces "datashift" option. 

    % find the binary file
    fs          = [dir(fullfile(data, '*.bin')) dir(fullfile(data, '*.dat'))];
    ops.fbinary = fullfile(data, fs(1).name);
    

    rez                = preprocessDataSub(ops);
    rez                = datashift2(rez, 1);

    [rez, st3, tF]     = extract_spikes(rez);

    rez                = template_learning(rez, tF, st3);

    [rez, st3, tF]     = trackAndSort(rez);

    rez                = final_clustering(rez, tF, st3);

    rez                = find_merges(rez, 1);

    % save final results as rez2
    fprintf('Saving final results in phy \n')
    rezToPhy2(rez, data);
    
    % saving figures
    h(1) = figure(1);
    h(2) = figure(2);
    h(3) = figure(3);
    savefig(h, [data, '\kilosort_overview.fig'])
    close(h);
    
end