#!/usr/bin/python
import sys
from argparse import ArgumentParser
import os
import re
from os.path import isdir, isfile

parser = ArgumentParser(
    description='Rename all files matching the given regex. Let\'s say you want to replace all files containing \'abc\' at the first of their name with \'def\'. Then you can use the following command: rename -e \'^abc\' -r \'def\'')
parser.add_argument('adr', nargs='?', metavar='Address', type=str, help='Target address. In other words: Where?',
                    default='./')
parser.add_argument('-e', '--exp', required=True, type=str,
                    help='[Expression]. Python selection regex to select desired files.')
parser.add_argument('-r', '--replace', type=str, required=True,
                    help='Replace the matched part of the name with this statement. Place \'\' to remove selected part.')
parser.add_argument('-R', '--recursive', action='count', help='Do it recursively.')
parser.add_argument('-d', action='count',
                    help='if you are willing to rename only directories, then pass in -d and if you desire to rename files either, pass in -dd.')
parser.add_argument('-s', '--show', action='count', help='just show the files which are going to be changed and do not write any thing on disk.')
parser.add_argument('-v', '--verbose', action='count', help='Enable verbosity.')

args = parser.parse_args()

T_DEFAULT = '\x1b[m'  # reset to the defaults
T_WHITE = '\x1b[1:37m'  # white text
T_GREEN = '\x1b[1;32m'  # green text
T_BLUE = '\x1b[1;34m'  # blue text
T_GREEN_BOLD = '\x1b[1;33m'  # green text
T_BLUE_BOLD = '\x1b[31;35m'  # blue text


class Container:
    file = None
    result = None

    def __init__(self, file):
        self.file = file


class Processor:
    def walk(self, path, exp, replace_with, target_type, recursive, only_show, verbose):
        """
        start processing of input string
        :param path: target location
        :param exp: a regex to search for desired files and directories
        :param replace_with: matched parts of file names will be replaced with this statement
        :param target_type: 0: only files, 1: only directories, 2: files and directories
        :param recursive: obvious!
        :param only_show: do not alert file system
        :param verbose: report
        """

        (dirs, files) = self.get_files(path)
        if target_type == 0:  # rename only files
            self.handle_files(path, files, exp, replace_with, only_show, verbose)
        elif target_type == 1:  # rename only directories
            self.handle_dirs(path, dirs, exp, replace_with, recursive, only_show, verbose)
        else:  # rename both
            self.handle_files(path, files, exp, replace_with, only_show, verbose)
            self.handle_dirs(path, dirs, exp, replace_with, recursive, only_show, verbose)

    def get_files(self, path):
        files = []
        dirs = []

        items = os.listdir(path)
        for f in items:
            s = path + f
            if isfile(s):
                files.append(Container(f))
            if isdir(s):
                dirs.append(Container(f))

        return dirs, files

    def prepare_new_names(self, files, exp, replace_with, report, isDir=True):
        results = {}
        x = None
        colorCodes = (T_BLUE, T_BLUE_BOLD) if isDir else (T_GREEN, T_GREEN_BOLD)

        for i in range(len(files) - 1, -1, -1):
            x = files[i]
            x.result = re.sub(exp, replace_with, x.file)  # catch new name
            if x.result != x.file:  # if new name differs from the old one
                # check for duplication
                n = x.result
                k = 1
                while n in results:
                    n = k + x.result
                    k += 1
                x.result = n

                if report:
                    self.my_print(colorCodes[0], x.file, T_WHITE, '  -->  ', colorCodes[1], x.result, T_DEFAULT, '\n')
            else:
                del files[i]

    def my_print(self, *strs):
        for s in strs:
            sys.stdout.write(s)

    def handle_files(self, path, files, exp, replace_with, only_show, verbose):
        # rename current files
        self.prepare_new_names(files, exp, replace_with, only_show or verbose, False)
        if only_show is False:
            self.write_on_disk(path, files)

        # clean files
        del files
        # files.clear()

    def handle_dirs(self, path, dirs, exp, replace_with, recursive, only_show, verbose):
        # check out subdirectories
        if recursive == 1:
            for d in dirs:
                self.walk(path + d.file, exp, replace_with, target_type, recursive, only_show, verbose)

        # rename current directories
        self.prepare_new_names(dirs, exp, replace_with, only_show or verbose, True)
        if only_show is False:
            self.write_on_disk(path, dirs)

        # clean dirs
        del dirs
        # dirs.clear()

    def write_on_disk(self, path, files):
        for x in files:
            os.rename(path + x.file, path + x.result)


target_type = 0
if args.d is not None:
    target_type = args.d

if target_type > 2:
    raise Exception('Wrong input argument. Please use -h to see the help')

path = os.popen("realpath " + args.adr).read()
path = path.strip() + '/'

Processor().walk(path, args.exp, args.replace, target_type, args.recursive == 1, args.show == 1,
                 args.verbose == 1)
