"""Build submitted commands."""

import os
import typing as tp


def build_qsub_head(out: tp.Optional[tp.TextIO] = None,
                    jobtitle: str = 'generic',
                    jobncpus: int = 1,
                    jobmem: str = '16GB',
                    jobwtime: str = '',
                    jobemail: str = '',
                    extraopts: tp.Optional[tp.Dict[str, str]] = None,
                    shell: str = 'bash'
                    ) -> tp.Optional[str]:
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
    jobwtime
        Walltime for PBS job.
    jobemail
        Email address to send job notifications.
    extraopts
        Dictionary with extra options to pass to the submitter.
    shell
        Write the commands for a specific kind of shell.

    Returns
    -------
    str
        list of submitter commands if `out` is None.
    """
    extra_res = ''
    if 'host' in extraopts:
        extra_res += f':host={extraopts["host"]}'
    if 'qbase' in extraopts:
        extra_res += f':Qlist={extraopts["qbase"]}'
    if 'diskmem' in extraopts:
        extra_res += f':scratch_local={extraopts["diskmem"]}'

    subcmd = f"""#!/bin/{shell}

#PBS -N {jobtitle}
#PBS -l select=1:ncpus={jobncpus}:mem={jobmem}{extra_res}
"""
    if jobwtime.strip():
        subcmd += f'#PBS -l walltime={jobwtime}\n'
    if jobemail.strip():
        subcmd += f'#PBS -m abe -M {jobemail}\n'
    if 'group' in extraopts:
        subcmd += f'#PBS -W group-list={extraopts["group"]}\n'
    if 'qname' in extraopts:
        subcmd += f'#PBS -q {extraopts["qname"]}'

    if shell.lower() in ('bash', 'sh', 'zsh'):
        subcmd += '''
# Store special variable for summary
JOB_QUEUE=$PBS_O_QUEUE
JOB_HOST=$PBS_O_HOST
JOB_ID=$PBS_JOBID
JOB_NAME=$PBS_JOBNAME
'''
    elif shell.lower() in ('csh', 'tcsh'):
        subcmd += '''
# Store special variable for summary
set JOB_QUEUE = "$PBS_O_QUEUE"
set JOB_HOST = "$PBS_O_HOST"
set JOB_ID = "$PBS_JOBID"
set JOB_NAME = "$PBS_JOBNAME"
'''
    else:
        raise NameError('Unknown type of shell')

    if out is None:
        return subcmd
    else:
        print(subcmd, file=out)


def build_sbatch_head(out: tp.Optional[tp.TextIO] = None,
                      jobtitle: str = 'generic',
                      jobncpus: int = 1,
                      jobmem: str = '16GB',
                      jobwtime: str = '',
                      jobemail: str = '',
                      extraopts: tp.Optional[tp.Dict[str, str]] = None
                      ) -> tp.Optional[str]:
    """Build script for SLURM.

    Builds a script to be run by a SLURM-compatible job submitter.
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
    jobwtime
        Walltime for PBS job.
    jobemail
        Email address to send job notifications.
    extraopts
        Dictionary with extra options to pass to the submitter.

    Returns
    -------
    str
        list of submitter commands if `out` is None.

    Notes
    -----
    Some recommend for SMP jobs: --nodes=1, --ntasks=1, --cpus-per-tasks=N
    It may have to be tested.
    """
    subcmd = f"""#!/bin/bash

#SBATCH --job-name {jobtitle}
#SBATCH --nodes=1
#SBATCH --ntasks-per-node={jobncpus}
#SBATCH --mem={jobmem}
"""
    if 'qname' in extraopts:
        subcmd += f'#SBATCH --partition={extraopts["qname"]}\n'
    if jobwtime.strip():
        subcmd += f'#SBATCH --time={jobwtime}\n'
    if 'host' in extraopts:
        subcmd += f'#SBATCH --nodelist={extraopts["host"]}\n'
    subcmd += '#SBATCH --exclusive\n'
    if jobemail.strip():
        subcmd += f"""\
