

import pathlib

import config

def create_cat_gt_command(cat_gt_params):

    cat_gt_command = []
    cat_gt_command.append("sh")
    cat_gt_command.append((pathlib.Path(config.cat_gt_directory, "runit.sh").as_posix()))

    for key, value in cat_gt_params.items():
        if key == "extras":
            extra_params = ["-"+i for i in value]
            cat_gt_command.extend(extra_params)
        else:
            if isinstance(value, list):
                str_value = [str(i) for i in value]
                cat_gt_command.append("-"+str(key)+"="+",".join(str_value))
            else:
                cat_gt_command.append("-"+str(key)+"="+str(value))
            
    return cat_gt_command
