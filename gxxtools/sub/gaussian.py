"""Gaussian submitter: setup of Gaussian system.

This module is part of the the library system and provides the
necessary information on the Gaussian setup on the hardware.
"""
import sys
import os
import re
import argparse
import typing as tp
from configparser import ConfigParser

from gxxtools.data import GXX_ARCH_FLAGS
import gxxtools.params as gtpar
import gxxtools.parse_ini as gtini


#  Gaussian-related definitions
# -----------------------------
# By default, Gxx_Sub allows unsupported workings (workings not listed in
#   the section of Gaussian versions).  If set False, only workings listed
#   in `Workings` are allowed.
_ANY_WORKING = True
GXX_ALIAS = None

GXX_FORMAT = re.compile(r'g(dv|\d{2})\.?\w\d{2}[p+]?')


def gaussian_default() -> str:
    """Return the default Gaussian version on architecture."""
    return gtini.gxx_info('default')


def gxx_parse_versions(gconf: ConfigParser,
                       work_tags: tp.Optional[tp.Sequence[str]]
                       ) -> tp.Tuple[tp.Dict[str, str], tp.List[str]]:
    """Parse data on installed Gaussian versions from `gconf`.

    Parses the information on the Gaussian versions from a Gaussian
    config file stored in `gconf`.

    Parameters
    ----------
    gconf
        Configuration file with available Gaussian versions.
    work_tags
        Work tags from default parameters.

    Returns
    -------
    dict
        Information on installed Gaussian versions.
    list
        Additional working tags.

    Raises
    ------
    KeyError
        Problem with key
    """
    # Extract Gaussian Installation Versions
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    # Supported formax gXX[.]ABB[p/+]
    gxx_versions = {}
    new_worktags = []
    for sec in sorted(gconf.sections()):
        if GXX_FORMAT.match(sec):
            key = sec.lower().replace('.', '').replace('+', 'p')
            gxx_versions[key] = {}
            data = gconf[sec]
            # Check if Path and ModuleName given, incompatible.
            if 'ModuleName' in data \
                    and {'FullPath', 'RootPath', 'BaseDir'} & set(data):
                raise KeyError('Incompatible Module and Path specifications.')
            # Define path
            res = '{rootpath}/{basedir}/{arch}/{gxx}'
            path_fmt = gconf.get(sec, 'GxxPathFmt', fallback=res).lower()
            # Root path
            if 'FullPath' in data:
                res = data['FullPath']
                path0 = '{fullpath}'
                path1 = '{rootpath}/{basedir}'
                if path0 in path_fmt:
                    path_fmt = path_fmt.replace(path0, res)
                elif path1 in path_fmt:
                    path_fmt = path_fmt.replace(path1, res)
                if '{rootpath}' in path_fmt or '{basedir}' in path_fmt:
                    raise KeyError('Overspecification in Gaussian root path.')
                gxx_versions[key]['path'] = path_fmt
            elif 'ModuleName' not in data:
                path = gconf.get(sec, 'RootPath', fallback=None)
                if ('rootpath' in path_fmt and path is None):
                    msg = 'ERROR: Missing Gaussian root installation dir.'
                    raise KeyError(msg)
                path_fmt = path_fmt.replace('{rootpath}', path)
                path = gconf.get(sec, 'BaseDir', fallback=None)
                if ('basedir' in path_fmt and path is None):
                    raise KeyError('ERROR: Missing `BaseDir` component.')
                path_fmt = path_fmt.replace('{basedir}', path)
                gxx_versions[key]['path'] = path_fmt
            else:
                gxx_versions[key]['module'] = gconf.get(sec, 'ModuleName')
            # Gaussian final directory
            gxx_versions[key]['gxx'] = gconf.get(
                sec, 'GDir', fallback=sec.split('.')[0].lower())
            # Machine architectures
            res = gconf.get(sec, 'Machs', fallback=None)
            if res is not None:
                if not res.strip():
                    res = None
                else:
                    res = [item.strip() for item in res.split(',')]
            gxx_versions[key]['mach'] = res
            # Gaussian version label
            if 'Name' in data:
                res = data['Name']
            else:
                if 'Gaussian' not in data or 'Revision' not in data:
                    msg = 'ERROR: Gaussian/Revision or Name must be provided.'
                    raise KeyError(msg)
                res = data['Gaussian'] + ' Rev. ' + data['Revision']
            gxx_versions[key]['name'] = res
            # Gaussian release date
            gxx_versions[key]['date'] = gconf.get(sec, 'Date', fallback=None)
            # Usage restrictions
            res = gconf.get(sec, 'Shared', fallback=None)
            if res is not None:
                items = [x.strip().lower() for x in res.split(',')]
                if {'any', 'all'} & set(items):
                    res = None
                else:
                    res = [x.strip() for x in res.split(',')]
            gxx_versions[key]['pub'] = res
            # Available standard/default workings
            if 'Workings' in data:
                res = [item.strip() for item in data['Workings'].split(',')]
                if set(res) - set(work_tags):
                    for item in res:
                        if item not in work_tags + new_worktags:
                            new_worktags.append(item)
            else:
                res = None
            gxx_versions[key]['work'] = res

    return gxx_versions, new_worktags


