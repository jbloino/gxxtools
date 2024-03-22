#!/usr/bin/env python3
"""Gaussian general submitter system.

This small program manages submission over different platforms.

author: Julien Bloino (julien.bloino@sns.it)
last changes: 2024.03.16
"""

import os
import sys
import re
import argparse
import subprocess
import typing as tp

import hpcnodes as hpc
import gxxtools as gt
import gxxtools.params as gtpar
# import gxxtools.sub as gtsub
import gxxtools.parse_ini as gtini
import gxxtools.sub.arch as gthpc
import gxxtools.sub.gaussian as gtgxx
import gxxtools.sub.cmds as gtcmd

# Program name is generated from commandline
PROGNAME = os.path.basename(sys.argv[0])

JOB_PID = str(os.getpid())
WORKDIR = os.getcwd()


# Command-line Parser
# ===================
def build_parser() -> argparse.ArgumentParser:
    """Build the options parser.

    Builds the full option parser.

    Returns
    -------
    :obj:`ArgumentParser`
        `ArgumentParser` object
    """
    parser = argparse.ArgumentParser(
            prog=PROGNAME,
            formatter_class=argparse.RawTextHelpFormatter)

    # Help documentation
    # ------------------
    doc_queues = gthpc.parser_doc_queues()
    doc_gaussian = gtgxx.parser_doc_gaussian()
    #  MANDATORY ARGUMENTS
    # ---------------------
    parser.add_argument('infile', help="Gaussian input file(s)", nargs='*')
    #  OPTIONS
    # ---------
    # Qsub-related options
    # ^^^^^^^^^^^^^^^^^^^^
    queue = parser.add_argument_group('queue-related options')
    queue.add_argument(
        '-j', '--job', dest='job',
        help='Sets the job name. (NOTE: PBS truncates after 15 characters')
    queue.add_argument(
        '-m', '--mail', dest='mail', action='store_true',
        help='Sends notification emails')
    queue.add_argument(
        '--mailto', dest='mailto',
        help='Sends notification emails')
    queue.add_argument(
        '--multi', choices=('parallel', 'serial'),
        help='Runs multiple jobs in a single submission')
    queue.add_argument(
        '--group', dest='group', type=str,
        help='User group')
    queue.add_argument(
        '-p', '--project', dest='project',
        help='Defines the project to run the calculation')
    queue.add_argument(
        '-P', '--print', dest='prtinfo', action='store_true',
        help='Print information about the submission process')
    if doc_queues is not None:
        queue.add_argument(
            '-q', '--queue', dest='queue', default=gthpc.queues_default(),
            help=f'Sets the queue type.\n{doc_queues}',
            metavar='QUEUE')
    queue.add_argument(
        '-S', '--silent', dest='silent', action='store_true',
        help='''\
Do not save standard output and error in files
WARNING: The consequence will be a loss of these outputs''')
    # Expert options
    # ^^^^^^^^^^^^^^
    expert = parser.add_argument_group('expert usage')
    expert.add_argument(
        '--cpto', dest='cpto', nargs='+',
        help='Files to be copied to the local scratch (dumb copy, no check)')
    expert.add_argument(
        '--cpfrom', dest='cpfrom', nargs='+',
        help='Files to be copied from the local scratch (dumb copy, '
        + 'no check)')
    expert.add_argument(
        '--nojob', dest='nojob', action='store_true',
        help='Do not run job. Simply generate the input sequence.')
    expert.add_argument(
        '-X', '--expert', dest='expert', action='count',
        help='''\
Expert use, remove several safeguards.
DO NOT USE except if you REALLY know what you are doing.
An incorrect usage may result in a BAN from the HPC resources.
Can be cumulated.
- 1: bypass input analysis
''')
    # Gaussian-related options
    # ^^^^^^^^^^^^^^^^^^^^^^^^
    gaussian = parser.add_argument_group('Gaussian-related options')
    gaussian.add_argument(
        '-c', '--chk', dest='gxxchk', metavar='CHK_FILENAME',
        help='Sets the checkpoint filename')
    gaussian.add_argument(
        '-g', '--gaussian', dest='gxxver', metavar='GAUSSIAN',
        default=gtgxx.gaussian_default(),
        help=f'{doc_gaussian}')
    gaussian.add_argument(
        '-i', '--ignore', dest='gxxl0I', nargs='+', metavar='L0_IGNORE',
        choices=['c', 'chk', 'r', 'rwf', 'a', 'all'],
        help='''\
Ignore the following options in input and command list:
+ c, chk: ignore the checkpoint file (omit it in the input, do not copy it)
+ r, rwf: ignore the read-write file (omit it in the input, do not copy it)
+ a, all: ignore both checkpoint and read-write files
''')
    gaussian.add_argument(
        '-k', '--keep', dest='gxxl0K', action='append', metavar='L0_KEEP',
        default=[],
        choices=['c', 'chk', 'm', 'mem', 'p', 'proc', 'r', 'rwf', 'a', 'all'],
        help='''\
Keeps user-given parameters to control the Gaussian job in input file.
The possible options are:
+ c, chk:  Keeps checkpoint filename given in input
+ m, mem:  Keeps memory requirements given in input
+ p, proc: Keeps number of proc. required in input
+ r, rwf:  Keeps read-write file given in input
+ a, all:  Keeps all data list above
''')
    gaussian.add_argument(
        '-o', '--out', dest='gxxlog', metavar='LOG_FILENAME',
        help='Sets the output filename')
    gaussian.add_argument(
        '-r', '--rwf', dest='gxxrwf', metavar='RWF_FILENAME',
        help='''\
Sets the read-write filename (Expert use!).
"auto" sets automatically the rwf from the input filename.''')
    # Architecture/Installation-specific options
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    arch = parser.add_argument_group('Architecture-specific options')
    gthpc.parser_add_opts(arch)
    gtgxx.parser_add_opts(arch)

    return parser


