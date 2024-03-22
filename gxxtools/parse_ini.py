#!/usr/bin/env python3
"""Simple parser of gxxconfig.ini file."""

import sys
import os
import typing as tp
import argparse
from configparser import ConfigParser, ExtendedInterpolation

from gxxtools.params import paths

_SEC_GXX = 'GAUSSIAN'
_SEC_CFG = 'CONFIG'
_SEC_ROOT = 'PATHS'
_SEC_COMP = 'COMPILER'
_SEC_QUEUE = 'QUEUE'
_SEC_SRV = 'SERVER'


def get_config(cfg_file: tp.Optional[str] = None) -> tp.Optional[ConfigParser]:
    """Return a ConfigParser instance.

    Returns an instance of ConfigParser() if a config file is found and
    load it, None otherwise.

    Parameters
    ----------
    fg_file
        Configuration file.
        If None, CONFIG_FILE is used.

    Returns
    -------
    obj:`ConfigParser`
        ConfigParser instance.
    """
    rfile = cfg_file if cfg_file is not None else paths['gxxcfg']
    if rfile is None:
        return None
        # raise FileNotFoundError('Missing configuration file')
    if not os.path.exists(rfile):
        return None
        # raise FileNotFoundError(f'File "{rfile}" not found.')
    config = ConfigParser(interpolation=ExtendedInterpolation())
    config.read(rfile)
    return config


def get_path(what: str,
             cfg_file: tp.Optional[str] = None,
             full_path: bool = True,
             miss_ok: bool = True) -> str:
    """Get/build file path.

    Constructs the path with information from `cfg_file` or global
    configuration file for the quantity represented by `what`.

    Parameters
    ----------
    what
        Quantity of interest.
    cfg_file
        Configuration file.
        If None, CONFIG_FILE is used.
    full_path
        If True, the full file path is returned, otherwise only name.
    miss_ok
        If False, an error is raised if the item is missing.

    Returns
    -------
    str
        Path to file or file.

    Raises
    ------
    FileNotFoundError
        Missing configuration file.
    KeyError
        Value of `what` is unknown.
    ValueError
        Missing information in config file.
    """
    def build_path(path: tp.Optional[str] = None,
                   file: tp.Optional[str] = None) -> tp.Optional[str]:
        """Build path from config file and path information."""
        if file is not None:
            if _SEC_CFG not in config.sections():
                if not miss_ok:
                    return None
                raise ValueError(f'Missing [{_SEC_CFG}] section')
            fname = config.get(_SEC_CFG, file, fallback=None)
            if fname is None:
                if not miss_ok:
                    raise ValueError(f'Missing option "{file}"')
            # check if file corresponds to an actual path
            # we will check that there is at least one path separator and
            # the path exists.
            if not full_path or (miss_ok and fname is None):
                res = fname
            elif os.sep in fname and os.path.exists(fname):
                res = os.path.abspath(fname)
            else:
                root = config.get(_SEC_ROOT, path, fallback=None)
                if root is not None:
                    res = os.path.join(root, fname)
                else:
                    res = fname
            return res
        else:
            if _SEC_ROOT not in config.sections():
                if miss_ok:
                    return None
                raise ValueError(f'Missing [{_SEC_ROOT}] section')
            root = config.get(_SEC_ROOT, path, fallback=None)
            if root is None:
                if not miss_ok:
                    raise ValueError(f'Missing option "{path}"')
            return root if root is None else os.path.abspath(root)

    config = get_config(cfg_file)
    if config is None:
        raise FileNotFoundError('Configuration file is missing.')

    info = {'path': None, 'file': None}

    if what.lower() in ('hpcnodes', 'hpcconfig', 'hpcfile'):
        if full_path:
            info['path'] = 'iniroot'
        info['file'] = 'hpcfile'
    elif what.lower() in ('gxxversions', 'gxxconfig', 'gxxfile'):
        if full_path:
            info['path'] = 'iniroot'
        info['file'] = 'gxxfile'
    elif what.lower() in ('hpcmod', 'hpcmodule'):
        info['path'] = 'hpcnodes'
    elif what.lower() == 'gxxroot':
        info['path'] = 'gxxroot'
    elif what.lower() == 'gxxrepo':
        info['path'] = 'gxxrepo'
    elif what.lower() in ('working', 'workroot'):
        info['path'] = 'workingroot'
    elif what.lower() == 'comproot':
        info['path'] = 'compiler_root'
    elif what.lower() == 'compdir':
        info['path'] = 'compiler_path'
    else:
        raise KeyError('Unsupported quantity')

    return build_path(**info)