def gxx_work_refdata(gdefaults: tp.Dict[str, str]) -> tp.Dict[str, tp.Any]:
    """Parse working-related reference data from Gaussian versions file.

    Extracts and parses the default parameters for working trees.

    Parameters
    ----------
    gdefaults
        Default parameters set in the configuration file.

    Returns
    -------
    dict
        Working-tree reference information.

    Raises
    ------
    KeyError
        Problem with key
    """
    work_ref = {'tags': []}

    if 'workinfo' in gdefaults:
        work_ref['info'] = {}
        for info in gdefaults['workinfo'].split(','):
            res = [item.strip() for item in info.split(':', maxsplit=3)]
            if len(res) == 3:
                key = res[0] or 'def'
                name = res[1] or 'System'
                mail = res[2] or 'N/A'
            else:
                raise KeyError('ERROR: WorkInfo format must contain 2 ":"')
            if key in work_ref['tags']:
                raise KeyError(f'ERROR: Duplicate tags "{key}"')
            work_ref['tags'].append(key)
            work_ref['info'][key] = (name, mail)
    else:
        work_ref['info'] = {'def': ('System', 'N/A')}

    if 'workpath' in gdefaults:
        work_ref['roots'] = {0: gdefaults['workpath']}
        for info in gdefaults['workpath'].split(','):
            res = [item.strip() for item in info.split(':', maxsplit=1)]
            if len(res) == 2:
                key = res[0] or 'def'
                path = res[1]
            else:
                raise KeyError('ERROR: WorkPath format must contain 1 ":"')
            if key in work_ref['roots']:
                raise KeyError('ERROR: Duplicate tag in WorkPath')
            work_ref['roots'][key] = path
    else:
        work_ref['roots'] = None

    return work_ref


def parser_add_opts(parser: argparse._ArgumentGroup):
    """Add Gaussian-related parser options."""
    parser.add_argument(
        '-w', '--wrkdir', dest='gxxwrk', nargs='+', metavar='WORKDIR',
        help='''\
Appends a working directory to the Gaussian path to look for executables.
Several working directories can be given by using multiple times the -w
  option. In this case, the last given working directory is the first one
  using during the path search.
NOTE: Only the path to the working root directory is needed. The script
      automatically selects the correct directories from there.
WARNING: The script expects a working tree structure as intended in the
         Gaussian developer manual.
''')


