#!/usr/bin/python3

# Please notice that inotifywait and rsync must be installed
# sample:
# sudo su ↲
# mkrd.py Project-Dir --verbose --inotify-options "--exclude ./node_modules" --filter '.+~\..+' --interval 180 --force ↲
#

import os
import re
import signal
import subprocess
import sys
import termios
import threading
import tty
from argparse import ArgumentParser


# classes -------------------------------------------------
class Repository:
    lock = threading.Lock()
    data = []

    def add(self, item):
        self.lock.acquire()
        if args.verbose:
            print('received item: ' + item)
        item = item[:item.rfind('/', 0, -1) + 1]
        exist = False
        i = len(self.data) - 1
        while i >= 0:
            if self.data[i] == item:
                exist = True
                break
            i -= 1
        if not exist:
            self.data.append(item)
        self.lock.release()

    def get_sorted_list(self):
        self.lock.acquire()
        lst = self.data.copy()
        self.data.clear()
        self.lock.release()
        return lst


class TimerThread(threading.Thread):
    def __init__(self, name):
        threading.Thread.__init__(self)
        self.name = name
        self.is_working = False
        self.interrupted = False
        self.condition = threading.Condition()

    def run(self):
        try:
            self.is_working = True
            if args.verbose:
                print('start timer')
            while not self.interrupted:
                with self.condition:
                    self.condition.wait(timeout=args.interval)
                    process_item_repository()
        except:
            print("timer faced an exception")
            process_item_repository()
        finally:
            self.is_working = False

    def interrupt(self):
        if self.is_working:
            if args.verbose:
                print('interrupting timer')
            self.interrupted = True
            with self.condition:
                self.condition.notify()


# therefore
# read arguments ------------------------------------------
parser = ArgumentParser(prog="mkrd", description="""
This program (make-ram-disk) reduces write on hard drive by mapping a directory to the RAM.
This script must get executed by super user. It is not recomended to sun by sudo because sudo affects only for a limitted time while you ususally need to run this script for long time.
The whole process is:
1. make directory /tmp/ProjectName
2. mount the created directory in RAM
3. use inotifywait over mounted directory (you need this tool installed)
4. periodically sync files in ram and the target dir which are not filtered""",
                        epilog="""
                        Example:
                        React project:
                        `mkrd.py ProjectPath --verbose --inotify-options "--exclude ./node_modules" --filter '.+~\..+' --time 180 --force`.
                        This command creates /tmp/ProjectName directory as a partition in RAM (force recreation the directory),
                        After that, it monitors the whole ram disk changes except '/tmp/ProjectName/node_modules' and
                        files like '/tmp/ProjectName/*~.*'.
                        Finally,  /tmp/ProjectName and the given project directory will be synced every 3 minutes.
                        """)

parser.add_argument("dir", type=str, help="Target directory to be mapped on RAM")

parser.add_argument("--mount-options", type=str, dest="m_ops", default='',
                    help="options of tmpfs. you may need some customization over mounting")

parser.add_argument("--inotify-options", type=str, dest="i_ops", default='',
                    help="options of inotifywait. checkout its manual for more information")

parser.add_argument("-f", "--filter", type=str, dest="filter", default='',
                    help="Limit files which trigger the processor by a regex string")

parser.add_argument("-i", "--interval", type=float, dest="interval", default=60,
                    help="Continuously update actual files by delay (seconds) [default 60 seconds]")

parser.add_argument("-v", "--verbose", dest="verbose", action='store_true', help="verbosity status")

parser.add_argument("--force", dest="force",
                    help="when mount point exists already, this option tries to remove the mount point at first and "
                         "if it fails because of being busy or any thing else, hiring the current mount point will be "
                         "the way. so --mount-options will be ignored",
                    action="store_true")

parser.add_argument("--close", dest="close", help="finish the process", action="store_true")

parser.add_argument("--no-clean", dest="no_clean", help="do not clean copied files to the mount point",
                    action="store_true")

args = parser.parse_args()


# methods -------------------------------------------------
def convert_to_str(obj):
    obj_type = type(obj)
    if obj_type == str:
        return obj
    elif obj_type == bytes:
        return obj.decode().strip("'\n ")
    elif obj_type == Exception:
        return str(obj)
    else:
        raise Exception('could not convert {} to string'.format(obj_type))


def exit_abnormal(exp):
    print('\nERROR>\n{}\n-----------------'.format(exp))
    exit(1)


def check_dest_existence(path):
    if not os.path.exists(path):
        raise Exception("\"{}\" not found".format(path))


def get_absolute_path(adr):
    return os.path.abspath(adr)


def check_user():
    output = convert_to_str(run_cmd("id -u"))
    if output != '0':
        raise Exception("Switch to root user, then execute this command")


def check_arguments():
    args.dir = get_absolute_path(args.dir)
    check_dest_existence(args.dir)

    if not args.dir.endswith('/'):
        args.dir += '/'

    if args.interval < 0:
        raise Exception("interval can not be negative")


def report_cmd_output(output):
    s = convert_to_str(output)
    if len(s) == 0:
        s = 'SUCCESSFUL'
    print(' -> ' + s)


def run_cmd(command):
    command = command
    if args.verbose:
        print(' > ' + command)
    process = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = error = False
    try:
        output, error = process.communicate()
    except:
        error = str(sys.exc_info())
    if error:
        raise Exception(convert_to_str(error))
    if args.verbose:
        report_cmd_output(output)
    return output


