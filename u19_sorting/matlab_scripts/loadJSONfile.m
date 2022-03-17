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