def parser_doc_gaussian() -> str:
    """Build help documentation for Gaussian versions.

    Automatically builds the documentation block describing the
    installed Gaussian version for help messages.
    """
    gxx_help = 'Absolute paths or the following keywords are supported:\n'
    # Gaussian versions
    for gxx, gdata in gtpar.gxx_versions.items():
        if gxx == 'alias':
            continue
        gname = gdata['name']
        gdate = gdata['date'] or 'N/A'
        if gxx == gtini.gxx_info('default'):
            ginfo = ' - default'
        else:
            ginfo = ''
        gxx_help += f'+ {gxx:7s}: {gname:22s} ({gdate}){ginfo}\n'
    # Aliases
    for gxx, alias in gtpar.gxx_versions['alias'].items():
        gxx_help += f'+ {gxx:7s}: Alias for "{alias}"\n'
    # Workings
    for gxx, gwork in gtpar.workings_info.items():
        gname = gwork['name']
        gdate = gwork['date'] or 'N/A'
        gauth = gwork['auth'] or '<Unknown>'
        gxx_help += f'+ {gxx:7s}: Working by {gauth} for {gname} (updated: ' \
            + f'{gdate})\n'
        # For a prettier output, try to align the colons between the different
        # docs, so we calculate first the longest doctype.
        if gwork['clog'] is not None:
            l_doctype = 9
        else:
            l_doctype = 0
        if gwork['docs'] is not None:
            l_doctype = max(l_doctype, *[len(x) for x in gwork['docs']])
        # Build format only if l_doctype > 0:
        if l_doctype > 0:
            dfmt = f'    {{dtype:{l_doctype:d}s}}: {{path}}{{extra}}\n'
            if gwork['clog'] is not None:
                prt = []
                for path, ftype in gwork['clog']:
                    if path is not None:
                        prt.append([path, []])
                    else:
                        prt[-1][1].append(ftype)
                for item in prt:
                    if item[1]:
                        extra = f' ({", ".join(item[1])} available)'
                    else:
                        extra = ''
                    gxx_help += dfmt.format(dtype='CHANGELOG', path=item[0],
                                            extra=extra)
            if gwork['docs'] is not None:
                for dtype in gwork['docs']:
                    prt = []
                    for path, ftype in gwork['docs'][dtype]:
                        if path is not None:
                            prt.append([path, []])
                        else:
                            prt[-1][1].append(ftype)
                    for item in prt:
                        extra = f' ({", ".join(item[1])} available)' \
                            if item[1] else ''
                        gxx_help += dfmt.format(dtype=dtype, path=item[0],
                                                extra=extra)
    # End of documentation block
    gxx_help += '+ Arbitrary path given by user\n'

    return gxx_help


