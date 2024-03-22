"""Build submitted commands."""

import os
import typing as tp


def build_qsub_extra(db_extra: tp.Dict[str, str]) -> tp.Union[str, str]:
    """Build extra commands for a qsub-like submitter.

    Translates the keywords stored in `db_extra` into commands for
    qsub.
    Commands are separated in two groups:

    1. extra options to be included as -l after "select".
    2. separate instructions involving different options.

    Parameters
    ----------
    db_extra
        Dictionary with extra options to pass to the submitter.

    Returns
    -------
    str
        options to add to the main command with select.
    str
        additional instructions for PBS.
    """
    extra_opts = ''
    extra_cmds = []

    if 'host' in db_extra:
        extra_opts += f':host={db_extra["host"]}'

    if 'qname' in db_extra:
        extra_opts += f':Qlist={db_extra["qname"]}'

    if 'diskmem' in db_extra:
        extra_opts += f':scratch_local={db_extra["diskmem"]}'

    if 'group' in db_extra:
        extra_cmds.append(f'#PBS -W group-list={db_extra["group"]}')

    return extra_opts, '\n'.join(extra_cmds)


def build_qsub_cmd(out: tp.TextIO,
                   jobtitle: str,
                   jobncpus: int,
                   jobmem: int,
                   ginfiles: tp.Sequence[str],
                   logfiles: tp.Sequence[str],
                   gxxenv: str,
                   gxxargs: str,
                   gxx: str,
                   wrkdir: str,
                   tmpdir: str,
                   runlocal: bool,
                   parallel: bool,
                   jobaddres: str = '',
                   jobaddcmd: str = '',
                   jobwtime: str = '',
                   jobemail: str = '',
                   cmdcpto: str = '',
                   cmdcpfrom: str = '',
                   cmdrmtemp: tp.Optional[str] = None
                   ):
    """Build QSub script.

    Builds a script to be run by a PBS-compatible job submitter.
    The script is stored in file/stream opened as `out`.

    Parameters
    ----------
    out:
        Output file object.
    jobtitle
        Name of the job for the queue system.
    jobncpus
        Number of processors to request
    jobmem
        Memory requirements, with units.
    ginfiles
        List of Gaussian input files.
    logfiles
        List of Gaussian output files.
    gxxenv
        Commands to load the Gaussian execution environment.
    gxxargs
        Extra arguments to pass to the Gaussian executable.
    gxx
        Name of the Gaussian executable.
    wrkdir
        Name of the working directory (starting point).
    tmpdir
        Name of the temporary directory on computing nodes.
    runlocal
        The job must be run purely on nodes, including the output.
    parallel
        Multiple Gaussian jobs must be run in parallel.
    jobaddres
        Extra resources commands for PBS job.
    jobaddcmd
        Extra commands for PBS job.
    jobwtime
        Walltime for PBS job.
    jobemail
        Email address to send job notifications.
    cmdcpto:
        Additional commands to copy file *to* temp. directory.
    cmdcpfrom:
        Additional commands to copy file *from* temp. directory.
    cmdrmtemp:
        Command to delete temporary directory (only if non-standard).
    """
    subcmd = f"""#!/bin/bash

#PBS -N {jobtitle}
#PBS -l select=1:ncpus={jobncpus}:mem={jobmem}{jobaddres}
"""
    if jobwtime.strip():
        subcmd += f'#PBS -l walltime={jobwtime}\n'
    if jobemail.strip():
        subcmd += f'#PBS -m abe -M {jobemail}\n'
    if jobaddcmd:
        subcmd += jobaddcmd + '\n'

    subcmd += f"""
# WORKDIR: work directory from head node
# TEMPDIR: temporary directory
WORKDIR={wrkdir}
TEMPDIR={tmpdir}
"""
    if tmpdir.startswith("$"):
        subcmd += f"""
# test if temporary directory is set, exit with error message if missing.
test -n "$TEMPDIR" || {{ echo >&2 "Variable {tmpdir[1:]} is not set!"; \
exit 1; }}
"""
    else:
        subcmd += f"""
mkdir -p {tmpdir}
# test if temporary directory is created.
test -d "$TEMPDIR" || \
{{ echo >&2 "Temporary director {tmpdir} could not be created"; exit 1; }}
"""

    subcmd += f'''
echo "----------------------------------------"
echo "PBS queue:     "$PBS_O_QUEUE
echo "PBS host:      "$PBS_O_HOST
echo "PBS node:      "$HOSTNAME
echo "PBS workdir:   {tmpdir}"
echo "PBS jobid:     "$PBS_JOBID
echo "PBS jobname:   "$PBS_JOBNAME
echo "PBS inputfile: {', '.join(ginfiles)}"
echo "----------------------------------------"

echo "$PBS_JOBID is running on node `hostname -f` in a scratch \
directory $TEMPDIR" >> $WORKDIR/jobs_info.txt
'''

    subcmd += f'\n{gxxenv}\n'

    subcmd += '\n{\n'
    for gjf in ginfiles:
        subcmd += f'mv {gjf} $TEMPDIR/\n'
    subcmd += '''\
} || { echo >&2 "Error while moving input file(s)!"; exit 2; }
'''

    subcmd += '''
# move into scratch directory
cd $TEMPDIR
'''

    if cmdcpto:
        subcmd += f'''
{{
{cmdcpto}
}} || {{ echo >&2 "Error while copying input file(s)!"; exit 2; }}
'''

    endline = ' &' if parallel else ''
    subcmd += '\n'
    for gjf, log in zip(ginfiles, logfiles):
        gjf_ = os.path.basename(gjf)
        log_ = os.path.basename(log)
        if runlocal:
            subcmd += f'({gxx} {gxxargs} {gjf_} {log_}; ' \
                + f'cp {log_} {log}){endline}\n'
        else:
            subcmd += f'{gxx} {gxxargs} {gjf_} {log}{endline}\n'
    if parallel:
        subcmd += 'wait\n'

    if cmdcpfrom:
        subcmd += f'''
{{
{cmdcpfrom}
}} || {{ echo >&2 "Error copying back files with code $?"; exit 4; }}
'''

    subcmd += '''
# Cleaning scratch directory.
'''
    if cmdrmtemp is not None:
        subcmd += cmdrmtemp
    else:
        subcmd += 'cd ${HOME}\nrm -rf ${TEMPDIR}'

    subcmd += '\n'

    print(subcmd, file=out)