def run_cmd_alive(command, consumer):
    global bg_process
    global is_proc_broken

    while not is_proc_broken:
        try:
            command = command
            if args.verbose:
                print(' > ' + command)
            bg_process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
            while True:
                output = convert_to_str(bg_process.stdout.readline())
                if len(output) > 0:
                    consumer(output)
                elif bg_process.poll() is not None:
                    break
        except:
            is_proc_broken = True
            if args.verbose:
                print(' -> ' + convert_to_str(sys.exc_info()))
        finally:
            if is_proc_broken:
                bg_process.poll()
                finish_process()


def release_resources():
    output = ''
    if args.verbose:
        print("releasing resources")
    is_mounted = "is not" not in str(run_cmd("mountpoint {}".format(mount_point)))
    if is_mounted:
        output = convert_to_str(run_cmd("umount " + mount_point))
    if len(output) == 0 and not args.no_clean:
        output = convert_to_str(run_cmd("rm --recursive --force {}".format(mount_point)))
    if len(output) > 0:
        raise Exception(output)


def finish_process():
    global bg_process
    global timer_worker

    if bg_process is not None:
        if args.verbose:
            print('kill inotifywait processor')
        bg_process.kill()
        bg_process = None
    if timer_worker.is_working:
        if args.verbose:
            print('stop worker')
        timer_worker.interrupt()
        timer_worker.join()
    try:
        release_resources()
    except Exception as e1:
        exit_abnormal('operation failed due to: "{}"'.format(e1))
    else:
        exit(0)


def create_mount_point():
    os.mkdir(mount_point)
    mount_options = ""
    if args.m_ops != '':
        mount_options = "--options " + args.m_ops
    cmd = "mount --types tmpfs {} {} {}".format(projectName, mount_point, mount_options)
    run_cmd(cmd)
    print("directory \"{}\" mounted at \"{}\"".format(args.dir, mount_point))


def handle_mount_point():
    if args.close:
        finish_process()
        print('this message must not show up')

    if os.path.exists(mount_point):
        print('directory "{}" is already mounted at "{}"'.format(projectName, mount_point))
        if args.force:
            try:
                release_resources()
                create_mount_point()
            except Exception as e1:
                if args.verbose:
                    print(
                        '\nrecreating mount point failed due to: "{}" so mount options will be ignored\nreusing "{}"...'.format(
                            e1, mount_point))
        else:
            print('please use --close or --force options')
            exit(0)
    else:
        try:
            create_mount_point()
        except Exception as e1:
            raise Exception('creating mount point failed due to: "{}"'.format(e1))


def copy_files():
    print("please wait to copy the target dir to the mount point...")
    cmd = "rsync --recursive --links --chmod=o+w --perms {} {}".format(args.dir, mount_point)
    run_cmd(cmd)


def file_change_listener(item):
    if args.filter == '' or re.search(args.filter, item) is None:
        global item_repository
        item_repository.add(item)


def start_monitoring():
    print("start monitoring mount point")
    cmd = "inotifywait -e modify -e attrib -e moved_to -e moved_from -e create -e delete --format '%w%f' --monitor --recursive "
    cmd += '{} {}'.format(mount_point, args.i_ops)
    run_cmd_alive(cmd, file_change_listener)
    print("ready ----------------------")


def get_smallest_common_path_between_2(min_path, path):
    while not path.startswith(min_path) and min_path != '/':
        min_path = min_path[:min_path.rfind('/', 0, -1) + 1]
    return min_path


def get_smallest_common_path(lst, l1):
    if l1 == 1:
        return lst[0]
    else:
        lst.sort(key=len)
        smallest_path = lst[0]
        i = 0
        while i < l1 and smallest_path != '/':
            smallest_path = get_smallest_common_path_between_2(smallest_path, lst[i])
            i += 1
        return smallest_path


def process_item_repository():
    lst = item_repository.get_sorted_list()
    l1 = len(lst)
    if l1 > 0:
        scp = get_smallest_common_path(lst, l1)
        rest_dir = scp[len(mount_point) + 1:]
        target_dir = args.dir + rest_dir
        if args.verbose:
            print("sync \"{}\" with \"{}\"".format(target_dir, scp))
        cmd = "rsync --recursive --links --delete {} {}".format(scp, target_dir)
        run_cmd(cmd)
    else:
        if args.verbose:
            print('nothing found to sync')


def initialize():
    global projectName
    global mount_point
    parent_dir = args.dir[:args.dir.rfind('/', 0, -1) + 1]
    projectName = args.dir[len(parent_dir):-1]
    mount_point = '/tmp/' + projectName


def read_key_pressed():
    file_descriptors = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin)
    x = sys.stdin.read(1)[0]
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, file_descriptors)
    return x


def handle_signal(sig_num, frame):
    global is_proc_broken

    print("\nPress S to sync or Any key to quit (s|*)", end="? ", flush=True)
    answer = read_key_pressed()
    print("")
    if answer == 's' or answer == 'S':
        print('start syncing...')
        process_item_repository()
        print('syncing finished')
    else:
        is_proc_broken = True
        raise Exception("break")


# body ----------------------------------------------------
# check user inputs
try:
    check_user()
    check_arguments()
except Exception as e:
    exit_abnormal(e)

# init data
bg_process = None
projectName = ''
mount_point = ''
is_proc_broken = False
item_repository = Repository()
timer_worker = TimerThread('timer worker')
initialize()
try:
    handle_mount_point()
    copy_files()
    timer_worker.start()
    signal.signal(signal.SIGINT, handle_signal)
    start_monitoring()
except Exception as e:
    finish_process()
