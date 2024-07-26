#!/usr/bin/env python3
"""Gaussian build tool for cluster."""

import sys
import os
import re
import tarfile
import argparse
import shutil
from datetime import date, datetime
import subprocess
import typing as tp

import hpcnodes as hpc
import gxxtools as gt
import gxxtools.params as gtpar
import gxxtools.parse_ini as gtini
import gxxtools.sub.cmds as gtcmd

#  Gaussian Versions
# -------------------
GXX_VERSIONS = ('gdv', 'g09', 'g16')

#  Archives format
# -----------------
FMT_GXX = r'(g\w\w)\.?(\w\d\d[p+]?)'
FMT_EXT = r'(\.\w+|\.tar\.\w+)'
FMT_GXXARCH = re.compile(r'^' + FMT_GXX + FMT_EXT + r'$')
FMT_WORKING = re.compile(r'^working_' + FMT_GXX + r'_(\w{4}-?\w{2}-?\w{2})'
                         + FMT_EXT + '$')
FMT_VERSION = re.compile(r'^(g\w\w|\w{3}).?(\w\d\d[p+]?)$')


# =============
#   FUNCTIONS
# =============
def build_parser(gxx_rootpath: str, dev_rootpath: str,
                 mach_data: tp.Dict[str, tp.Sequence[tp.Any]]
                 ) -> argparse.ArgumentParser:
    """Build the parser for the commandline analysis.

    Builds the parser for the commandline analysis.

    Parameters
    ----------
    gxx_rootpath
        Root path to the Gaussian installation.
    dev_rootpath
        Root path to development trees.
    mach_data
        Machines/architectures data.

    Returns
    -------
    obj:`argparse.ArgumentParser`
        Commandline argument parser
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter
        )
    parser.add_argument(
        'archive', help="""\
Gaussian or working archive file, or version.
- The Gaussian archive is expected to have the form gXX[.]xxx[x][.ext]
  If no extension is provided, the archive is searched in a repository.
- The working should have the form working_gXX[.]xxx[x]_YYYYMMDD.ext
- The version can only be used together with '-c' to facilitate compilation
  The version should have the form AAA[.]xxx[x]
Where
XX: major version: DV, 09, 16...
xxx[x]: minor version (3 or 4 characters)
YYYYMMDD: date, as yearmonthday
AAA: trigram: either gXX or user defined (ex: jbl)
"""
        )
    parser.add_argument(
        '-c', '--compile', dest='mode', action='store_const', const='compile',
        help='Only compile the working, do not create anything.'
        )
    parser.add_argument(
        '-m', '--mach', nargs='+', dest='mach', choices=mach_data.keys(),
        help='Architectures on which the job has to be run.'
        )
    parser.add_argument(
        '--job', default='build',
        help='Job name'
        )
    parser.add_argument(
        '-u', '--update', dest='mode', action='store_const', const='update',
        help='Update the compilation directory with files present in archive'
        )
    parser.add_argument(
        '--gpath', help=f"""\
Root path of the Gaussian installation.
- Default: {gxx_rootpath}
- Structure:
gpath/
    gXX.xxx[x]/
        arch/
            gXX/
""")
    parser.add_argument(
        '--wpath', help=f"""\
Root path for the working tree.
- Default: {dev_rootpath}
- Structure:
wpath/
    gXX.xxx[x]/
        src/
        arch/
            ...
            exe-dir
