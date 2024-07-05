"""Provide basic data and arrays for gxxtools.

Provides basic constants that may be used by other modules or scripts.
"""

# Equivalency between procs archs and Gaussian mach dirs
# machine arch as defined in HPC ini file -> Macs in Gxx ini file.
# This depends on the naming convention adopted on each cluster
GXX_ARCH_FLAGS = {
    'nehalem': 'intel64-nehalem',
    'westmere': 'intel64-nehalem',
    'sandybridge': 'intel64-sandybridge',
    'ivybridge': 'intel64-sandybridge',
    'skylake': 'intel64-haswell',
    'cascadelake': 'intel64-haswell',
    'bulldozer': 'amd64-istanbul',
    'naples': 'intel64-haswell',
    'rome': 'intel64-haswell',
    'milan': 'intel64-haswell',
    'zen1': 'intel64-haswell',
    'zen2': 'intel64-haswell',
    'zen3': 'intel64-haswell',
}