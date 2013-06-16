#!/usr/bin/env python

"""
Build script for FlightGear

Requires: Python 2.7

Supported distributions:
 * Debian wheezy
 * Ubuntu?
 * Other Debian?
"""

import sys
import os
import subprocess
import logging
import time


## === Configure logging =======================================================

logger = logging.getLogger('flightgear_build')
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)


## === Utilities ===============================================================

def run(*command, **kwargs):
        return subprocess.check_call(command)


def run_get_output(*command, **kwargs):
        return subprocess.check_output(command)


def identify_distro():
    from collections import namedtuple
    nt = namedtuple('release_info', ['distro', 'release', 'codename'])

    try:
        distro = run_get_output("lsb_release", "-si").strip()
        release = run_get_output("lsb_release", "-sr").strip()
        codename = run_get_output("lsb_release", "-sc").strip()
    except:
        pass  # Command failed for some reason..
    else:
        return nt(distro, release, codename)

    ## todo: fallback to using /etc/issue or other methods for older distros
    pass


SUDO_METHOD='auto'  # auto|sudo|su

def sudo(*command, **kwargs):
    global SUDO_METHOD
    if SUDO_METHOD == 'auto':
        try:
            run('which', 'sudo')
        except:
            SUDO_METHOD='su'
        else:
            SUDO_METHOD='sudo'

    if SUDO_METHOD == 'sudo':
        command = ('sudo',) + command

    elif SUDO_METHOD == 'su':
        ## todo: escape arguments in a better way!
        command = ['su', '-c', ' '.join(
            ['"{}"'.format(c.replace(r'"', r'\"')) for c in command])]

    elif SUDO_METHOD == 'ssh':
        ## todo: escape arguments in a better way!
        command = ('ssh', 'root@localhost') + command

    else:
        assert False  # We should never get here!

    return run(*command, **kwargs)


class chdir(object):
    def __init__(self, newdir):
        self.newdir = newdir
        self.olddir = None

    def __enter__(self):
        self.olddir = os.getcwd()
        if not os.path.exists(self.newdir):
            os.makedirs(self.newdir)
        os.chdir(self.newdir)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.olddir)


def select_git_branch(repo_dir, branch):
    """
    Select git branch or tag in a repository.
    """
    # todo: make this more bullet-proof!
    with chdir(repo_dir):
        run('git', 'fetch')
        run('git', 'checkout', '--force', branch)
        run('git', 'reset', '--hard')



## === Tasks ===================================================================

global BASE_DIRECTORY
BASE_DIRECTORY = os.path.abspath(os.path.dirname(__file__))

global GLOBAL_CONFIG
GLOBAL_CONFIG = {}


COMMON_PACKAGES = """
cvs subversion cmake make build-essential automake
fluid gawk gettext scons git-core

libalut0 libalut-dev
libasound2 libasound2-dev
libboost-dev
libboost-serialization-dev
libfltk1.3 libfltk1.3-dev
libglew1.5-dev
libhal-dev
libjasper1 libjasper-dev
libopenal1 libopenal-dev
libopenexr-dev
libpng12-0 libpng12-dev
libqt4-dev
libsvn-dev
libwxgtk2.8-0 libwxgtk2.8-dev
libxft2 libxft-dev
libxi6 libxi-dev
libxinerama1 libxinerama-dev
libxmu6 libxmu-dev
python-imaging-tk
python-tk
zlib1g zlib1g-dev
""".split()

UBUNTU_PACKAGES = COMMON_PACKAGES + """
freeglut3-dev
libapr1-dev
libjpeg62 libjpeg62-dev
""".split()

# Tested on Debian Wheezy
DEBIAN_PACKAGES = COMMON_PACKAGES + """
freeglut3-dev
libjpeg8 libjpeg8-dev
""".split()

SUPPORTED_DISTROS = [
    ('Debian', '7.0', 'wheezy'),
    ('Debian', '7.1', 'wheezy'),
]


def install_packages():
    """
    Install packages using package manager.
    """
    release_info = identify_distro()
    logger.debug("Release: {} {} {}".format(*release_info))
    if release_info not in SUPPORTED_DISTROS:
        logger.warning("Your distribution is not supported!")

    packages = []
    if release_info.distro == 'Ubuntu':
        packages = UBUNTU_PACKAGES
    else:  # Assume debian
        packages = DEBIAN_PACKAGES

    sudo('apt-get', 'update')
    sudo('apt-get', 'install', *packages)


##==============================================================================
## PLIB
##==============================================================================

PLIB_REPO = "http://plib.svn.sourceforge.net/svnroot/plib/trunk"
PLIB_STABLE_REVISION = "2172"