with source files "symlinked" in each arch directory.
""")

    return parser


def build_working(archive: str,
                  wpath: str,
                  gpath: str,
                  src_dir: str,
                  mach_list: tp.List[str],
                  mach_data: tp.Dict[str, tp.Sequence[tp.Any]],
                  mode: str,
                  shell_head: str,
                  shell_main: str) -> tp.Dict[str, str]:
    """Build or update working tree.

    Builds or updates a Gaussian working tree.

    Parameters
    ----------
    archive
        Name of the archive.
    wpath
        Root path to working tree.
    gpath
        Root path to Gaussian installation directories.
    src_dir
        Directory name where source files are stored.
    mach_list
        List of micro-architectures on which to compile.
    mach_data
        Information on available micro-architectures.
    mode
        One of the values: deploy, compile, update.
    shell_head
        Header commands, that do not require further specifications.
    shell_main
        Main commands, which require further information.

    Returns
    -------
    dict
        List of shell commands for each requested architectures.
    """
    def create_symlink(file_src: str, link_dest: str) -> None:
        """Create a symbolic link.

        Checks if possible/necessary to create symbolic link and creates
        it if relevant.

        Parameters
        ----------
        file_src : str
            Source file
        link_dest : str
            Destination link
        mode : str
            Compilation mode
        """
        if os.path.exists(link_dest):
            if os.path.islink(link_dest):
                if _mode == 'deploy':
                    try:
                        os.remove(link_dest)
                    except OSError as err:
                        raise OSError(f'Unable to remove "{link_dest}"') \
                            from err
            else:
                raise OSError(
                    f'"{link_dest}" exists and is not a symbolic link')
        if not os.path.exists(link_dest):
            os.symlink(file_src, link_dest)

    #  Variable check
    # ----------------
    _mode = mode.lower()
    if _mode not in ('deploy', 'compile', 'update'):
        raise ValueError('Unrecognized mode')

    #  Parsing of the archive keyword
    # --------------------------------
    # We assume that the formatting has been checked beforehand
    arch_name = os.path.basename(archive)
    res = FMT_WORKING.match(arch_name)
    if res is not None:
        gxx, gxx_rev, _, _ = res.groups()
    else:
        gxx, gxx_rev = FMT_VERSION.match(arch_name).groups()
        if gxx not in GXX_VERSIONS:
            gxx = 'gdv'

    #  Sets Gaussian directories
    # ---------------------------
    dir_gaussian = f'{gxx}.{gxx_rev}'
    path_workdir = os.path.join(wpath, dir_gaussian)
    path_srcdir = os.path.join(path_workdir, src_dir)
    paths_mach = []
    for cpu_arch in mach_list:
        paths_mach.append(os.path.join(path_workdir,
                                       mach_data[cpu_arch][1]))

    #  Check existence of Gaussian directory
    # ---------------------------------------
    path_gaussian = os.path.join(gpath, dir_gaussian)
    if not os.path.exists(path_gaussian):
        print('WARNING: Gaussian installation directory does not exist.')
        print('         Please install it before.')
        sys.exit()

    #  Check existence of working directory
    # --------------------------------------
    if not os.path.exists(path_workdir):
        if _mode == 'deploy':
            print(
                f'Working root "{path_workdir}" does not exist. Creating it.')
            try:
                os.makedirs(path_workdir)
            except OSError as err:
                raise OSError('Cannot create working root. Exit.') from err
        else:
            raise OSError(f'Path "{path_workdir}" does not exist.')

    if not os.path.exists(path_srcdir):
        if _mode == 'deploy':
            print('Source directory for source tree does not exist.',
                  'Creating it...')
            try:
                os.makedirs(path_srcdir)
            except OSError as err:
                raise OSError('Cannot create source tree.') from err
        else:
            raise OSError(f'Path "{path_srcdir}" does not exist.')
    else:
        if _mode == 'deploy':
            print('Source tree already exists')
            print(f'REMINDER: The path is "{path_srcdir}"')
            while True:
                msg = '[k]eep, [b]ackup, [u]pdate or [r]emove it, or [q]uit? '
                ans = input(msg)
                if ans.lower() in ['b', 'k', 'r']:
                    break
                if ans.lower() == 'q':
                    sys.exit()
                else:
                    print('Incorrect value. Accepted values are: b, r, q')
            if ans.lower() == 'r':
                print('Source directory will be removed.')
                try:
                    shutil.rmtree(path_srcdir)
                    os.makedirs(path_srcdir)
                except shutil.Error as err:
                    raise OSError('Unable to remove old directory') from err
                except OSError as err:
                    raise OSError('Unable to create new directory') from err
            elif ans.lower() == 'k':
                print('No changes to source directory. \
The tree will be recompiled.')
                _mode = 'compile'
            elif ans.lower() == 'u':
                print('Source directory will be updated.')
                _mode = 'update'
            elif ans.lower() == 'b':
                print('Source directory will be backed up.')
                new_dir = f'{path_srcdir}.bak.' \
                    f'{date.today().strftime("%Y-%m-%d")}'
                try:
                    os.rename(path_srcdir, new_dir)
                    os.makedirs(path_srcdir)
                except OSError as err:
                    raise OSError(f'Cannot backup "{path_srcdir}"') from err

    #  Archive extraction
    # --------------------
    if _mode in ('deploy', 'update'):
        dir_cur = os.getcwd()
        os.chdir(path_srcdir)

        # Loop is done to remove leading directory
        try:
            with tarfile.open(os.path.join(dir_cur, archive), 'r:*') as tar:
                dir_lead = os.path.commonprefix(tar.getnames())
                for fobj in tar:
                    if dir_lead:
                        fobj.name = fobj.name.replace(dir_lead+'/', '', 1)
                    tar.extract(fobj)
        except tarfile.CompressionError as err:
            raise ValueError('Unsupported type of archive.') from err
        os.chdir(dir_cur)

    #  Archive-based directory structure
    # -----------------------------------
    if _mode in ('deploy', 'update'):
        # Directory creation
        # ^^^^^^^^^^^^^^^^^^
        for path_mach in paths_mach:
            if not os.path.exists(path_mach):
                if _mode == 'update':
                    print('Architecture directory "{path_mach}" does not '
                          + 'exist. Trying to build it')
                try:
                    os.mkdir(path_mach)
                except OSError as err:
                    raise OSError('Unable to create architecture-based '
                                  + f'directory "{path_mach}"') from err
            else:
                if _mode == 'deploy':
                    print(f'Architecture directory "{path_mach}" exists. '
                          + 'Removing it.')
                    shutil.rmtree(path_mach)
                    try:
                        os.mkdir(path_mach)
                    except shutil.Error as err:
                        raise OSError('Unable to remove old directory') \
                            from err
                    except OSError as err:
                        raise OSError('Cannot create architecture directory '
                                      + f'"{path_mach}"') from err
        #  Link source files
        #  ^^^^^^^^^^^^^^^^^
        os.chdir(path_workdir)
        dirs_ok = re.compile(r'\b(nutil|l\d+)\b')
        for path_mach in paths_mach:
            for item in os.listdir(src_dir):
                rel_path = os.path.join(src_dir, item)
                # Directories
                if os.path.isdir(rel_path) and re.search(dirs_ok, rel_path):
                    path_to = os.path.join(path_mach, item)
                    if not os.path.exists(path_to):
                        os.mkdir(path_to)
                    for fname in os.listdir(rel_path):
                        file_src = os.path.join(rel_path, fname)
                        if os.path.splitext(file_src)[1] in ('.F', '.make',
                                                             '.inc'):
                            path_from = os.path.join(path_workdir, file_src)
                            link_to = os.path.join(path_mach, item, fname)
                            create_symlink(path_from, link_to)
                elif item == 'Makefile':
                    path_from = os.path.join(path_workdir, src_dir, item)
                    link_to = os.path.join(path_mach, item)
                    create_symlink(path_from, link_to)
                elif os.path.splitext(item)[1] in ['.F', '.make', '.inc']:
                    path_from = os.path.join(path_workdir, item)
                    link_to = os.path.join(path_mach, item)
                    create_symlink(path_from, link_to)
    else:  # _mode == 'compile'
        for path_mach in paths_mach:
            if not os.path.exists(path_mach):
                raise OSError(
                    f'Architecture directory "{path_mach}" does not exist.')
        os.chdir(path_workdir)

    scripts = {}
    for cpu_arch in mach_list:
        dname = mach_data[cpu_arch][1]
        gdir = os.path.join(path_gaussian, dname)
        wdir = os.path.join(path_workdir, dname)
        scripts[cpu_arch] = \
            shell_head + shell_main.format(gxxdir=gdir, workdir=wdir, gxx=gxx)

    return scripts


def build_gaussian(archive: str,
                   gpath: str,
                   gxx_repository: str,
                   mach_list: tp.List[str],
                   mach_data: tp.Dict[str, tp.Sequence[tp.Any]],
                   mode: str,
                   shell_head: str,
                   shell_main: str) -> tp.Dict[str, str]:
    """Build or update a Gaussian installation.

    Builds or updates a full Gaussian installation.

    Parameters
    ----------
    archive
        Name of the archive.
    gpath
        Root path to Gaussian installation directories.
    gxx_repository
        Path to repository archives.
    mach_list
        List of micro-architectures on which to compile.
    mach_data
        Information on available micro-architectures.
    mode
        One of the value: deploy, compile.
    shell_head
        Header commands, that do not require further specifications.
    shell_main
        Main commands, which require further information.

    Returns
    -------
    dict
        List of shell commands for each requested architectures.

    Raises
    ------
    ValueError
        Errors related to arguments
    OSError
        Errors related to file/directory operations
    """
    #  Variable check
    # ----------------
    _mode = mode.lower()
    if _mode not in ('deploy', 'compile'):
        raise ValueError('Unrecognized mode')

    #  Parsing of the archive keyword
    # --------------------------------
    # We assume that the formatting has been checked beforehand
    print('Analyzing Gaussian archive name.')
    arch_name = os.path.basename(archive)
    res = FMT_GXXARCH.match(arch_name)
    if res is not None:
        gxx, gxx_rev, _ = res.groups()
        path_archive = os.path.abspath(archive)
    else:
        gxx, gxx_rev = FMT_VERSION.match(arch_name).groups()
        path_archive = None

    #  Gaussian archive lookup
    # -------------------------
    # Look in repository if not given by user
    if path_archive is None:
        print('Looking for Gaussian archive in repository.')
        files = []
        basename1 = gxx + gxx_rev + '.'
        basename2 = gxx + '.' + gxx_rev + '.'
        for item in os.listdir(gxx_repository):
            if item.startswith(basename1) or item.startswith(basename2):
                files.append(item)
        if len(files) == 0:
            raise OSError('Unable to find the Gaussian archive file.')
        elif len(files) > 1:
            raise OSError(
                'Too many matching archives. Specify better the archive.')
        else:
            path_archive = os.path.join(gxx_repository, files[0])
    # Check that archive exists
    if not os.path.exists(path_archive):
        raise OSError('Gaussian archive not found')

    #  Build Gaussian installation directories
    # -----------------------------------------
    dir_gaussian = f'{gxx}.{gxx_rev}'
    print('Verifying if previous installation exists.')
    path_gaussian = os.path.join(gpath, dir_gaussian)
    if os.path.exists(path_gaussian):
        if _mode == 'deploy':
            print('Previous installation exists. Removing it...')
            try:
                shutil.rmtree(path_gaussian)
                os.mkdir(path_gaussian)
            except shutil.Error as err:
                raise OSError('Unable to remove old directory') from err
            except OSError as err:
                raise OSError('Unable to create new directory') from err
        else:
            for cpu_arch in mach_list:
                newdir = os.path.join(path_gaussian, mach_data[cpu_arch][1])
                if os.path.exists(newdir):
                    print("Previous installation of",
                          f"{mach_data['cpu_arch'][1]} exists. Removing it.")
                    try:
                        shutil.rmtree(newdir)
                    except shutil.Error as err:
                        raise OSError('Unable to remove old directory') \
                            from err
                    except OSError as err:
                        raise OSError('Unable to create new directory') \
                            from err
    else:
        os.mkdir(path_gaussian)

    #  Archive extraction
    # --------------------
    print('Building Gaussian directory structure.')
    os.chdir(path_gaussian)
    # tarfile module seems to fail in some cases, trying to help it
    ext = os.path.splitext(path_archive)[1][1:]
    if ext == 'tbJ':
        oper = 'r:xz'
    elif ext == 'tbz':
        oper = 'r:bz2'
    else:
        oper = 'r:*'
    for cpu_arch in mach_list:
        dname = mach_data[cpu_arch][1]
        os.mkdir(dname)
        os.chdir(dname)
        with tarfile.open(path_archive, oper) as tar:
            tar.extractall()
        os.chdir(os.pardir)

    #  Compilation
    # -------------
    print('Building compilation scripts')

    scripts = {}
    for cpu_arch in mach_list:
        dname = mach_data[cpu_arch][1]
        gdir = os.path.join(path_gaussian, dname)
        scripts[cpu_arch] = shell_head \
            + shell_main.format(gxxdir=gdir, gxx=gxx, arch=cpu_arch)

    return scripts


def compiler_csh_cmds(name: str, root_path: str, full_path: str) -> str:
    """Build CSH commands to set compiler.

    Builds CSH commands to set the environment to use the compiler.

    Parameters
    ----------
    name
        Name of the compiler.
    root_path
        Root installation directory of the compiler.
    full_path
        Path to the actual directory.
        Sometimes, compilers use a special tree structure based on the
        version and the "flavor" (x86/x64) on top of the root path.
        `full_path` should provide the full resolved path.

    Returns
    -------
    str
        List of commands to run to set up the compiler variables and
        environment as a multi-line string.
    """
    if name.upper() == 'NVHPC':
        txt = f"""