#SBATCH --mail-type=all
#SBATCH --mail-user={jobemail}
"""

    subcmd += '''
# Store special variable for summary
JOB_QUEUE=$SLURM_JOB_PARTITION
JOB_HOST=$SLURM_SUBMIT_HOST
JOB_ID=$SLURM_JOBID
JOB_NAME=$SLURM_JOB_NAME
'''

    if out is None:
        return out
    else:
        print(subcmd, file=out)


def build_bash_cmd(out: tp.TextIO,
                   ginfiles: tp.Sequence[str],
                   logfiles: tp.Sequence[str],
                   gxxenv: str,
                   gxxargs: str,
                   gxx: str,
                   wrkdir: str,
                   tmpdir: str,
                   runlocal: bool,
                   parallel: bool,
                   cmdcpto: str = '',
                   cmdcpfrom: str = '',
                   cmdrmtemp: tp.Optional[str] = None
                   ):
    """Build pure BASH/shell cmds for the submiiter.

    Builds a script to be run by BASH-compatible shell.
    The script is stored in file/stream opened as `out`.

    Parameters
    ----------
    out:
        Output file object.
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
    cmdcpto:
        Additional commands to copy file *to* temp. directory.
    cmdcpfrom:
        Additional commands to copy file *from* temp. directory.
    cmdrmtemp:
        Command to delete temporary directory (only if non-standard).
    """
    runcmd = f"""
# WORKDIR: work directory from head node
# TEMPDIR: temporary directory
WORKDIR={wrkdir}
TEMPDIR={tmpdir}
"""
    if tmpdir.startswith("$"):
        runcmd += f"""
# test if temporary directory is set, exit with error message if missing.
test -n "$TEMPDIR" || {{ echo >&2 "Variable {tmpdir[1:]} is not set!"; \
exit 1; }}
"""
    else:
        runcmd += f"""
mkdir -p $TEMPDIR
# test if temporary directory is created.
test -d "$TEMPDIR" || \
{{ echo >&2 "Temporary director {tmpdir} could not be created"; exit 1; }}
"""

    runcmd += f'''
echo "----------------------------------------"
echo "JOB queue:     "$JOB_QUEUE
echo "JOB host:      "$JOB_HOST
echo "JOB node:      "$HOSTNAME
echo "JOB workdir:   {tmpdir}"
echo "JOB jobid:     "$JOB_ID
echo "JOB jobname:   "$JOB_NAME
echo "JOB inputfile: {', '.join(ginfiles)}"
echo "----------------------------------------"

echo "$JOB_ID is running on node `hostname -f` in a scratch \
directory $TEMPDIR" >> $WORKDIR/jobs_info.txt
'''

    runcmd += f'\n{gxxenv}\n'

    runcmd += '\n{\n'
    for gjf in ginfiles:
        runcmd += f'mv {gjf} $TEMPDIR/\n'
    runcmd += '''\
} || { echo >&2 "Error while moving input file(s)!"; exit 2; }
'''

    runcmd += '''
# move into scratch directory
cd $TEMPDIR
'''

    if cmdcpto:
        runcmd += f'''
{{
{cmdcpto}
}} || {{ echo >&2 "Error while copying input file(s)!"; exit 2; }}
'''

    endline = ' &' if parallel else ''
    runcmd += '\n'
    for gjf, log in zip(ginfiles, logfiles):
        gjf_ = os.path.basename(gjf)
        log_ = os.path.basename(log)
        if runlocal:
            runcmd += f'({gxx} {gxxargs} {gjf_} {log_}; ' \
                + f'cp {log_} {log}){endline}\n'
        else:
            runcmd += f'{gxx} {gxxargs} {gjf_} {log}{endline}\n'
    if parallel:
        runcmd += 'wait\n'

    if cmdcpfrom:
        runcmd += f'''
{{
{cmdcpfrom}
}} || {{ echo >&2 "Error copying back files with code $?"; exit 4; }}
'''

    runcmd += '''
# Cleaning scratch directory.
'''
    if cmdrmtemp is not None:
        runcmd += cmdrmtemp
    else:
        runcmd += 'cd ${HOME}\nrm -rf ${TEMPDIR}'

    runcmd += '\n'

    print(runcmd, file=out)