def download_plib(plib_source_dir, revision=None, update=True):
    if os.path.exists(plib_source_dir):
        if update and os.path.exists(os.path.join(plib_source_dir, '.svn')):
            ## We can update safely
            logger.debug("PLIB: Running svn update in existing local copy")
            with chdir(plib_source_dir):
                if revision is not None:
                    ## Specific version
                    logger.debug("PLIB: Selected revision: {}".format(revision))
                    run('svn', 'update', '-r', revision)
                else:
                    ## Unstable version
                    logger.debug("PLIB: Selected revision: latest")
                    run('svn', 'update')
            return  # We're done

        else:
            if update:
                ## Mumble.. better move it!
                logger.warning("PLIB: source directory doesn't appear to be "
                    "a subversion local copy. Moving and starting over.")
            else:
                logger.debug("PLIB: Old directory found -- moving since update=False")
            tmp_name = "{}.{}".format(plib_source_dir, int(time.time()))
            os.rename(plib_source_dir, tmp_name)

    logger.debug("PLIB: Running svn checkout to obtain a fresh copy")
    if revision is not None:
        logger.debug("PLIB: Selected revision: {}".format(revision))
        run('svn', '-r', revision, 'checkout', PLIB_REPO, plib_source_dir)
    else:
        logger.debug("PLIB: Selected revision: latest")
        run('svn', 'checkout', PLIB_REPO, plib_source_dir)


def build_plib(build_dir, install_dir, stable=True, update=True, reconfigure=True,
               clean=False, make_flags=None):
    logger.info("Building PLIB")
    plib_source_dir = os.path.join(build_dir, 'src', 'plib')
    plib_build_dir = os.path.join(build_dir, 'build', 'plib')

    GLOBAL_CONFIG['plib:source_dir'] = plib_source_dir
    GLOBAL_CONFIG['plib:build_dir'] = plib_build_dir
    GLOBAL_CONFIG['plib:install_dir'] = install_dir

    plib_revision = PLIB_STABLE_REVISION if stable else None
    download_plib(plib_source_dir, revision=plib_revision)

    if reconfigure:
        logger.debug("PLIB: Running autogen")
        with chdir(plib_source_dir):
            run('./autogen.sh')

        logger.debug("PLIB: Running configure")
        with chdir(plib_build_dir):
            run(os.path.join(plib_source_dir, 'configure'),
                "--disable-pw",
                "--disable-sl",
                "--disable-psl",
                "--disable-ssg",
                "--disable-ssgaux",
                "--prefix={}".format(install_dir),
                "--exec-prefix={}".format(install_dir))

    with chdir(plib_build_dir):
        logger.debug("PLIB: Running make")
        if make_flags is not None:
            run('make', *make_flags)
        else:
            run('make')

        logger.debug("PLIB: Running make install")
        run('make', 'install')


##==============================================================================
## OpenSceneGraph
##==============================================================================

OSG_STABLE_REVISION="http://svn.openscenegraph.org/osg/OpenSceneGraph/tags/OpenSceneGraph-3.1.1/"
OSG_UNSTABLE_REVISION="http://svn.openscenegraph.org/osg/OpenSceneGraph/tags/OpenSceneGraph-3.1.7/"


def download_openscenegraph(osg_source_dir, stable=True, update=True):
    if os.path.exists(osg_source_dir):
        if update and os.path.exists(os.path.join(osg_source_dir, '.svn')):
            ## We can update safely
            logger.debug("OSG: Running svn update in existing local copy")
            with chdir(osg_source_dir):
                ## todo: check that the version is correct!
                run('svn', 'update')
            return  # We're done

        else:
            if update:
                ## Mumble.. better move it!
                logger.warning("OSG: source directory doesn't appear to be a "
                    "subversion local copy. Moving and starting over.")
            else:
                logger.debug("OSG: Old directory found -- moving since update=False")
            tmp_name = "{}.{}".format(osg_source_dir, int(time.time()))
            os.rename(osg_source_dir, tmp_name)

    logger.debug("OSG: Running svn checkout to obtain a fresh copy")
    repo_url = OSG_STABLE_REVISION if stable else OSG_UNSTABLE_REVISION
    run('svn', 'checkout', repo_url, osg_source_dir)


