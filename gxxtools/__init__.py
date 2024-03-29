"""Initialize the gxxtool library system."""

import os
import sys
import re
import typing as tp
from configparser import ConfigParser, ExtendedInterpolation

import gxxtools.params as gtpar
import gxxtools.parse_ini as gtini

_RC_FILE = 'gxxtoolsrc'
_RC_DIR = os.path.join(gtpar.home, '.config')
_RC_PATH = os.path.join(_RC_DIR, _RC_FILE)
_ALT_RC_PATH = os.path.join(gtpar.home, f'.{_RC_FILE}')


def load_rc(server: tp.Optional[str] = None):
    """Initialize basic parameters for GxxTools.
    
    server can be provided to override the default configuration,
    typically for debugging purposes.
    
    Parameters
    ----------
    server
        Server to emulate, either as a full address or an alias,
        compatible with gxxtoolsrc section keywords.
    """
    if os.path.exists(_RC_PATH):
        gt_rc_file = _RC_PATH
    elif os.path.exists(_ALT_RC_PATH):
        gt_rc_file = _ALT_RC_PATH
    else:
        gt_rc_file = None
    if gt_rc_file is None:
        print(f'Missing configuration file.  Creating template in {_RC_PATH}.')
        if not os.path.exists(_RC_DIR):
            os.makedirs(_RC_DIR)
        with open(_RC_PATH, 'w', encoding='utf-8') as fobj:
            fobj.write("""\
# Configuration file for the gxxtool library.
# Each section corresponds to a HPC head node hostname or domain.
# examples: "*.domain.com" or "example.domain.com"
# Multiple equivalent domains/addresses can be given, separated by commas.
# example: "example1.domain.com, example2.domain.com"
# The file should primarily contains path to configuration files, which
# should contain the necessary information.
# Supported fields are:
# - gxx_config: path to gxxconfig.ini with general information on Gaussian
#              installation and infrastructure configuration.
# - hpc_config: path to hpcconfig.ini file, with nodes/hardware-specific
#              information.
# - gxx_versions: path to gxxversions.ini file, with information on Gaussian
#                versions available on cluster.

[*.example.com]
gxx_config = /home/user/gxxconfig_example.ini
hpc_config = /home/user/hpcconfig_example.ini
gxx_versions = /home/user/gxxversions_example.ini
""")
        sys.exit(1)

    if gtpar.DEBUG:
        print('Using main configuration file from', gt_rc_file)

    if server is not None:
        if gtpar.DEBUG:
            print(f'Overridding the server addr to: {server}.')
        gtpar.server['headaddr'] = server

    config = ConfigParser(interpolation=ExtendedInterpolation())
    config.read(gt_rc_file)

    _secok = None
    while _secok is None:
        for section in config.sections():
            for addr in section.split(','):
                pattern = addr.strip().replace('.', r'\.').replace('*', r'.+')
                if re.match(pattern, gtpar.server['headaddr']):
                    _secok = section
                    break
        else:
            break

    if _secok is None:
        print(f'Missing configuration for {gtpar.server["headaddr"]}')
        sys.exit(10)

    _sec = config[_secok]

    keypath = {
        'gxx_config': {
            'key': 'gxxcfg',
            'doc': 'path to general infrastructure information file'
        },
        'hpc_config': {
            'key': 'hpcini',
            'convert': str,
            'doc': 'path to HPC hardware information file',
        },
        'gxx_versions': {
            'key': 'gxxver',
            'convert': str,
            'doc': 'path to Gaussian versions information file',
        },
    }

    for key, db in keypath.items():
        path = _sec.get(key).format(home=gtpar.home)
        if path is None:
            print(f'Missing {db["doc"]}.')
            if gtpar.files.get(db['key'], default=None) is not None:
                if os.path.exists(os.path.join(gtpar.home,
                                               gtpar.files[db['key']])):
                    path = os.path.join(gtpar.home, gtpar.files[db['key']])
                    print(f'Found {path}.  Using it.')
            if path is None:
                sys.exit(10)
        elif not os.path.exists(path):
            print(f'ERROR: Configuration file not found at {path}')
            sys.exit(1)
        gtpar.paths[db['key']] = path

    gtpar.stage = 1
    gtpar.paths['rcfile'] = gt_rc_file

    # Load basic information from gxxconfig.ini
    gtpar.server['mailaddr'] = gtini.srv_info('email')
    gtpar.server['platform'] = gtini.srv_info('alias')
    gtpar.server['nodestype'] = gtini.srv_info('jobtype')
    gtpar.server['submitter'] = gtini.srv_info('submitter')
    gtpar.server['deltmpcmd'] = gtini.srv_info('cleanscratch')
    gtpar.server['runlocal'] = gtini.srv_info('runlocal')
    gtpar.stage = 2