setenv NVHPCSDK {root_path}
set nvbasedir = "{full_path}"
set nvcudadir = "${{nvbasedir}}/cuda"
set nvcompdir = "${{nvbasedir}}/compilers"
set nvmathdir = "${{nvbasedir}}/math_libs"
set nvcommdir = "${{nvbasedir}}/comm_libs"
set NVPATH = "${{nvcudadir}}/bin:${{nvcompdir}}/bin:${{nvcommdir}}/mpi/bin"
set NVLDPATH = \
"${{nvcudadir}}/lib64:${{nvcudadir}}/extras/CUPTI/lib64:${{nvcompdir}}/lib"
set NVLDPATH = "${{NVLDPATH}}:${{nvmathdir}}/lib64:${{nvcommdir}}/mpi/lib:"
set NVLDPATH = \
"${{NVLDPATH}}:${{nvcommdir}}/nccl/lib:${{nvcommdir}}/nvshmem/lib"
set NVCPATH = \
"${{nvmathdir}}/include:${{nvcommdir}}/mpi/include:${{nvcommdir}}/nccl/include"
set NVCPATH = "${{NVCPATH}}:${{nvcommdir}}/nvshmem/include"
set NVMANPATH = "${{nvcompdir}}/man"

# For Gaussian, set PGI-related environment vars to match NVHPC
setenv PGI ${{NVHPCSDK}}
setenv PGIDIR ${{nvcompdir}}