def parse_options(parser: argparse.ArgumentParser) -> tp.Dict[str, tp.Any]:
    """Parse and analyze options.

    Parses commandline and other options and generate all relevant
    information.

    Parameters
    ----------
    parser
        Commandline argument parser.

    Returns
    -------
    dict
        Settings for the submission and execution of Gaussian.

    Notes
    -----
    The function manages directly the termination of the program since
    there are many exit points while building the parameters.

    """
    argopts = parser.parse_args()

    options = {
        'gxxlnk0': argopts.gxxl0K,
        'expert': argopts.expert,
        'cpto': argopts.cpto,
        'cpfrom': argopts.cpfrom,
        'mailto': '',
        'project': argopts.project,
        'silent': argopts.silent,
        'prtinfo': argopts.prtinfo,
        'nojob': argopts.nojob,
    }
    
    # Query options
    # ^^^^^^^^^^^^^
    # Query options are expected to exit after result.
    if gthpc.parse_queries(argopts):
        sys.exit()
    if gtgxx.parse_queries(argopts):
        sys.exit()
    # Check multiple/single input file(s)
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    num_infiles = len(argopts.infile)
    # We need at least 1 input file
    if num_infiles == 0:
        print('ERROR: Missing Gaussian input file')
        sys.exit(2)
    multi_gjf = num_infiles > 1
    if argopts.multi is None:
        options['multijob'] = 'serial' if multi_gjf else 'no'
    else:
        options['multijob'] = argopts.multi
    # Initialization qsub arguments structure
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    options['subargs'] = []
    # Queue/Architecture specifications
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    try:
        options['qncpus'], options['qmem'], options['qinfo'], \
            options['tmpdir'] = gthpc.get_arch_spec(argopts, jobid=JOB_PID)
    except KeyError:
        print('ERROR: Unsupported queue')
        sys.exit(2)
    except ValueError as err:
        print('ERROR: Wrong virtual queue specification')
        print(f'Reason: {err}')
        sys.exit(2)
    # Gaussian specifications
    # ^^^^^^^^^^^^^^^^^^^^^^^
    options['gxx'], options['gxx_cmds'], options['gxx_exedir'] = \
        gtgxx.get_gxx_spec(argopts)
    # Definition of Gaussian input file
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    options['filebase'] = []
    options['ginfiles'] = []
    options['infiles'] = []
    options['n_input'] = 0
    for infile in argopts.infile:
        if not os.path.exists(infile):
            print(f'ERROR: Cannot find Gaussian input file "{infile}"')
            sys.exit()
        options['infiles'].append(infile)
        options['n_input'] += 1
        full_path = os.path.abspath(infile)
        options['ginfiles'].append(full_path)
        options['filebase'].append(os.path.splitext(full_path)[0])
    # Definition of Gaussian output file
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    options['logfiles'] = []
    if argopts.gxxlog:
        if multi_gjf:
            print('ERROR: Output file not supported for a multi-job')
            sys.exit()
        options['logfiles'].append(os.path.abspath(argopts.gxxlog))
    else:
        for base in options['filebase']:
            options['logfiles'].append(base + '.log')
    # Definition of Gaussian internal files
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    # NOTE: A "None" file means to keep what exits. "False" to remove it
    # - CHECKPOINT FILE
    options['chkfiles'] = []
    if argopts.gxxchk:
        if multi_gjf:
            print('ERROR: Checkpoint file not supported for a multi-job')
            sys.exit()
        options['chkfiles'].append(os.path.abspath(argopts.gxxchk))
    elif not set(['c', 'chk', 'a', 'all']) & set(argopts.gxxl0K):
        for base in options['filebase']:
            options['chkfiles'].append(base + '.chk')
    else:
        options['chkfiles'] = None
    # - READ-WRITE FILE
    options['rwffiles'] = []
    if argopts.gxxrwf:
        if argopts.gxxrwf.lower() == 'auto':
            for base in options['filebase']:
                options['rwffiles'].append(base + '.rwf')
        else:
            if multi_gjf:
                print('ERROR: RWF file not supported for a multi-job')
                sys.exit()
            options['rwffiles'].append(os.path.abspath(argopts.gxxrwf))
    elif set(['r', 'rwf', 'a', 'all']) & set(argopts.gxxl0K):
        options['rwffiles'] = None
    else:
        options['rwffiles'] = False
    # Job name
    # ^^^^^^^^
    if argopts.job:
        options['jobname'] = argopts.job
    else:
        if multi_gjf:
            options['jobname'] = 'multi-job'
        else:
            options['jobname'] = os.path.basename(options['filebase'][0])
    # Check if job name compliant with PBS restrictions
    # Starting digit
    if options['jobname'][0].isdigit():
        print('NOTE: First character of jobname is a digit.\n'
              + 'Letter "a" is preprended.')
        options['jobname'] = 'a' + options['jobname']
    # Less than 15 chars
    if len(options['jobname']) > 15:
        options['jobname'] = options['jobname'][:15]
        fmt = 'NOTE: Job name exceeds 15 chars. Truncating to {}'
        print(fmt.format(options['jobname']))
    # Mail specification
    # ^^^^^^^^^^^^^^^^^^
    if argopts.mail:
        if argopts.mailto:
            options['mailto'] = argopts.mailto
        else:
            if gtpar.server['mailaddr']:
                fmt = gtpar.server['mailaddr']
                options['mailto'] = fmt.format(user=gtpar.user)
            else:
                print('ERROR: Cannot define email address.')
                sys.exit(1)
        if {'{', '}'} & set(options['mailto']):
            print('ERROR: Could not fully resolve the email address.')
            print('       Quitting to avoid making a mess.')
            sys.exit(1)

    return options


