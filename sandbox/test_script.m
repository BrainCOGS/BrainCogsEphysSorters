% Testscript to check whether kilosortbatch works as intended:
% tested on two files, for NPX1 and NP2 with associated config files.
% Further documentation on channel Maps + config is in the Readme.md

% Test 1 on NPX2
 
ksdir = 'C:\Users\ms81\Desktop\Kilosort\';
phydir = 'C:\Users\ms81\Desktop\npy-matlab';
data = 'D:\NPX_DATA\manuel\tmp\TowersTask_g0_imec2';
tmp = 'D:\NPX_DATA\manuel\tmp';
config = 'C:\Users\ms81\Desktop\code\config_manuel.m';
chanmap = 'C:\Users\ms81\Desktop\code\chanMap_npx2_hStripe_bottom2.mat';
numchans = 384;
start = 0;
stop = inf;
highpass = 300;
blocks = 5;
sig = 20; % spatial smoothness function for regression.

kilosortbatch(ksdir, phydir, data, tmp, config, chanmap, numchans, start, stop, sig, highpass, blocks)

% Test 2 on NPX2 
  
ksdir = 'C:\Users\ms81\Desktop\Kilosort\';
phydir = 'C:\Users\ms81\Desktop\npy-matlab';
data = 'D:\NPX_DATA\manuel\tmp\tmp_M012\imec0_catgt_2021-12-10_g0';
tmp = 'D:\NPX_DATA\manuel\tmp';
config = 'C:\Users\ms81\Desktop\code\config_manuel.m';
chanmap = 'C:\Users\ms81\Desktop\code\chanMap_npx1_staggered.mat';
numchans = 384;
start = 0;
stop = inf;
highpass = 300;
blocks = 5;
sig = 20; % spatial smoothness function for regression.

kilosortbatch(ksdir, phydir, data, tmp, config, chanmap, numchans, start, stop, sig, highpass, blocks)