def gxx_build_archs(cfg_file: tp.Optional[str] = None,
                    miss_ok: bool = True) -> tp.Dict[str, str]:
    """Return the build architectures for Gaussian.

    Constructs a dictionary of the build dictionary as,
    gaussian_build_arch: (directory, build_node)

    Parameters
    ----------
    cfg_file
        Configuration file.
        If None, CONFIG_FILE is used.
    miss_ok
        If the information on an architecture is missing, the
        architecture is simply ignored.

    Returns
    -------
    dict
        Dictionary of architectures with the form:
        gaussian_arch: (install_dir, compilation_node)

    Raises
    ------
    FileNotFoundError
        Missing configuration file.
    ValueError
        Missing information in configuration file
    """
    config = get_config(cfg_file)
    if config is None:
        raise FileNotFoundError('Configuration file is missing.')

    archs = config.get(_SEC_GXX, 'build_archs', fallback=None)
    if archs is None:
        raise ValueError('Missing build architecture in config file.')
    arch_data = {}
    archs = (item.strip() for item in archs.split(','))
    for arch in archs:
        # By default, we silently
        info = config.get(_SEC_GXX, f"build_{arch}", fallback=None)
        if info is None:
            if not miss_ok:
                raise ValueError(f'Missing information for arch {arch}')
        else:
            if '|' not in info:
                msg = f'''Incorrect format for build information on arch {arch}
Expected format: installation_structure | build_node
ex: intel64-haswell | verne'''
                raise ValueError(msg)
            arch_data[arch] = tuple(item.strip() for item in info.split('|'))
    return arch_data if arch_data else None


def gxx_info(what: str, cfg_file: tp.Optional[str] = None
             ) -> tp.Optional[tp.Union[str, bool]]:
    """Return Gaussian-related data.

    Returns the Gaussian-related data corresponding to `what` from the
    configuration file.

    Parameters
    ----------
    what
        Information of interest.
    cfg_file
        Configuration file.
        If None, CONFIG_FILE is used.

    Returns
    -------
    str
        Path to file.

    Raises
    ------
    FileNotFoundError
        Missing configuration file.
    KeyError
        Value of `what` is unknown.
    ValueError
        Missing information in config file.
    """
    config = get_config(cfg_file)
    if config is None:
        raise FileNotFoundError('Configuration file is missing.')

    query = what.lower()
    if query == 'default':
        res = config.get(_SEC_GXX, 'default', fallback=None)
        if res is None:
            raise ValueError('Missing default Gaussian version')
    elif query in ('use_mod', 'use_module', 'module'):
        res = config.getboolean(_SEC_GXX, 'module', fallback=False)
    elif query in ('use_path', 'path'):
        res = config.getboolean(_SEC_GXX, 'path', fallback=True)
    else:
        raise KeyError('Unrecognized Gaussian information')

    return res


def sub_info(what: str, cfg_file: tp.Optional[str] = None
             ) -> tp.Optional[tp.Union[str, bool]]:
    """Return queue/submission-related data.

    Returns the queue-related information corresponding to `what` from
    the configuration file.

    Parameters
    ----------
    what
        Information of interest.
    cfg_file
        Configuration file.
        If None, CONFIG_FILE is used.

    Returns
    -------
    str
        Path to file.

    Raises
    ------
    FileNotFoundError
        Missing configuration file.
    KeyError
        Value of `what` is unknown.
    ValueError
        Missing information in config file.
    """
    config = get_config(cfg_file)
    if config is None:
        raise FileNotFoundError('Configuration file is missing.')

    query = what.lower()
    if query in ('default', 'queue'):
        res = config.get(_SEC_QUEUE, 'default', fallback=None)
        if res is None:
            raise ValueError('Missing default Gaussian version')
    elif query in ('manual', 'nodes'):
        res = config.getboolean(_SEC_QUEUE, 'manual', fallback=True)
    elif query in ('walltime', 'wtime'):
        res = config.get(_SEC_QUEUE, 'walltime', fallback=None)
    else:
        raise KeyError('Unrecognized queue information')

    return res