def set_resources(options: tp.Dict[str, tp.Any]
                  ) -> tp.Tuple[tp.Optional[int], tp.Optional[int]]:
    """Set hardware resources.

    Based on user options and requirements, sets suitable hardware
    resources for calculations.

    Parameters
    ----------
    options
        Settings for the submission and execution of Gaussian.

    Returns
    -------
    int
        Number of processors
    int
        Allocatable memory

    Raises
    ------
    ValueError
        Insufficient resources.
    """
    if {'p', 'proc', 'a', 'all'} & set(options['gxxlnk0']):
        nprocs = None
    elif options['n_input'] > 1 and options['multijob'] == 'parallel':
        nprocs = options['qncpus']['base']//options['n_input']
        if nprocs == 0:
            msg = 'ERROR: Too many parallel jobs for the number of ' \
                + 'processing units'
            raise ValueError(msg)
    else:
        nprocs = options['qncpus']['base']
    if {'m', 'mem', 'a', 'all'} & set(options['gxxlnk0']):
        mem = None
    else:
        if nprocs is None:
            factor = 1.
        else:
            factor = min(1., nprocs/options['qncpus']['base'])
        mem_byte = int(options['qmem']['base']*factor)
        mem = hpc.bytes_units(mem_byte, 0, False, 'g')
        if mem.startswith('0'):
            mem = hpc.bytes_units(mem_byte, 0, False, 'm')

    return nprocs, mem