def gxx_parse_workings(gconf: ConfigParser,
                       gxx_versions: tp.Dict[str, str],
                       work_ref: tp.Optional[tp.Sequence[str]]
                       ) -> tp.Dict[str, str]:
    """Parse data on installed Gaussian working dirs from `gconf`.

    Parses the information on the available working trees from a
    Gaussian config file stored in `gconf`.

    Parameters
    ----------
    gconf
        Configuration file with available Gaussian versions.
    gxx_versions
        Information on installed Gaussian versions.
    work_ref
        Default working data parameters

    Returns
    -------
    dict
        Information on installed working trees.

    Raises
    ------
    KeyError
        Problem with key
    """
    workings = {}
    # We select the working-related sections by complementarity:
    #   everything which does not have the Gaussian version format
    #   is a priori a possible working
    # Gxx_QSub only supports the format "tag.gxx.rev"
    for sec in [sec for sec in sorted(gconf.sections())
                if not GXX_FORMAT.match(sec)]:
        wtags = sec.lower().replace('+', 'p').split('.')
        if len(wtags) != 3:
            continue
        tag, gxx, rev = wtags
        data = gconf[sec]
        # Get information on Gaussian version (shortened label and name)
        # Then compare if part of the versions
        gver = gxx + rev
        # Gaussian version label
        if 'Name' in data:
            gname = data['Name']
        else:
            if 'Gaussian' not in data or 'Revision' not in data:
                msg = 'ERROR: Gaussian/Revision or Name must be provided.'
                raise KeyError(msg)
            gname = data['Gaussian'] + ' Rev. ' + data['Revision']
        # Check if reference Gaussian version installed
        gkey = None
        if gver in gxx_versions:
            gkey = gver
        else:
            for key in gxx_versions:
                if gxx_versions[key]['name'] == gname:
                    gkey = key
        # Check if missing Gaussian installation or working not allowed
        if gkey is None:
            raise KeyError('ERROR: Reference Gaussian version not found.')
        elif not _ANY_WORKING:
            if tag not in gxx_versions[gkey]['Workings']:
                break
        # Build key
        # For GDV, since rev unique, use tagrev
        # For Gxx, there may be overlap, so taggxxrev
        if wtags[1] == 'gdv':
            key = tag + rev
        else:
            key = tag + gxx + rev
        workings[key] = {'gref': gkey}
        # Define path
        res = '{workpath}/{basedir}/{arch}'
        path_fmt = gconf.get(sec, 'WorkPathFmt', fallback=res).lower()
        # Root path
        if 'FullPath' in data:
            res = data['FullPath']
            path0 = '{fullpath}'
            path1 = '{workpath}/{basedir}'
            if path0 in path_fmt:
                path_fmt = path_fmt.replace(path0, res)
            elif path1 in path_fmt:
                path_fmt = path_fmt.replace(path1, res)
            if '{workpath}' in path_fmt or '{basedir}' in path_fmt:
                raise KeyError('Overspecification in working root path.')
        else:
            path = gconf.get(sec, 'WorkPath', fallback=None)
            if ('workpath' in path_fmt and path is None):
                raise KeyError('ERROR: Missing working root directory.')
            elif work_ref['roots'] is not None:
                if path == work_ref['roots'][0]:
                    if tag not in work_ref['roots']:
                        msg = f'ERROR: Missing default WorkPath for "{tag}"'
                        raise KeyError(msg)
                    wroot = work_ref['roots'][tag]
                else:
                    wroot = path
            else:
                wroot = path
            path_fmt = path_fmt.replace('{workpath}', wroot)
            path = gconf.get(sec, 'BaseDir', fallback=None)
            if ('basedir' in path_fmt and path is None):
                raise KeyError('ERROR: Missing `BaseDir` component.')
            path_fmt = path_fmt.replace('{basedir}', path)
            # if 'BaseDir' in data:
            #     res = os.path.join(wroot, data['BaseDir'])
            # else:
            #     msg = 'ERROR: Either `BaseDir`+`WorkPath` or `FullPath`' \
            #         + 'must be set.'
            #     raise KeyError(msg)
        workings[key]['path'] = path_fmt
        # Store the path without arch if present as the base directory
        path = path_fmt.rstrip(r'\/')
        if '{arch}' in path:
            workings[key]['basepath'] = re.sub(r'[\/]?\{arch\}', '', path)
        else:
            workings[key]['basepath'] = path
        # Gaussian version label
        workings[key]['name'] = gname
        # Version
        workings[key]['ver'] = gconf.get(sec, 'Version', fallback=None)
        # Update date
        workings[key]['date'] = gconf.get(sec, 'Date', fallback=None)
        # Machine architectures
        res = gconf.get(sec, 'Machs', fallback='')
        if res.strip():
            res = [item.strip() for item in res.split(',')]
        workings[key]['mach'] = res
        # Usage restrictions
        res = gconf.get(sec, 'Shared', fallback=None)
        if res is not None:
            items = [x.strip().lower() for x in res.split(',')]
            if {'any', 'all'} & set(items):
                res = None
            else:
                res = [x.strip() for x in res.split(',')]
        workings[key]['pub'] = res
        # Author information
        if tag in work_ref['info']:
            workings[key]['auth'] = work_ref['info'][tag][0]
            workings[key]['mail'] = work_ref['info'][tag][1]
        else:
            workings[key]['auth'] = None
            workings[key]['mail'] = None
        # Changelog
        if 'changelog' in data:
            vers = data['changelog'].split(',')
            workings[key]['clog'] = []
            for item in vers:
                res = item.split(':')
                if len(res) == 2:
                    fname, ftype = [s.strip() for s in res]
                else:
                    fname = res[0].strip()
                    ftype = os.path.splitext(fname)[0][1:].upper()
                if fname.strip().startswith('.'):
                    if fname.count('.') == 1:
                        if len(workings[key]['clog']) == 0:
                            msg = 'ERROR: Changelog alternative format but ' \
                                + 'no main format.'
                            raise KeyError(msg)
                        else:
                            fname = None
                if fname is not None:
                    fname = fname.format(fullpath=workings[key]['basepath'])
                workings[key]['clog'].append((fname, ftype))
        else:
            workings[key]['clog'] = None
        # Other documentations
        if 'docs' in data:
            workings[key]['docs'] = {}
            docs = data['docs'].split('\n')
            for item0 in docs:
                try:
                    keydoc, paths = item0.split(':', maxsplit=1)
                except ValueError as err:
                    msg = 'ERROR: Format for docs should be:' \
                        + 'DOCTYPE:path[:format][,[altpath]ext[:format]].'
                    raise KeyError(msg) from err
                workings[key]['docs'][keydoc] = []
                vers = paths.split(',')
                for item1 in vers:
                    res = item1.split(':')
                    if len(res) == 2:
                        fname, ftype = [s.strip() for s in res]
                    else:
                        fname = res[0].strip()
                        ftype = os.path.splitext(fname)[0][1:].upper()
                    if fname.strip().startswith('.'):
                        if fname.count('.') == 1:
                            if len(workings[key]['docs'][keydoc]) == 0:
                                msg = f'ERROR: {keydoc} alternative' \
                                    + 'format but no main format.'
                                raise KeyError(msg)
                            else:
                                fname = None
                    if fname is not None:
                        fname = fname.format(
                            fullpath=workings[key]['basepath'])
                    workings[key]['docs'][keydoc].append((fname, ftype))
        else:
            workings[key]['docs'] = None

    return workings