def srv_info(what: str, cfg_file: tp.Optional[str] = None
             ) -> tp.Optional[tp.Union[str, bool]]:
    """Return server-related data.

    Returns the server-related data corresponding to `what` from the
    configuration file.

    Parameters
    ----------
    what
        Information of interest.
    cfg_file
        Configuration file.
        If None, CONFIG_FILE is used.

    Returns
    -------
    str
        Path to file.

    Raises
    ------
    FileNotFoundError
        Missing configuration file.
    KeyError
        Value of `what` is unknown.
    ValueError
        Missing information in config file.
    """
    config = get_config(cfg_file)
    if config is None:
        raise FileNotFoundError('Configuration file is missing.')

    query = what.lower()
    if query == 'alias':
        res = config.get(_SEC_SRV, 'alias', fallback=None).lower()
        if res is None:
            raise ValueError('Missing server alias')
    elif query == 'email':
        res = config.get(_SEC_SRV, 'email', fallback=None)
    elif query in ('submitter', 'sub', 'job', 'qsub'):
        res = config.get(_SEC_SRV, 'submitter', fallback='qsub').lower()
        if res not in ('qsub', ):
            raise ValueError('Unsupported type of job submitter.')
        if query == 'qsub':
            res = res == 'qsub'
    elif query in ('jobtype', 'srvtype', 'servertype', 'queues', 'noqueues',
                   'dispatch', 'central'):
        res = config.get(_SEC_SRV, 'jobtype', fallback='queues').lower()
        if res not in ('central', 'queues'):
            raise ValueError('Unsupported type of job submission.')
        if query == 'queues':
            res = res == 'queues'
        elif query in ('noqueues', 'dispatch', 'central'):
            res = res == 'central'
    elif query in ('local', 'runlocal'):
        res = config.getboolean(_SEC_SRV, 'runlocal', fallback=False)
    elif query in ('clean', 'cleancmd', 'cleanscratch', 'rmscratch'):
        res = config.get(_SEC_SRV, 'cleanscratch', fallback=None)
        if res is not None:
            if res.lower() == 'auto':
                res = None
    else:
        raise KeyError('Unrecognized server information')

    return res


def get_info(what: str, cfg_file: tp.Optional[str] = None
             ) -> tp.Union[str, bool]:
    """Return information for `what`.

    Returns the information corresponding to `what` from the
    configuration file.

    Parameters
    ----------
    what
        Information of interest.
    cfg_file
        Configuration file.
        If None, CONFIG_FILE is used.

    Returns
    -------
    str, bool
        Stored information.

    Raises
    ------
    FileNotFoundError
        Missing configuration file.
    KeyError
        Value of `what` is unknown.
    ValueError
        Missing information in config file.
    """
    config = get_config(cfg_file)
    if config is None:
        raise FileNotFoundError('Configuration file is missing.')

    if what.lower() in ('compiler', 'compname'):
        res = config.get(_SEC_COMP, 'name', fallback=None)
        if res is None:
            raise ValueError('Missing name of the compiler')
    elif what.lower() == 'set_compiler':
        res = config.getboolean(_SEC_COMP, 'set_env', fallback=False)
    elif what.lower() in ('queue', 'default_queue'):
        res = config.get(_SEC_QUEUE, 'default', fallback=None)
    elif what.lower() in ('queues_avail'):
        res = config.getboolean(_SEC_QUEUE, 'manual', fallback=True)
    elif what.lower() in ('walltime_needed'):
        res = config.getboolean(_SEC_QUEUE, 'walltime', fallback=False)
    else:
        raise KeyError('Unrecognized information')

    return res


def main():
    """Add commandline support."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter)

    qties = {
        'default': 'Default Gaussian version',
        'build_archs': 'Gaussian build architectures',
        'hpcmodule': 'Path to hpcmodule file',
        'hpcfile': 'Path to configuration file for hpcnodes module',
        'gxxfile': 'Path to configuration file with versions',
        'gxxroot': 'Root directory where Gaussian versions are installed',
        'workroot': 'Root directory where "workings" are installed',
        'working': 'Alias for "workroot"',
    }

    msg = 'Quantity to parser from file. Supported:\n'
    for key, txt in qties.items():
        msg += f'- {key:<12s}: {txt}\n'

    parser.add_argument('quantity', choices=tuple(qties),
                        help=msg)
    parser.add_argument('-c', '--configfile', default=paths['gxxcfg'],
                        help='Configuration file with relevant information')

    opts = parser.parse_args()

    if opts.quantity in ('default', ):
        try:
            res = gxx_info(opts.quantity, opts.configfile)
        except (FileNotFoundError, ValueError, KeyError) as err:
            print(err)
            sys.exit(1)
        print(res)
    elif opts.quantity in ('build_archs', ):
        try:
            res = gxx_build_archs(opts.configfile)
        except (FileNotFoundError, ValueError, KeyError) as err:
            print(err)
            sys.exit(1)
        print(res)
    else:
        try:
            res = get_path(opts.quantity, opts.configfile)
        except (FileNotFoundError, ValueError, KeyError) as err:
            print(err)
            sys.exit(1)
        print(res)


if __name__ == '__main__':
    main()
