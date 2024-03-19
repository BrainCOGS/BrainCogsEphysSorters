
import os, shutil, sys 
import subprocess


def move_to_root_folder(root_path, cur_path):
    for filename in os.listdir(cur_path):
        if os.path.isfile(os.path.join(cur_path, filename)):
            shutil.move(os.path.join(cur_path, filename), os.path.join(root_path, filename))
        elif os.path.isdir(os.path.join(cur_path, filename)):
            move_to_root_folder(root_path, os.path.join(cur_path, filename))
        else:
            sys.exit("Should never reach here.")
    # remove empty folders
    if cur_path != root_path:
        os.rmdir(cur_path)


def get_hostname():
    """
    Get hostname of system
    """

    hostname = ''

    p = subprocess.Popen("hostname", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.wait()

    stdout, stderr = p.communicate()
    if p.returncode == 0:
        hostname = stdout.decode('UTF-8')

    return hostname

    