if ($?PATH) then
    setenv PATH ${{PATH}}:${{NVPATH}}
else
    setenv PATH ${{NVPATH}}
endif
if ($?LD_LIBRARY_PATH) then
    setenv LD_LIBRARY_PATH ${{LD_LIBRARY_PATH}}:${{NVLDPATH}}
else
    setenv LD_LIBRARY_PATH ${{NVLDPATH}}
endif
if ($?MANPATH) then
    setenv MANPATH ${{MANPATH}}:${{NVMANPATH}}
else
    setenv MANPATH ${{NVMANPATH}}
endif
"""
    elif name.upper() == 'PGI':
        txt = f"""
setenv PGIDIR {full_path}
setenv MPIfull_path {dir}/mpi/mpich

if ($?PATH) then
    setenv PATH ${{PATH}}:${{PGIDIR}}/bin
else
    setenv PATH ${{PGIDIR}}/bin
endif
if ($?LD_LIBRARY_PATH) then
    setenv LD_LIBRARY_PATH ${{LD_LIBRARY_PATH}}:${{PGIDIR}}/lib
else
    setenv LD_LIBRARY_PATH ${{PGIDIR}}/lib
endif
if ($?MANPATH) then
    setenv MANPATH ${{MANPATH}}:${{PGIDIR}}/man
