"""Gaussian submitter: QSub-type submitter on heterogeneous nodes.

This module is part of the the library system and provides the
necessary interface to submit jobs through a qsub-like system on
clusters of heterogenous nodes managed semi-independently.
"""

import os
import re
import sys
import argparse
import typing as tp

import hpcnodes as hpc

import gxxtools as gt
import gxxtools.parse_ini as gtini
import gxxtools.params as gtpar


# ====================================
#   INSTALLATION-SPECIFIC PARAMETERS
# ====================================

# From early tests, best to use only physical cores
# Anyway, this can be changed depending on preferences
_USE_LOGICAL_CORE = False
# Maximum occupation of the total memory on a given node
# By default, Gaussian does a very good job in managing the memory, but there
#   is some memory set statically, so besides %Mem
# We limit the user or default requirements to 90% of the available memory.
_MEM_LIMIT = .9

# Basic Paths
# -----------
# TMPDIR is only used if users asked to copy back some specific files
#   but do not provide any specific paths back.  To avoid overridding any
#   file, Gxx-QSub creates a directory in HOME based on the PID.
# {pid} refers to the job PID, dirs can be added too.
TMPDIR = 'scratch-{pid}'


# Global Interface
# ================
# Provide general connectors
def nodes_list():
    """List available nodes."""
    return sorted(gtpar.queues_info.keys())


def queues_default():
    """Return the default queue."""
    return gtini.get_info('queue')


def parse_queries(opts: argparse.Namespace) -> bool:
    """Check query options from parsing result.

    Checks if architecture-specific query options have been provided.
    Returns True if a query was requested.
    """
    if opts.mach:
        print("""\
List of available HPC Nodes
---------------------------
""")
        for family in sorted(gtpar.nodes_info):
            print(gtpar.nodes_info[family])
        return True
    return False


def parser_add_opts(parser: argparse._ArgumentGroup):
    """Add architecture-specific parser options."""
    parser.add_argument(
        '-M', '--mach', dest='mach', action='store_true',
        help='Prints technical info on the machines available in the cluster')
    parser.add_argument(
        '--node', dest='node', type=int,
        help='Name of a specific node (ex: node01)')
    parser.add_argument(
        '-t', '--tmpdir', dest='tmpdir', metavar='TEMP_DIR',
        help='''\
Sets the temporary directory where calculations will be run.
This is set automatically based on the node configuration.
"{username}" can be used as a placeholder for the username.''')
    if gtpar.server['nodestype'] == 'central':
        parser.add_argument(
            '--tmpspace', metavar='TEMP_SPACE', default='10GB',
            help='Temporary storage space.')
    wtime = gtini.sub_info('walltime')
    if wtime:
        needed = wtime is True
        if isinstance(wtime, str):
            defval = wtime
        else:
            defval = None
        parser.add_argument(
            '--walltime', default=defval, required=needed,
            help='Sets the walltime for the job (as hh:mm:ss).')


def parser_doc_queues() -> tp.Optional[str]:
    """Return the documentation for available HPC queuing options."""
    if gtpar.server['nodestype'] == 'queues':
        return f"""Sets the queues.
Available queues:
{', '.join(nodes_list())}

Virtual queues defined as:
<queue>[:[nprocs][:nodeid]]
with:
    <queue>: one of the queues above
    nprocs: choice for number of processing units
        - "H" : uses half of the cores of a single CPU
        - "S" : uses a single core
        - "0" : auto (same as empty)
        - positive integer: total number of cores to use.
        - negative integer: number of CPUs to use
"""
    else:
        return None


