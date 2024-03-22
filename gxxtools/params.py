"""Store paths for gxxtools module."""
import os

home = os.getenv('HOME')
user = os.getlogin()

# State of build of parameters
# 0: not initialized
# 1: initialized by basic init of gxxtools
# 2: gxxconfig has been loaded
# 3: HPC infrastructure specifications loaded
# 4: Gaussian specifications loaded
stage = 0

paths = {
    'gxxcfg': None,
    'hpcini': None,
    'rcpath': None,
    'gxxver': None,
}

files = {
    'gxxcfg': 'gxxconfig.ini',
    'hpcini': 'hpcnodes.ini',
    'gxxver': 'gxxversions.ini',
}

server = {
    'headaddr': os.uname().nodename,
    'mailaddr': None,
    'platform': None,
    'nodestype': None,
    'submitter': None,
    'deltmpcmd': None
}

nodes_info = None

gxx_versions = None

workings_def = None

workings_info = None

queues_info = None

node_family = None