def check_gjf(gjf_ref: str,
              gjf_new: str,
              dat_P: tp.Optional[int] = None,
              dat_M: tp.Optional[str] = None,
              file_chk: tp.Optional[tp.Union[str, bool]] = None,
              file_rwf: tp.Optional[tp.Union[str, bool]] = None,
              rootdir: tp.Optional[str] = None
              ) -> tp.Tuple[int, str, tp.List[tp.List[str]]]:
    """Analyses and completes Gaussian input.

    Checks and modifies a Gaussian input file and extracts relevant
        information for the submission script:
    - Hardware resources to be be read from the input file
    - Files to copy.

    Parameters
    ----------
    gjf_new
        New input file where completed Gaussian directives are stored.
    dat_P
        Number of processors to request in Gaussian job.
        Otherwise, use the value in reference input file.
    dat_M
        Memory requirement.
        Otherwise, use the value in reference input file.
    file_chk
        Checkpoint file to use.
        If None, do not specify it in input.
    rootdir
        Root directory to look for files.

    Returns
    -------
    int
        Number of processors actually requested.
    str
        Actual memory requirements.
    list
        List of files to copy from/to the computing node.
    """

    def write_hdr(fobj: tp.IO[str],
                  dat_P: tp.Optional[int] = None,
                  dat_M: tp.Optional[str] = None,
                  file_chk: tp.Optional[tp.Union[str, bool]] = None,
                  file_rwf: tp.Optional[tp.Union[str, bool]] = None
                  ) -> None:
        """Small function to write Link0 header.

        Parameters
        ----------
        dat_P : int, optional
            Number of processors to request in Gaussian job.
        dat_M : str, optional
            Memory requirement.
        file_chk : str or bool, optional
            Checkpoint file to use.
        file_rwf : str or bool, optional
            Checkpoint file to use
        """
        if dat_M is not None:
            fobj.write(f'%Mem={dat_M}\n')
        if dat_P is not None:
            fobj.write(f'%NProcShared={dat_P}\n')
        if file_chk is not None and file_chk:
            fobj.write(f'%Chk={file_chk}\n')
        if file_rwf is not None and file_rwf:
            fobj.write(f'%Rwf={file_rwf}\n')

    def process_route(route: str
                      ) -> tp.Union[bool, bool, bool, bool, tp.List[str]]:
        """Parse Gaussian route specification section.

        Parses a route specification and checks relevant parameters.

        Parameters
        ----------
        route : str
            Route specification

        Returns
        -------
        tuple
            The following information are returned:
            - bool if Link717 will be used
            - bool if Link717 option section present in input
            - bool if Link718 will be used
            - bool if Link718 option section present in input
            - list of files to copy from/to the computing node
        """
        # fmt_frq = r'\bfreq\w*=?(?P<delim>\()?' \
        #     + r'[^)]*' \
        #     + '{}' \
        #     + r'[^)]*' \
        #     + r'(?(delim)\))\b'
        fmt_frq = r'\bfreq\w*=?(?P<delim>\()?' \
            + r'\S*' \
            + '{}' \
            + r'\S*' \
            + r'(?(delim)\))\b'
        # fmt_frq = r'\bfreq\w*=?(?P<delim>\()?' \
        #     + r'(?(delim)[^)]*|\S*)' \
        #     + '{}' \
        #     + r'(?(delim)[^)]*|\S*)' \
        #     + r'(?(delim)\))\b'
        fmt_frq = r'\bfreq\w*=?(?P<delim>\()?' \
            + r'(?(delim)[^)]|[^(),])*' \
            + '{}' \
            + r'(?(delim)[^)]|\S)*' \
            + r'(?(delim)\)|\b)'
        # ! fmt_geom = r'\bgeom\w*=?(?P<delim>\()?\S*{}\S*(?(delim)\))\b'
        # ! key_FC = re.compile(str_FC, re.I)
        key_718 = re.compile(fmt_frq.format(r'\b(fc|fcht|ht)\b'), re.I)
        key_718o = re.compile(fmt_frq.format(r'\breadfcht\b'), re.I)
        key_717 = re.compile(fmt_frq.format(r'\breadanh'), re.I)
        key_717o = re.compile(fmt_frq.format(r'\banharm(|onic)\b'), re.I)
        use717, use718, opt717, opt718 = False, False, False, False
        extra_cp = []
        # Check if we need to copy back
        if re.compile(r'\bgeomview\b').search(route):
            extra_cp.append(['cpfrom', 'points.off'])
        key_fchk = re.compile(r'\b(FChk|FCheck|FormCheck)\b')
        if key_fchk.search(route):
            extra_cp.append(['cpfrom', 'Test.FChk'])
        if key_718.search(route):
            use718 = True
        if key_718o.search(route):
            use718 = True
            opt718 = True
        if key_717.search(route):
            use717 = True
        if key_717o.search(route):
            use717 = True
            opt717 = True

        return use717, opt717, use718, opt718, extra_cp

    nprocs = dat_P
    mem = dat_M
    ops_copy = []
    ls_exts = ['.chk', '.dat', '.log', '.out', '.fch', '.rwf']
    ls_chks = []
    # ls_chks should be given as tuples (op, file) with:
    # op = 0: cpto/cpfrom
    #      1: cpto
    #      2: cpfrom
    # Reference for `op`: scratch dir
    # file: checkpoint file of interest
    if file_chk:
        ls_chks.append((0, file_chk))
    ls_rwfs = []
    if file_rwf:
        ls_rwfs.append(file_rwf)
    ls_files = []

    newlnk = True
    inroute = False
    use717 = [None]
    use718 = [None]
    opt717 = [None]
    opt718 = [None]
    route = ['']

    with open(gjf_ref, 'r', encoding='utf-8') as fobjr, \
            open(gjf_new, 'w', encoding='utf-8') as fobjw:
        write_hdr(fobjw, dat_P, dat_M, file_chk, file_rwf)
        for line in fobjr:
            line_lo = line.strip().lower()
            # END-OF-BLOCK
            if not line_lo:
                fobjw.write(line)
                if inroute:
                    use717[-1], opt717[-1], use718[-1], opt718[-1], dat =\
                        process_route(route[-1])
                    if dat:
                        ops_copy.extend(dat)
                    inroute = False
                continue
            # NEW BLOCK
            if line_lo == '--link1--':
                fobjw.write(line)
                newlnk = True
                route.append('')
                use717.append(None)
                use718.append(None)
                opt717.append(None)
                opt718.append(None)
                write_hdr(fobjw, dat_P, dat_M, file_chk, file_rwf)
            # INSTRUCTIONS
            else:
                if line_lo.startswith(r'%'):
                    if line_lo != '%nosave':
                        keyval = line.split('=')[1].strip()
                        # LINK0 INSTRUCTION
                        if line_lo.startswith(r'%chk'):
                            if file_chk is None:
                                ls_chks.append((0, keyval))
                            else:
                                line = ''
                        elif line_lo.startswith(r'%oldchk'):
                            ls_chks.append((1, keyval))
                        elif line_lo.startswith(r'%rwf'):
                            if file_rwf is not False:
                                ls_rwfs.append(keyval)
                            else:
                                line = ''
                        elif line_lo.startswith('%mem'):
                            if dat_M is None:
                                mem = keyval
                            else:
                                line = ''
                        elif line_lo.startswith('%nproc'):
                            if dat_P is None:
                                nprocs = int(keyval)
                            else:
                                line = ''
                elif (line_lo.startswith('#') and newlnk) or inroute:
                    # ROUTE SECTION
                    newlnk = False
                    inroute = True
                    route[-1] += ' ' + line.strip()
                else:
                    # REST OF INPUT
                    # The input files should not contain any spaces
                    # We assume that extensions are provided
                    if use717[-1] or use718[-1]:
                        if len(line_lo.split()) == 1 and line_lo.find('.') > 0:
                            ext = os.path.splitext(line.strip())[1]
                            if ext[:4] in ls_exts:
                                ls_files.append(line.strip())
                fobjw.write(line)

    # Copy files for CHK
    if ls_chks:
        # set is there to remove duplicate files
        for oper, chk in set(ls_chks):
            if oper in [0, 1] and os.path.exists(chk):
                ops_copy.append(['cpto', chk, rootdir])
            if oper in [0, 2]:
                ops_copy.append(['cpfrom', chk, rootdir])
    if ls_rwfs:
        # set is there to remove duplicate files
        for rwf in set(ls_rwfs):
            if os.path.exists(rwf):
                ops_copy.append(['cpto', rwf, rootdir])
            ops_copy.append(['cpfrom', rwf, rootdir])
    if ls_files:
        for fname in set(ls_files):
            if os.path.exists(fname):
                ops_copy.append(['cpto', fname, rootdir])

    if ops_copy:
        for cmd, what, _ in ops_copy:
            if cmd == 'cpto':
                dname, fname = os.path.split(what)
                if dname:
                    print(f'Will copy file: {fname} from {dname}')
                else:
                    print(f'Will copy file: {what}')

    return nprocs, mem, ops_copy


