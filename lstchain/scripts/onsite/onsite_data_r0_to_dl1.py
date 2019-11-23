#!/usr//bin/env python

## Code to reduce R0 data to DL1 onsite (La Palma cluster)


import sys
import os
import shutil
import random
import argparse
import calendar
import lstchain
from lstchain.io.data_management import *

parser = argparse.ArgumentParser(description="Real Data R0 to DL1")

parser.add_argument('input_dir', type=str,
                    help='path to the files directory to analyse',
                    )

parser.add_argument('--config_file', '-conf', action='store', type=str,
                    dest='config_file',
                    help='Path to a configuration file. If none is given, a standard configuration is applied',
                    default=None
                    )

# For Real Data:

parser.add_argument('--pedestal_path', '-pedestal', action='store', type=str,
                    dest='pedestal',
                    help='Path to a pedestal file. Required only for real data analysis.',
                    default=None
                    )

parser.add_argument('--calibration_path', '-calib', action='store', type=str,
                    dest='calib',
                    help='Path to a calibration file. Required only for real data analysis.',
                    default=None
                    )

parser.add_argument('--pointing_file_path', '-pointing', action='store', type=str,
                    dest='pointing',
                    help='path to the pointing file from drive. Required only for real data analysis',
                    default=None,
                    )

# parser.add_argument('--n_files_per_dl1', '-nfdl1', action='store', type=str,
#                     dest='n_files_per_dl1',
#                     help='Number of input files merged in one DL1. If 0, the number of files per DL1 is computed based '
#                          'on the size of the DL0 files and the expected reduction factor of 50 '
#                          'to obtain DL1 files of ~100 MB. Else, use fixed number of files',
#                     default=0,
#                     )

today = calendar.datetime.date.today()
default_prod_id = f'{today.year:04d}{today.month:02d}{today.day:02d}_v{lstchain.__version__}_v00'

parser.add_argument('--prod_id', action='store', type=str,
                    dest='prod_id',
                    help="Production ID",
                    default=default_prod_id,
                    )

args = parser.parse_args()

# source env onsite - can be changed for custom install
source_env = 'source /local/home/lstanalyzer/.bashrc; conda activate cta;'


def main():

    PROD_ID = args.prod_id
    # NFILES_PER_DL1 = args.n_files_per_dl1
    #
    # DESIRED_DL1_SIZE_MB = 100

    R0_DATA_DIR = args.input_dir

    print("\n ==== START {} ==== \n".format(sys.argv[0]))

    print("Working on DL0 files in {}".format(R0_DATA_DIR))

    check_data_path(R0_DATA_DIR)

    raw_files_list = get_input_filelist(R0_DATA_DIR)

    # if NFILES_PER_DL1 == 0:
    #     size_dl0 = os.stat(raw_files_list[0]).st_size / 1e6
    #     reduction_dl0_dl1 = 5
    #     size_dl1 = size_dl0 / reduction_dl0_dl1
    #     NFILES_PER_DL1 = max(1, int(DESIRED_DL1_SIZE_MB / size_dl1))

    number_files = len(raw_files_list)
    query_yes_no(f"{number_files} jobs to launch, ok?")

    RUNNING_DIR = os.path.join(R0_DATA_DIR.replace('R0', 'running_analysis'), PROD_ID)

    JOB_LOGS = os.path.join(RUNNING_DIR, 'job_logs')
    DL1_DATA_DIR = os.path.join(RUNNING_DIR, 'DL1')
    # ADD CLEAN QUESTION

    print("RUNNING_DIR: ", RUNNING_DIR)
    print("JOB_LOGS DIR: ", JOB_LOGS)
    print("DL1 DATA DIR: ", DL1_DATA_DIR)

    for dir in [RUNNING_DIR, DL1_DATA_DIR, JOB_LOGS]:
        check_and_make_dir(dir)

    list = raw_files_list

    dir_lists = os.path.join(RUNNING_DIR, 'file_lists')
    output_dir = os.path.join(RUNNING_DIR, 'DL1')
    check_and_make_dir(dir_lists)
    check_and_make_dir(output_dir)
    print("output dir: ", output_dir)

    # number_of_sublists = len(list) // NFILES_PER_DL1 + int(len(list) % NFILES_PER_DL1 > 0)

    counter = 0
    for file in raw_files_list:
        jobo = os.path.join(JOB_LOGS, "job{}.o".format(counter))
        jobe = os.path.join(JOB_LOGS, "job{}.e".format(counter))
        cc = ' -conf {}'.format(args.config_file) if args.config_file is not None else ' '
        base_cmd = f'"lstchain_data_r0_to_dl1 -f {file} -o {output_dir} -pedestal {args.pedestal} -calib {args.calib} ' \
            f'-pointing {args.pointing} {cc}"'
        cmd = 'sbatch -e {} -o {} --wrap {}'.format(jobe, jobo, base_cmd)
        # os.system(cmd)
        print(cmd)
        counter += 1


    # copy this script itself into logs

    for f in [sys.argv[0], args.pedestal, args.calib, args.pointing]:
        shutil.copyfile(f, os.path.join(RUNNING_DIR, os.path.basename(f)))

    # copy config file into logs
    if args.config_file is not None:
        shutil.copy(args.config_file, os.path.join(RUNNING_DIR, os.path.basename(args.config_file)))

    print("\n ==== END {} ==== \n".format(sys.argv[0]))


if __name__ == '__main__':
    main()