def build_openscenegraph(build_dir, install_dir, stable=True, update=True,
        reconfigure=True, clean=False, make_flags=None):
    logger.info("Building OpenSceneGraph")
    osg_source_dir = os.path.join(build_dir, 'src', 'osg')
    osg_build_dir = os.path.join(build_dir, 'build', 'osg')

    GLOBAL_CONFIG['osg:source_dir'] = osg_source_dir
    GLOBAL_CONFIG['osg:build_dir'] = osg_build_dir
    GLOBAL_CONFIG['osg:install_dir'] = install_dir

    download_openscenegraph(osg_source_dir, stable=stable, update=update)

    if reconfigure:
        logger.debug("OSG: reconfiguring")
        with chdir(osg_build_dir):
            cmakecache_file = os.path.join(osg_source_dir, 'CMakeCache.txt')
            if os.path.exists(cmakecache_file):
                os.unlink(cmakecache_file)
            run('cmake',
                '-D', "CMAKE_BUILD_TYPE=Release",
                '-D', "CMAKE_CXX_FLAGS=-O3 -D__STDC_CONSTANT_MACROS",
                '-D', "CMAKE_C_FLAGS=-O3",
                '-D', "CMAKE_INSTALL_PREFIX:PATH={}".format(install_dir),
                osg_source_dir)

    with chdir(osg_build_dir):
        logger.info("OSG: Running make")
        run('make', *(make_flags or ()))

        logger.info("OSG: Running make install")
        run('make', 'install')

    # Fix for 64bit
    libdir = os.path.join(install_dir, 'lib')
    if not os.path.exists(libdir):
        os.symlink(os.path.join(install_dir, 'lib64'), libdir)


##==============================================================================
## OpenRTI
##==============================================================================

OPENRTI_REPO = "git://gitorious.org/openrti/openrti.git"
OPENRTI_UNSTABLE = "master"
OPENRTI_STABLE = "OpenRTI-0.3.0"


def download_openrti(source_dir, stable=True, update=True):
    git_branch = OPENRTI_STABLE if stable else OPENRTI_UNSTABLE

    need_move = False

    if os.path.exists(source_dir):
        if not update:
            logger.debug("OpenRTI: Old directory found -- moving since update=False")
            need_move = True

        elif not os.path.exists(os.path.join(source_dir, '.git')):
            logger.warning("OpenRTI: source directory doesn't appear to be a "
                           "git repository clone. Moving and starting over.")
            need_move = True

    if need_move:
        tmp_name = "{}.{}".format(source_dir, int(time.time()))
        os.rename(source_dir, tmp_name)

    if not os.path.exists(source_dir):
        logger.debug("OpenRTI: Running git clone to obtain a fresh copy")
        run('git', 'clone', OPENRTI_REPO, source_dir)

    ## Ok, now select the appropriate branch
    select_git_branch(source_dir, git_branch)


def build_openrti(build_dir, install_dir, stable=True, update=True,
        reconfigure=True, clean=False, make_flags=None):

    logger.info("Building OpenRTI")
    source_dir = os.path.join(build_dir, 'src', 'openrti')
    build_dir = os.path.join(build_dir, 'build', 'openrti')

    GLOBAL_CONFIG['openrti:source_dir'] = source_dir
    GLOBAL_CONFIG['openrti:build_dir'] = build_dir
    GLOBAL_CONFIG['openrti:install_dir'] = install_dir

    download_openrti(source_dir, stable=stable, update=update)

    if reconfigure:
        logger.debug("OpenRTI: reconfiguring")
        with chdir(build_dir):
            cmakecache_file = os.path.join(source_dir, 'CMakeCache.txt')
            if os.path.exists(cmakecache_file):
                os.unlink(cmakecache_file)
            run('cmake',
                '-D', "CMAKE_BUILD_TYPE=Release",
                '-D', "CMAKE_CXX_FLAGS=-O3 -D__STDC_CONSTANT_MACROS",
                '-D', "CMAKE_C_FLAGS=-O3",
                '-D', "CMAKE_INSTALL_PREFIX:PATH={}".format(install_dir),
                source_dir)

    with chdir(build_dir):
        logger.info("OpenRTI: Running make")
        if make_flags is not None:
            run('make', *make_flags)
        else:
            run('make')

        logger.info("OpenRTI: Running make install")
        run('make', 'install')


##==============================================================================
## SimGear
##==============================================================================

SIMGEAR_REPO = "git://gitorious.org/fg/simgear.git"
SIMGEAR_STABLE = "version/2.10.0-final"  # This is a tag
SIMGEAR_UNSTABLE = "remotes/origin/next"


def download_simgear(source_dir, stable=True, update=True):
    git_branch = SIMGEAR_STABLE if stable else SIMGEAR_UNSTABLE

    need_move = False

    if os.path.exists(source_dir):
        if not update:
            logger.debug("SimGear: Old directory found -- moving since update=False")
            need_move = True

        elif not os.path.exists(os.path.join(source_dir, '.git')):
            logger.warning("SimGear: source directory doesn't appear to be a "
                           "git repository clone. Moving and starting over.")
            need_move = True

    if need_move:
        tmp_name = "{}.{}".format(source_dir, int(time.time()))
        os.rename(source_dir, tmp_name)

    if not os.path.exists(source_dir):
        logger.debug("SimGear: Running git clone to obtain a fresh copy")
        run('git', 'clone', OPENRTI_REPO, source_dir)

    ## Ok, now select the appropriate branch
    select_git_branch(source_dir, git_branch)