def main():
    """Submit Gaussian job on HPC nodes."""
    # Initialization
    # --------------
    gt.load_rc()

    # Nodes/Architecture specification
    # --------------------------------
    _path = os.path.join(gtpar.home, gtpar.files['hpcini'])
    if os.path.exists(_path):
        gtpar.paths['hpcini'] = _path
    else:
        gtpar.paths['hpcini'] = gtini.get_path('hpcconfig', miss_ok=False)
    if not os.path.exists(gtpar.paths['hpcini']):
        print('ERROR: Cannot find the HPC nodes specification file.')
        sys.exit(1)

    # HPC specifications
    # ------------------
    gthpc.init()

    # Gaussian specifications
    # -----------------------
    gtgxx.init()

    # Option building and parsing
    # ---------------------------
    parser = build_parser()

    options = parse_options(parser)
    multi_gjf = options['n_input'] > 1

    # Resources definition
    # --------------------
    # Define NProcs and Mem
    try:
        nprocs, mem = set_resources(options)
    except ValueError as err:
        print('ERROR: Insufficient resources to run job')
        print('Motive', err)
        sys.exit(1)

    # Check input and build list of relevant data
    # -------------------------------------------
    rootdirs = []
    gjf_files = []
    ops_copy = []
    full_P, full_M = 0, 0
    for index, infile in enumerate(options['ginfiles']):
        # outfile = glog_files[index]
        filebase = options['filebase'][index]
        if options['chkfiles']:
            chkfile = os.path.basename(options['chkfiles'][index])
        else:
            chkfile = options['chkfiles']
        if options['rwffiles']:
            rwffile = os.path.basename(options['rwffiles'][index])
        else:
            rwffile = options['rwffiles']
        rootdir, ginfile = os.path.split(infile)
        # A new, temporary input is created
        gjf_new = f'{filebase}_{JOB_PID}.gjf'
        # The script works in the directory where the input file is stored
        os.chdir(rootdir)
        if not options['expert']:
            dat_P, dat_M, data = check_gjf(ginfile, gjf_new, nprocs, mem,
                                           chkfile, rwffile, rootdir)
            if options['multijob'] == 'parallel':
                full_P += dat_P
                full_M += hpc.convert_storage(dat_M)
            else:
                if dat_P > full_P:
                    full_P = dat_P
                val = hpc.convert_storage(dat_M)
                if val > full_M:
                    full_M = hpc.convert_storage(dat_M)
        ops_copy.extend(data)
        rootdirs.append(rootdir)
        gjf_files.append(gjf_new)
    if not options['expert']:
        if full_P > options['qncpus']['base']:
            msg = f'''\
ERROR: Too many processors required for the available resources.
       {full_P} processing units requested for {options['qncpus']} available.\
'''
            print(msg)
            sys.exit(1)
        if full_M > options['qmem']['base']:
            print('ERROR: Requested memory exceeds available resources')
            sys.exit()
        nprocs = full_P
        mem = hpc.bytes_units(full_M, 0, False, 'g')
    if (options['qncpus']['soft'] is not None and
            nprocs > options['qncpus']['soft']):
        print('NOTE: Number of processors exceeds soft limit.')
    if (options['qmem']['soft'] is not None and
            hpc.convert_storage(mem) > options['qmem']['soft']):
        print('NOTE: Requested memory exceeds soft limit.')

    # Generate transfer commands
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^
    cpto = ''
    cpfrom = ''
    # fmt_to = '(cp {} ./) >& /dev/null\n'
    # fmt_from = '(cp {} {}) >& /dev/null\n'
    fmt_to = 'cp {} ./\n'
    fmt_from = 'cp {} {}\n'
    for cmd, what, where in ops_copy:
        if cmd == 'cpto':
            if where:
                cpto += fmt_to.format(os.path.join(where, what))
            else:
                cpto += fmt_to.format(what)
        elif cmd == 'cpfrom':
            if where:
                cpfrom += fmt_from.format(what, where)
            else:
                print('WARNING: Missing destination for file to retrieve')
                print(f'    {what} will be copied to {WORKDIR}')
                cpfrom += fmt_from.format(what, WORKDIR)
        else:
            print('ERROR: Unknown transfer operation.')
    if options['cpto']:
        for data in options['cpto']:
            cpto += fmt_to.format(os.path.join(WORKDIR, data))
    if options['cpfrom']:
        for data in options['cpfrom']:
            cpfrom += fmt_from.format(data, WORKDIR)
    # Build Submitter job
    # -------------------
    run_parallel = multi_gjf and options['multijob'] == 'parallel'
    wtime = options['qinfo'].get('walltime', '')
    if gtpar.server['submitter'] == 'qsub':
        job_extra_res, job_extra_cmd = \
              gtcmd.build_qsub_extra(options['qinfo'])
        if options['nojob']:
            cmdfobj = sys.stdout
        else:
            cmdfile = f'run_job_{JOB_PID}.sh'
            print(f'Building command file {cmdfile}.')
            cmdfobj = open(cmdfile, 'w', encoding='utf-8')
        gtcmd.build_qsub_cmd(cmdfobj, options['jobname'], nprocs, mem,
                             gjf_files, options['logfiles'],
                             options['gxx_cmds'], options['gxx_exedir'],
                             options['gxx'], WORKDIR, options['tmpdir'],
                             gtpar.server['runlocal'], run_parallel,
                             jobaddres=job_extra_res,
                             jobaddcmd=job_extra_cmd,
                             jobwtime=wtime, jobemail=options['mailto'],
                             cmdcpto=cpto, cmdcpfrom=cpfrom,
                             cmdrmtemp=gtpar.server['deltmpcmd'])
        if not options['nojob']:
            cmdfobj.close()
            qsub_cmd = ['qsub']
            if 'qname' in options['qinfo']:
                qsub_cmd.extend(['-q', options['qinfo']['qname']])
            qsub_cmd.append(cmdfile)
            # print(*qsub_cmd)
            cmd = subprocess.run(qsub_cmd, text=True, check=True,
                                 capture_output=True)
            print(f'QSub submission job: "{cmd.stdout.strip()}"')
