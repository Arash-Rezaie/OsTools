#!/usr/bin/python
import os
import re
import subprocess
import sys
import threading
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
                    self.condition.wait(timeout=args.time)
                process_item_repository()
        except:
            print("timer faced an exception")
            pass
        finally:
            self.is_working = False
            release_resources()

    def interrupt(self):
        if self.is_working:
            if args.verbose:
                print('interrupting timer')
            self.interrupted = True
            with self.condition:
                self.condition.notify()


# read arguments ------------------------------------------
parser = ArgumentParser(prog="mkrd", description="""
This program (make-ram-disk) reduces write on hard drive by mapping a directory to the RAM. The process is:
1. make a directory at [base_mount_point]/[dir]~ 
2. mount the created directory in RAM 
4. use inotifywait over mounted directory
5. filter files by regex
6. put target file in update queue,
7. apply updates to [dir] according to a delay time""",
                        epilog="""
                        Example:
                        React project:  
                        ./mkrd.py ~/AProject -v --inotify-options "--exclude ./node_modules" -f '.+~\..+' --force
                        """)
parser.add_argument("dir", type=str, help="Target directory to be mapped on RAM")
parser.add_argument("--mount-options", type=str, dest="m_ops", default='',
                    help="options of tmpfs. you may need some customization over mounting")
parser.add_argument("--inotify-options", type=str, dest="i_ops", default='',
                    help="options of inotifywait. checkout its manual for more information")
parser.add_argument("-f", "--filter", type=str, dest="filter", default='',
                    help="Limit files which trigger the processor by a regex string")
parser.add_argument("-t", "--time", type=float, dest="time", default=60,
                    help="Continuously update actual files by delay (seconds)")
parser.add_argument("-v", "--verbose", dest="verbose", action='store_true', help="verbosity status")
parser.add_argument("--force", dest="force", help="force to mount dir", action="store_true")
parser.add_argument("--close", dest="close", help="finish the process", action="store_true")
parser.add_argument("--no-clean", dest="no_clean", help="do not clean copied files to the mount point",
                    action="store_true")
args = parser.parse_args()


# methods -------------------------------------------------
def exit_abnormal(msg):
    print("\nERROR: " + msg + '\n-----------------')
    exit(1)


def check_dest_existence(path):
    if not os.path.exists(path):
        exit_abnormal("\"{}\" not found".format(path))


def get_absolute_path(adr):
    return os.path.abspath(adr)


def check_arguments():
    args.dir = get_absolute_path(args.dir)
    check_dest_existence(args.dir)

    if not args.dir.endswith('/'):
        args.dir += '/'

    if args.time < 0:
        exit_abnormal("ERROR: time can not be negative")


def get_byte_as_str(byte_array):
    return byte_array.decode().strip("'\n ")


def report_cmd_output(output):
    s = get_byte_as_str(output)
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
        if type(error) == 'str':
            exit_abnormal(' -> ' + error)
        else:
            exit_abnormal(' -> ' + get_byte_as_str(error))
    if args.verbose:
        report_cmd_output(output)
    return output


def run_cmd_alive(command, consumer):
    global bg_process
    try:
        command = command
        if args.verbose:
            print(' > ' + command)
        bg_process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
        while True:
            output = get_byte_as_str(bg_process.stdout.readline())
            if len(output) > 0:
                consumer(output)
            elif bg_process.poll() is not None:
                break
    except:
        if args.verbose:
            print(' -> ' + str(sys.exc_info()))
    finally:
        bg_process.poll()
        finish_process()


def release_resources():
    output = ''
    if args.verbose:
        print("releasing resources")
    is_mounted = "is not" not in str(run_cmd("mountpoint {}".format(mount_point)))
    if is_mounted:
        output = get_byte_as_str(run_cmd("sudo umount " + mount_point))
    if len(output) == 0 and not args.no_clean:
        output = get_byte_as_str(run_cmd("sudo rm --recursive --force {}".format(mount_point)))
    if len(output) > 0:
        exit_abnormal("operation failed due to " + output)


def finish_process():
    global bg_process
    global timer_worker
    if bg_process is not None:
        print('kill inotifywait processor')
        bg_process.kill()
        bg_process = None
    if timer_worker.is_working:
        timer_worker.interrupt()
    else:
        release_resources()


def create_mount_point():
    if not os.path.exists(mount_point):
        os.mkdir(mount_point)
    mount_options = ""
    if args.m_ops != '':
        mount_options = "--options " + args.m_ops
    cmd = "sudo mount --types tmpfs {} {} {}".format(projectName, mount_point, mount_options)
    run_cmd(cmd)
    print("directory \"{}\" mounted at \"{}\"".format(args.dir, mount_point))


def handle_mount_point():
    if os.path.exists(mount_point):
        if not args.close and not args.force:
            exit_abnormal(
                "directory \"{}\" is mounted at \"{}\" already. umount it and clear its mount point or use options --force or --close".format(
                    projectName, mount_point))
        finish_process()
    if args.close:
        exit(0)
    else:
        create_mount_point()


def copy_files():
    print("please wait to copy the target dir to the mount point...")
    cmd = "sudo rsync --recursive --links --chmod=o+w --perms {} {}".format(args.dir, mount_point)
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


def get_smallest_common_path_between_2(min_path, path):
    while not path.startswith(min_path) and min_path != '/':
        min_path = min_path[:min_path.rfind('/', 0, -1) + 1]
    return min_path


def get_smallest_common_path(lst, l):
    if l == 1:
        return lst[0]
    else:
        lst.sort(key=len)
        smallest_path = lst[0]
        i = 0
        while i < l and smallest_path != '/':
            smallest_path = get_smallest_common_path_between_2(smallest_path, lst[i])
            i += 1
        return smallest_path


def process_item_repository():
    lst = item_repository.get_sorted_list()
    l = len(lst)
    if l > 0:
        scp = get_smallest_common_path(lst, l)
        rest_dir = scp[len(mount_point) + 1:]
        target_dir = args.dir + rest_dir
        if args.verbose:
            print("sync \"{}\" with \"{}\"".format(target_dir, scp))
        cmd = "rsync --recursive --links --delete {} {}".format(scp, target_dir)
        run_cmd(cmd)
    else:
        if args.verbose:
            print('no data to sync')


def initialize():
    global projectName
    global mount_point
    parentDir = args.dir[:args.dir.rfind('/', 0, -1) + 1]
    projectName = args.dir[len(parentDir):-1]
    mount_point = '/tmp/' + projectName


# body ----------------------------------------------------
# check user inputs
check_arguments()

# init data
bg_process = None
projectName = ''
mount_point = ''
item_repository = Repository()
timer_worker = TimerThread('timer worker')
initialize()

handle_mount_point()
copy_files()
timer_worker.start()
start_monitoring()