# OPENRTI_INSTALL_DIR=openrti
# INSTALL_DIR_OPENRTI=$INSTALL_DIR/$OPENRTI_INSTALL_DIR
# cd "$CBD"

# if [ ! -d "openrti" ]
# then
#     mkdir "openrti"
# fi

# if [ "$WHATTOBUILD" = "" -o "$WHATTOBUILD" = "OPENRTI" -o "$WHATTOBUILD" = "ALL" ]
# then
#     echo "****************************************" | tee -a $LOGFILE
#     echo "**************** OPENRTI ***************" | tee -a $LOGFILE
#     echo "****************************************" | tee -a $LOGFILE


#     if [ "$DOWNLOAD" = "y" ]
#     then
#         cd openrti

#         echo -n "git FROM git://gitorious.org/openrti/openrti.git ... " >> $LOGFILE

#         if [ -d "openrti" ]
#         then
#             echo "openrti exists already."
#         else
#             git clone git://gitorious.org/openrti/openrti.git
#         fi

#         cd openrti

#         git fetch origin
#         if [ "$STABLE" = "STABLE" ]
#         then
#             # switch to stable branch
#             # create local stable branch, ignore errors if it exists
#             git branch -f $OPENRTI_STABLE_GIT_BRANCH origin/$OPENRTI_STABLE_GIT_BRANCH 2> /dev/null || true
#             # switch to stable branch. No error is reported if we're already on the branch.
#             git checkout -f $OPENRTI_STABLE_GIT_BRANCH
#             # get indicated stable version
#             git reset --hard $OPENRTI_STABLE_REVISION
#         else
#             # switch to unstable branch
#             # create local unstable branch, ignore errors if it exists
#             git branch -f $OPENRTI_UNSTABLE_GIT_BRANCH origin/$OPENRTI_UNSTABLE_GIT_BRANCH 2> /dev/null || true
#             # switch to unstable branch. No error is reported if we're already on the branch.
#             git checkout -f $OPENRTI_UNSTABLE_GIT_BRANCH
#             # pull latest version from the unstable branch
#             git pull
#         fi

#         cd ..

#         echo " OK" >> $LOGFILE
#         cd ..

#     fi

#     cd "openrti/openrti"

#     if [ ! "$UPDATE" = "UPDATE" ]
#     then
#         if [ "$RECONFIGURE" = "y" ]
#         then

#             cd "$CBD"
#             mkdir -p build/openrti
#             cd "$CBD"/build/openrti
#             echo -n "RECONFIGURE OPENRTI ... " >> $LOGFILE
#             rm -f ../../openrti/openrti/CMakeCache.txt
#             cmake -D CMAKE_BUILD_TYPE="Release" -D CMAKE_CXX_FLAGS="-O3 -D__STDC_CONSTANT_MACROS" -D CMAKE_INSTALL_PREFIX:PATH="$INSTALL_DIR_OPENRTI" ../../openrti/openrti/ 2>&1 | tee -a $LOGFILE
#             echo " OK" >> $LOGFILE



#         fi
#     fi

#     if [ "$COMPILE" = "y" ]
#     then


#         cd "$CBD"/build/openrti
#         echo "MAKE OPENRTI" >> $LOGFILE
#         echo "make $JOPTION $OOPTION " >> $LOGFILE
#         make $JOPTION $OOPTION 2>&1 | tee -a $LOGFILE

#         echo "INSTALL OPENRTI" >> $LOGFILE
#         make install 2>&1 | tee -a $LOGFILE
#     fi
#     cd -
# fi



if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--sudo-method', dest='sudo_method', action='store',
        default='auto', choices=('auto', 'sudo', 'su', 'ssh'),
        help='Select which method to be used for running commands '
             'as the superuser.')
    parser.add_argument(
        '--build-dir', dest='build_dir', action='store')
    parser.add_argument(
        '--install-dir', dest='install_dir', action='store')
    parser.add_argument(
        '--makeopts', dest='makeopts', action='store')
    args = parser.parse_args()

    SUDO_METHOD = args.sudo_method

    BUILD_DIR = os.path.abspath(args.build_dir)
    INSTALL_DIR = os.path.abspath(args.install_dir)
    MAKEOPTS = args.makeopts.split(' ')

    GLOBAL_CONFIG['build_dir'] = BUILD_DIR
    GLOBAL_CONFIG['install_dir'] = INSTALL_DIR

    #install_packages()
    # build_plib(
    #     build_dir=BUILD_DIR,
    #     install_dir=INSTALL_DIR,
    #     make_flags=MAKEOPTS)
    # build_openscenegraph(
    #     build_dir=BUILD_DIR,
    #     install_dir=INSTALL_DIR,
    #     make_flags=MAKEOPTS)
    build_openrti(
        build_dir=BUILD_DIR,
        install_dir=INSTALL_DIR,
        make_flags=MAKEOPTS)
    pass
