# Gaussian tool suite


## Description

A simple library tool related to the use og Gaussian on HPC platforms.
It takes care of setting up some information to run on the platform.

Several modules are provides:
- `sub`: manages the core submission system
- `parse_ini`: parses a configuration file with information on Gaussian versions.
- `utils`: provides a HPC-aware system to query Gaussian utilities.

## To install the tool suite

pip3 install -e git+https://github.com/jbloino/gxxtools.git#egg=gxxtools
