#!/usr/bin/env python

###############################################################################
#                                                                             #
#   ctx.py                                                                    #
#   Contexo main tool - (c) Scalado AB 2008                                   #
#                                                                             #
#   Author: Manuel Astudillo (manuel.astudillo@scalado.)                      #
#   License GPL v2. See LICENSE.txt.                                          #
#   ------------                                                              #
#                                                                             #
#                                                                             #
###############################################################################
# coding=UTF-8
import logging
import logging.handlers
import os
import os.path
import sys
import shutil
from contexo import ctx_view
from contexo import ctx_cfg
from contexo import ctx_envswitch
from contexo import ctx_common
from contexo import ctx_common
from contexo import ctx_comp
from contexo import ctx_sysinfo

import locale
try:
    #this fails on windows, but it doesn't matter much
    locale.resetlocale() # locale.LC_ALL,  'en_US.UTF-8')
except:
    pass

try:
    import platform
    if platform.architecture()[0] == '64bit' and platform.architecture()[1] == 'WindowsPE':
        userErrorExit("64-bit Python on Windows does not support 32-bit pysvn. Install 32-bit Python instead.")
except:
    # if we have an old Contexo installation we might wind up here due to Contexo previously having a package named 'platform'
    pass

logging.basicConfig(format = '%(asctime)s %(levelname)-8s %(message)s',
                                datefmt='%H:%M:%S',
                                level = logging.DEBUG);

#
# Get configuration.
#
contexo_config_path = os.path.join( ctx_common.getUserCfgDir(), ctx_sysinfo.CTX_CONFIG_FILENAME )
infoMessage("Using config file '%s'"%contexo_config_path,  1)
cfgFile = ctx_cfg.CFGFile( contexo_config_path )

setInfoMessageVerboseLevel( int(cfgFile.getVerboseLevel()) )

CTX_DEFAULT_BCONF = cfgFile.getDefaultBConf().strip(" '")


def dir_has_rspec(view_dir):
    view_filelist = os.listdir(view_dir)
    for entry in view_filelist:
        if entry.endswith('.rspec'):
            return True
    return False

def get_view_dir():
    caller_dir = os.path.abspath('.')
    view_dir = os.path.abspath('.')
    os.chdir(view_dir)
    view_dir = os.path.abspath('')
    while not dir_has_rspec(view_dir):
        os.chdir('..')
        if view_dir == os.path.abspath(''):
            userErrorExit('ctx could not find an rspec in the supplied argument or any subdirectory')
        view_dir = os.path.abspath('')
    return view_dir
 
#------------------------------------------------------------------------------
def cmd_updateview():
     view_dir = get_view_dir(args.view)

    cview = ctx_view.CTXView( view_dir, updating=True, validate=True )
    # cview.updateRepositories()

    # cview.checkoutRepositories()