def get_arch_spec(opts: argparse.Namespace,
                  jobid: tp.Optional[tp.Any] = None
                  ) -> tp.Tuple[tp.Dict[str, int], tp.Dict[str, float],
                                tp.Dict[str, str], str]:
    """Get HPC architecture specifications.

    Retrieves architecture specifications based on options:

    - the number of processing units to use.
    - the maximum memory possible on node.
    - extra information for the submitter system (program independent).
    - temporary storage specification (variable or specification)

    This function acts only as wrapper to server architectures-specific
    routines and adds generic parsing.

    Parameters
    ----------
    opts
        Result of the argument line parsing, with at least these attrs.
    jobid
        Job ID to be used to generate a path to store temporary files.

    Return
    ------
    dict
        the number of processing units to use, with soft/hard limit.
    dict
        the maximum memory possible on node, with soft/hard limit
    dict
        extra information for the submitter system.
    str
        Path or variable for the general storage.

    """
    if gtpar.server['nodestype'] == 'queues':
        maxcpu, maxmem, job_extra = _get_spec_by_queue(opts)
    else:
        maxcpu, maxmem, job_extra = _get_spec_generic(opts)

    if gtini.get_info('walltime_needed'):
        if opts.walltime is None:
            wtime_dat = gtini.sub_info('walltime')
            if isinstance(wtime_dat, dict):
                if 'qname' not in job_extra:
                    print('ERROR: missing queue name to set walltime.')
                    sys.exit(10)
                qbase = job_extra.get('qbase', '')
                # The following test is weak since it assumes that the
                # queue_type cannot appear as is in another part of the format.
                # In practice, this means that if we have queue types short and
                # long, then the system would be confused with a format like:
                # {node_queue_name}long_{queue_type}.
                qname = job_extra['qname'].replace(qbase, '')
                wtime = None
                for key, val in wtime_dat.items():
                    if key and key in qname:
                        wtime = val
                        break
                if '' in wtime_dat and wtime is None:
                    wtime = wtime_dat['']
            else:
                print('ERROR: missing walltime')
                sys.exit(10)
        else:
            wtime = opts.walltime
        if not re.fullmatch(r'\d+:\d{2}:\d{2}', wtime):
            print('ERROR: wrong format for the walltime')
            sys.exit(10)
        job_extra['walltime'] = wtime
    if gtpar.server['nodestype'] == 'central':
        try:
            hpc.convert_storage(opts.tmpspace)
        except ValueError:
            print('ERROR: Incorrect format for the storage space')
            sys.exit(10)
        job_extra['diskmem'] = opts.tmpspace
    # analyse storage
    if opts.tmpdir is not None:
        tmp_path = opts.tmpdir.format(username=gtpar.user)
    elif gtpar.node_family.path_tmpdir:
        tmp_path = gtpar.node_family.path_tmpdir.format(username=gtpar.user)
    else:
        print('''\
WARNING: No local storage specification.  Cowardly quitting.''')
        sys.exit(10)
    if not tmp_path.startswith('$'):
        tmp_path += os.path.sep + f'gaurun-{jobid}'

    return maxcpu, maxmem, job_extra, tmp_path