def parse_queries(_opts: argparse.Namespace) -> bool:
    """Check query options from parsing result.

    Checks if Gaussian-related query options have been provided.
    Returns True if a query was requested.
    """
    return False


def get_gxx_spec(opts: argparse.Namespace) -> tp.Tuple[str, str, str]:
    """Check options related to Gaussian version.

    Checks Gaussian version, working tree info and rights.
    Returns 3 types of information:

    - name of the Gaussian executable
    - list of commands to set up Gaussian environments
    - exedir command to be passed to Gaussian executable

    Parameters
    ----------
    opts : str
        Result of the argument line parsing, with at least these attrs.
        gxxver: Gaussian version or full path.
        gxxwrk: Gaussian working versions or paths.

    Returns
    -------
    str
        name of the Gaussian executable
    str
        list of commands to set up Gaussian environments
    str
        exedir command to be passed to Gaussian executable
    """
    def get_gxx_arch() -> str:
        """Return the compatible GXX architecture."""
        try:
            gxx_arch = GXX_ARCH_FLAGS[gtpar.node_family.cpu_arch]
        except KeyError:
            print('INTERNAL ERROR: Unsupported hardware architecture.')
            sys.exit(9)
        return gxx_arch

    gxxroot = None
    gxxwork = None
    is_path = False
    if opts.gxxver in gtpar.gxx_versions['alias']:
        gver = gtpar.gxx_versions['alias'][opts.gxxver]
    else:
        gver = opts.gxxver
    if gver in gtpar.workings_info:
        work_info = gtpar.workings_info[gver]
        gver_info = gtpar.gxx_versions[work_info['gref']]
    elif gver in gtpar.gxx_versions:
        work_info = None
        gver_info = gtpar.gxx_versions[gver]
    else:
        work_info = None
        gver_info = None
        if os.path.exists(gver) or gtpar.DEBUG:
            is_path = True
            # Check if directory or executable file
            if not os.path.isdir(gver):
                gxxroot = os.path.split(gver)[0]
            else:
                gxxroot = gver
        else:
            print('ERROR: Gaussian option neither keyword nor valid path.')
            sys.exit(2)
    # Check Access
    if gver_info is not None:
        if gver_info['pub'] is not None and gtpar.user not in gver_info['pub']:
            print('ERROR: User is not allowed to use this Gaussian version.')
            sys.exit(3)
    if work_info is not None:
        if work_info['pub'] is not None and gtpar.user not in work_info['pub']:
            print('ERROR: User is not allowed to use this working tree.')
            sys.exit(3)

    # Definition of Gaussian executable
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    gxx_arch = None
    env_cmds = []
    # Check if module requested.
    if not is_path and 'module' in gver_info:
        env_cmds.append(f'module add {gver_info["module"]}')
    else:
        if gver_info is not None:
            gxx_arch = get_gxx_arch()
            if gver_info['mach'] is not None:
                if gxx_arch not in gver_info['mach']:
                    print(
                        'ERROR: Unsupported machine architecture in working.')
                    sys.exit(2)
                gxxroot = gver_info['path'].replace('{arch}', gxx_arch)
            else:
                gxxroot = gver_info['path']
            gxxroot = gxxroot.replace('{gxx}', gver_info['gxx'])
            if '{arch}' in gxxroot:
                print('ERROR: Gaussian path not fully resolved.')
                sys.exit(2)
        dirlist = [os.path.join(gxxroot, f)
                   for f in ['bsd', 'local', 'extras', '']]
        gauss_exedir = os.pathsep.join(dirlist)
        env_cmds.append(f'export GAUSS_EXEDIR="{gauss_exedir}"')
        env_cmds.append(
            f'export GAUSS_ARCHDIR="{os.path.join(gauss_exedir, "arch")}"')
        if 'PATH' in os.environ:
            txt = gauss_exedir + os.pathsep + '${PATH}'
        else:
            txt = gauss_exedir
        env_cmds.append(f'export PATH="{txt}"')
        if 'LD_LIBRARY_PATH' in os.environ:
            txt = gauss_exedir + os.pathsep + '${LD_LIBRARY_PATH}'
        else:
            txt = gauss_exedir
        env_cmds.append(f'export LD_LIBRARY_PATH="{txt}"')

    if work_info is not None:
        if gxx_arch is None:
            gxx_arch = get_gxx_arch()
        if work_info['mach'] is not None:
            if gxx_arch not in work_info['mach']:
                print('ERROR: Unsupported machine architecture in working.')
                sys.exit(2)
            gxxwork = work_info['path'].replace('{arch}', gxx_arch)
        else:
            gxxwork = work_info['path']
        if '{arch}' in gxxwork:
            print('ERROR: Working path not fully resolved.')
            sys.exit(2)

    # Paths built, complete check on workings with user options.
    gxxworks = []
    if gxxwork:
        gxxworks.append(gxxwork)
    if opts.gxxwrk:
        for workdir in opts.gxxwrk:
            if os.path.exists(workdir) or gtpar.DEBUG:
                gxxworks.append(workdir)
            else:
                fmt = 'ERROR: working tree directory "{}" does not exits'
                print(fmt.format(workdir))
                sys.exit(2)

    # Sets commands relative to workings
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    gxx_exedir = ''
    if gxxworks:
        gxx_exedir = ' -exedir='
        for gxxwork in gxxworks:
            gxx_exedir += f'{gxxwork}/l1:{gxxwork}/exe-dir:'
        gxx_exedir += ' $GAUSS_EXEDIR'

    return gver_info['gxx'], '\n'.join(env_cmds), gxx_exedir