else
    setenv MANPATH ${{PGIDIR}}/man
endif
"""
    else:
        raise KeyError('Unrecognized compiler')
    return txt


# ==================
#   INPUT ANALYSIS
# ==================
def main():
    """Run the main script."""
    # Check first if debugging mode enabled to override some initialization
    emulate = None
    rcfile = None
    cmd_args = sys.argv[1:].copy()
    todel = []
    for i, item in enumerate(cmd_args):
        if item.lower().startswith('--debug'):
            if '=' in item:
                emulate = item.split('=', maxsplit=1)[1].lower()
            gtpar.DEBUG = True
            todel.append(i)
        elif item.lower().startswith('--rc'):
            args = item.split('=')
            if len(args) == 1:
                print('ERROR: Missing configuration file for gxxtools')
                sys.exit(100)
            rcfile = args[-1]
            todel.append(i)
    for i in sorted(todel, reverse=True):
        del cmd_args[i]

    # Initialization
    # --------------
    gt.load_rc(emulate, rcfile)

    # Nodes/Architecture specification
    # --------------------------------
    if not os.path.exists(gtpar.paths['hpcini']):
        print('ERROR: Cannot find the HPC nodes specification file.')
        sys.exit(1)

    # Load HPC nodes/queue structure
    # ------------------------------
    gtpar.nodes_info = hpc.parse_ini(gtpar.paths['hpcini'])
    gtpar.queues_info = hpc.list_queues_nodes(gtpar.nodes_info)

    # Initialize scripts templates
    # ----------------------------
    # The scripts are built sequentially based on internal parameters
    csh_gxx_head = ''
    csh_dev_head = ''
    csh_gxx_main = ''
    csh_dev_main = ''

    # Get Gaussian and working installation paths
    # -------------------------------------------
    # Gaussian installation
    try:
        gxx_rootpath = gtini.get_path('gxxroot')
        gxx_repository = gtini.get_path('gxxrepo')
    except ValueError as e:
        print('ERROR: Gaussian basic paths not provided.')
        print(e)
        sys.exit(1)

    # Development tree top / working
    try:
        dev_rootpath = gtini.get_path('working')
    except ValueError as e:
        print('ERROR: Could not find information on the working structure')
        print(e)
        sys.exit(1)
    dev_srcdir = 'src'

    # Compiler information
    # --------------------
    try:
        compiler_dir = gtini.get_path('compdir')
        compiler_root = gtini.get_path('comproot')
        compiler_name = gtini.get_info('compiler')
        compiler_setenv = gtini.get_info('set_compiler')
    except ValueError as e:
        print('ERROR: Missing information on available compiler.')
        print(e)
        sys.exit(1)
    # Check if necessary to set up compiler environment
    if compiler_setenv:
        try:
            txt = compiler_csh_cmds(compiler_name, compiler_root, compiler_dir)
            csh_gxx_head += txt
            csh_dev_head += txt
        except KeyError:
            print('ERROR: Unrecognized compiler.')
            sys.exit(1)

    # Main script
    # -----------
    csh_gxx_main += '''
setenv {gxx}root {gxxdir}
rehash
cd ${gxx}root/{gxx}
source ${gxx}root/{gxx}/bsd/{gxx}.login
./bsd/bld{gxx} all {arch} >& build.log
'''
    csh_dev_main += '''
if ($?PATH) then
    setenv PYTHONPATH ''
endif
setenv {gxx}root {gxxdir}
rehash
source ${gxx}root/{gxx}/bsd/{gxx}.login
cd {workdir}
mk
'''

    # Compilation architectures
    # -------------------------
    # Build list of CPU architectures on which Gaussian may have to be built.
    mach_data = {}
    machs = {key.lower(): key for key in gtpar.nodes_info}
    gxx_builds = gtini.gxx_build_archs()
    if gxx_builds is None:
        print('No build information in GAUSSIAN block.')
        print('Exiting since nothing to do.')
        sys.exit(1)
    for arch, info in gxx_builds.items():
        if info[1].lower() in machs:
            mach_data[arch] = (gtpar.nodes_info[machs[info[1].lower()]],
                               info[0])
        else:
            print(f'ERROR: Unknown family {info[0]}')
            sys.exit(1)

    # Option building and parsing
    # ---------------------------
    # First check if debug mode requested:
    parser = build_parser(gxx_rootpath, dev_rootpath, mach_data)
    args = parser.parse_args(cmd_args)

    # Analysis of options
    # -------------------
    # Now check user options
    # Check list of machines/architectures to compile
    if args.mach is None:
        mach_list = list(mach_data.keys())[:]
    else:
        mach_list = args.mach

    arch_name = os.path.basename(args.archive)
    if FMT_VERSION.match(arch_name):
        if os.path.exists(args.archive):
            build = 'gaussian' if arch_name.startswith(GXX_VERSIONS) \
                else 'working'
        else:
            build = 'gaussian' if args.archive.startswith(GXX_VERSIONS) \
                else 'working'
    elif FMT_GXXARCH.match(arch_name):
        build = 'gaussian'
    elif FMT_WORKING.match(arch_name):
        build = 'working'
    else:
        print('ERROR: Unrecognized structure for the archive. See help.')
        sys.exit(1)

    if args.mode is None:
        mode = 'deploy'
    else:
        mode = args.mode

    gpath = args.gpath is None and gxx_rootpath or args.gpath
    if not os.path.exists(gpath):
        print('ERROR: Root path to Gaussian installation does not exist.')
        sys.exit(1)

    jobname = args.job

    if build == 'working':
        wpath = args.wpath is None and dev_rootpath or args.wpath
        if not os.path.exists(wpath):
            print(f'ERROR: Working tree root path "{wpath}" does not exist.')
            sys.exit(1)
        try:
            run_cmds = build_working(
                args.archive, wpath, gpath, dev_srcdir, mach_list,
                mach_data, mode, csh_dev_head, csh_dev_main)
        except (ValueError, OSError) as err:
            print(f'ERROR: Failed to {mode} working. '
                  + f'The following error was encountered:\n{err}')
            sys.exit(1)
    else:
        try:
            run_cmds = build_gaussian(
                args.archive, gpath, gxx_repository, mach_list,
                mach_data, mode, csh_gxx_head, csh_gxx_main)
        except (ValueError, OSError) as err:
            print(f'ERROR: Failed to {mode} Gaussian. '
                  + f'The following error was encountered:\n{err}')
            sys.exit(1)

    # Prepare run execution
    # ---------------------
    for arch in mach_list:
        extra = {
            'qname': sorted(mach_data[arch][0].supported_queues)[0]
        }
        if gtpar.server['submitter'] == 'qsub':
            sub_cmds = gtcmd.build_qsub_head(jobtitle=jobname, extraopts=extra,
                                             shell='tcsh')
            sub_exe = 'qsub'
        elif gtpar.server['submitter'] == 'slurm':
            sub_cmds = gtcmd.build_qsub_head(jobtitle=jobname, extraopts=extra,
                                             shell='tcsh')
            sub_exe = 'sbatch'
        else:
            sub_exe = None  # Trick to have sub_exe technically always defined.
            sub_cmds = None
            print('ERROR: Unsupported submitter program')
            sys.exit(1)
        fname = f'build_job_{arch}_{datetime.now().strftime("%Y%m%d_%H%M")}.sh'
        print(f'Writing script file: "{fname}"')
        with open(fname, 'w', encoding='utf-8') as cmdfile:
            cmdfile.write(sub_cmds)
            cmdfile.write(run_cmds[arch])
        cmd = subprocess.run([sub_exe, fname], text=True, check=True,
                             capture_output=True)
        print(f'Submission job ID: "{cmd.stdout.strip()}"')


if __name__ == '__main__':
    main()