def _get_spec_by_queue(opts: argparse.Namespace
                       ) -> tp.Tuple[tp.Dict[str, int], tp.Dict[str, float],
                                     tp.Dict[str, str]]:
    """Get queue and node specifications.

    Retrieves queue and architecture specifications based on full queue
    name and returns:
    - the number of processing units to use.
    - the maximum memory possible on node.
    - extra information for the submitter system (program independent).
    The function also checks the consistency of overlapping options
    related to queues and nodes

    Parameters
    ----------
    opts
        Result of the argument line parsing, with at least these attrs.
        queue: full queue spec. as "queue[:[nproc_spec]:[node_id]]"
        node: node specification.
        group: user group to consider for access rights.

    Returns
    -------
    dict
        the number of processing units to use, with soft/hard limit.
    dict
        the maximum memory possible on node, with soft/hard limit
    dict
        extra information for the submitter system.

    Raises
    ------
    ValueError
        Incorrect definition of the virtual queue
    KeyError
        Unsupported queue
    """
    job_extra = {}
    # Queue specification parsing
    # ---------------------------
    data = opts.queue.split(':')
    if len(data) == 1:
        queue = data[0]
        nprocs = None
        nodeid = None
    elif len(data) == 2:
        queue = data[0]
        nprocs = data[1].strip() or None
        nodeid = None
    elif len(data) == 3:
        queue = data[0]
        nprocs = data[1].strip() or None
        nodeid = data[2].strip() or None
    else:
        raise ValueError('Too many sections in full queue specification.')
    job_extra['qname'] = queue

    try:
        gtpar.node_family = gtpar.nodes_info[gtpar.queues_info[queue]]
    except KeyError as err:
        raise KeyError('Unsupported queue.') from err
    job_extra['qbase'] = gtpar.node_family.queue_name

    # Definition of number of processors
    # ----------------------------------
    nprocs_avail = gtpar.node_family.nprocs(count_all=_USE_LOGICAL_CORE)
    # core_factor: integer multiplier to account for virtual if requested/avail
    core_factor = nprocs_avail/gtpar.node_family.nprocs(count_all=False)
    maxcpu = {
        'soft': gtpar.node_family.cpu_limits['soft'],
        'hard': gtpar.node_family.cpu_limits['hard'] or nprocs_avail
    }
    if nprocs is None:
        if maxcpu['soft'] is not None:
            res = maxcpu['soft']
        elif maxcpu['hard'] is not None:
            res = maxcpu['hard']
        else:
            raise ValueError('No limit on number of processors.')
    else:
        if nprocs == 'H':  # Half of cores on 1 processor
            res = int(gtpar.node_family.ncores*core_factor/2)
        elif nprocs == 'S':  # Only 1 physical core
            res = 1*core_factor
        elif nprocs == '0':  # Seen as blank/auto == full machine
            res = nprocs_avail
        else:
            try:
                value = int(nprocs)
                if value < 0:
                    res = abs(value)*gtpar.node_family.ncores*core_factor
                elif value > 0:
                    res = value
            except ValueError as err:
                raise ValueError('Unsupported definition of processors.') \
                    from err
    nprocs = int(res)
    if nprocs > nprocs_avail:
        raise ValueError('Too many processing units requested.')
    elif (gtpar.node_family.cpu_limits['hard'] is not None and
          nprocs > gtpar.node_family.cpu_limits['hard']):
        raise ValueError('Number of processing units exceeds hard limit.')
    maxcpu['base'] = nprocs

    # Check memory specifications
    # ---------------------------
    maxmem = {
        'soft': gtpar.node_family.mem_limits['soft'],
        'hard': gtpar.node_family.mem_limits['hard'] or
        gtpar.node_family.size_mem
    }
    if maxmem['soft'] is not None:
        maxmem['soft'] *= _MEM_LIMIT
    if maxmem['hard'] is not None:
        maxmem['hard'] *= _MEM_LIMIT
    if maxmem['soft'] is not None:
        mem = maxmem['soft']
    elif maxmem['hard'] is not None:
        mem = maxmem['hard']
    else:
        raise ValueError('No memory limit.')
    maxmem['base'] = mem

    # Node id
    # -------
    if nodeid is not None:
        try:
            value = int(nodeid)
            if value > len(gtpar.node_family):
                raise ValueError('Node id higher than number of nodes.')
        except ValueError as err:
            raise KeyError('Wrong definition of the node ID') from err
        nodeid = value

    # Check if user gave node id through --node option and virtual queue
    if opts.node is not None:
        if (nodeid is not None and nodeid != opts.node):
            msg = 'ERROR: Different nodes selected through virtual queue ' \
                + 'and option'
            print(msg)
            sys.exit(2)
        else:
            nodeid = opts.node
    if nodeid is not None:
        fmt = f'{{qname}}{{id:0{len(str(len(gtpar.node_family)))}d}}'
        job_extra['host'] = fmt.format(qname=gtpar.node_family.queue_name,
                                       id=nodeid)

    # Check if group specification
    # ----------------------------
    # Check if only some groups authorized to run on node family
    if gtpar.node_family.user_groups is not None:
        if opts.group is not None:
            if opts.group in gtpar.node_family.user_groups:
                group = opts.group
            else:
                print('ERROR: Chosen group not authorized to use this node.')
                sys.exit(10)
        else:
            fmt = 'NOTE: Those nodes are only accessible to members of: {}'
            print(fmt.format(','.join(gtpar.node_family.user_groups)))
            group = gtpar.node_family.user_groups[0]
            if len(gtpar.node_family.user_groups) > 1:
                print(f'Multiple groups authorized. "{group}" chosen.')
        job_extra['group'] = opts.group

    return maxcpu, maxmem, job_extra