def init():
    """Initialize Gaussian system information."""
    # Check that necessary information is loaded
    if gtpar.stage < 3:
        raise NameError('Stages in gxxtools have not been properly built.')
    # Get Gaussian data file
    gconf = ConfigParser()
    gxxfiles = []
    path = os.path.join(os.getenv('HOME'), gtpar.files['gxxver'])
    if os.path.exists(path) or gtpar.DEBUG:
        gxxfiles.append(path)
    if gtpar.paths['gxxver'] is not None:
        gxxfiles.append(gtpar.paths['gxxver'])
    if not gxxfiles:
        print('Missing configuration files.  Nothing to do.')
        sys.exit(10)
    gconf.read(gxxfiles)
    gdefaults = gconf.defaults()

    try:
        gtpar.workings_def = gxx_work_refdata(gdefaults)
    except KeyError as err:
        print('ERROR: Failed to get standard working data.')
        print('Motive:', err)
        sys.exit(1)

    try:
        gtpar.gxx_versions, worktag = \
            gxx_parse_versions(gconf, gtpar.workings_def['tags'])
    except KeyError as err:
        print('ERROR: Failed to get information on Gaussian versions')
        print('Motive:', err)
        sys.exit(1)
    gtpar.workings_def['tags'].extend(worktag)

    # Check that GDEFAULT is present
    if gtini.gxx_info('default') not in gtpar.gxx_versions:
        print('ERROR: Default version of Gaussian not present in config files')
        sys.exit(1)

    # Sort Working Tags
    # ^^^^^^^^^^^^^^^^^
    gtpar.workings_def['tags'].sort()
    scr = [item.lower() for item in gtpar.workings_def['tags']]
    if len(scr) < len(gtpar.workings_def['tags']):
        print('WARNING: Some tags only differ by the case.',
              'Assuming this is correct.')

    # Gaussian working information
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    try:
        gtpar.workings_info = gxx_parse_workings(gconf, gtpar.gxx_versions,
                                                 gtpar.workings_def)
    except KeyError as err:
        print('ERROR: Failed to get information on installed workings')
        print('Motive:', err)
        sys.exit(1)

    # Gaussian Keyword Aliases
    # ^^^^^^^^^^^^^^^^^^^^^^^^
    gtpar.gxx_versions['alias'] = {gxx[:3]: gxx for gxx in gtpar.gxx_versions}

    gtpar.stage = 4