def _get_spec_generic(opts: argparse.Namespace
                      ) -> tp.Tuple[tp.Dict[str, int], tp.Dict[str, float],
                                    tp.Dict[str, str]]:
    """Get general hardware specifications.

    Retrieves general hardware specifications for a merged queueing system
    (single entry).
    It returns:

    - the number of processing units to use.
    - the maximum memory possible on node.
    - extra information for the submitter system (program independent).

    The function also checks the consistency of overlapping options
    related to queues and nodes

    Parameters
    ----------
    opts : str
        Result of the argument line parsing, with at least these attrs.
        group: user group to consider for access rights.

    Returns
    -------
    dict
        the number of processing units to use, with soft/hard limit.
    dict
        the maximum memory possible on node, with soft/hard limit
    dict
        extra information for the submitter system.

    Raises
    ------
    ValueError
        Incorrect definition of the virtual queue
    KeyError
        Unsupported queue
    """
    job_extra = {}

    nodes = {key.lower(): key for key in gtpar.nodes_info}
    if 'basic' in nodes:
        key = nodes['basic']
    elif 'base' in nodes:
        key = nodes['base']
    elif 'generic' in nodes:
        key = nodes['generic']
    elif 'general' in nodes:
        key = nodes['general']
    else:
        raise KeyError('Cannot find the generic specifications.')
    gtpar.node_family = gtpar.nodes_info[key]

    # Definition of number of processors
    # ----------------------------------
    nprocs_avail = gtpar.node_family.nprocs(count_all=_USE_LOGICAL_CORE)
    # core_factor: integer multiplier to account for virtual if requested/avail
    maxcpu = {
        'soft': gtpar.node_family.cpu_limits['soft'],
        'hard': gtpar.node_family.cpu_limits['hard'] or nprocs_avail
    }
    if maxcpu['soft'] is not None:
        res = maxcpu['soft']
    elif maxcpu['hard'] is not None:
        res = maxcpu['hard']
    else:
        raise ValueError('No limit on number of processors.')
    nprocs = int(res)
    if nprocs > nprocs_avail:
        raise ValueError('Too many processing units requested.')
    elif (gtpar.node_family.cpu_limits['hard'] is not None and
          nprocs > gtpar.node_family.cpu_limits['hard']):
        raise ValueError('Number of processing units exceeds hard limit.')
    maxcpu['base'] = nprocs

    # Check memory specifications
    # ---------------------------
    maxmem = {
        'soft': gtpar.node_family.mem_limits['soft'],
        'hard': gtpar.node_family.mem_limits['hard'] or
        gtpar.node_family.size_mem
    }
    if maxmem['soft'] is not None:
        maxmem['soft'] *= _MEM_LIMIT
    if maxmem['hard'] is not None:
        maxmem['hard'] *= _MEM_LIMIT
    if maxmem['soft'] is not None:
        mem = maxmem['soft']
    elif maxmem['hard'] is not None:
        mem = maxmem['hard']
    else:
        raise ValueError('No memory limit.')
    maxmem['base'] = mem

    # Check if group specification
    # ----------------------------
    # Check if only some groups authorized to run on node family
    if gtpar.node_family.user_groups is not None:
        if opts.group is not None:
            if opts.group in gtpar.node_family.user_groups:
                group = opts.group
            else:
                print('ERROR: Chosen group not authorized to use this node.')
                sys.exit(10)
        else:
            fmt = 'NOTE: Those nodes are only accessible to members of: {}'
            print(fmt.format(','.join(gtpar.node_family.user_groups)))
            group = gtpar.node_family.user_groups[0]
            if len(gtpar.node_family.user_groups) > 1:
                print(f'Multiple groups authorized. "{group}" chosen.')
        job_extra['group'] = opts.group

    return maxcpu, maxmem, job_extra


def init():
    """Initialize system."""
    # Check if gxxtools initialized
    if gtpar.stage < 2:
        gt.load_rc()

    # Load HPC nodes/queue structure
    gtpar.nodes_info = hpc.parse_ini(gtpar.paths['hpcini'])
    gtpar.queues_info = hpc.list_queues_nodes(gtpar.nodes_info)
    gtpar.stage = 3

# vim: ft=python foldmethod=indent
