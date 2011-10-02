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
from internal_argparse import ArgumentParser
import internal_argparse
from contexo import ctx_view
from contexo import ctx_cfg
from contexo.ctx_envswitch  import  assureList, EnvironmentLayout, switchEnvironment
from contexo import ctx_common
from contexo.ctx_common import setInfoMessageVerboseLevel, infoMessage, userErrorExit, warningMessage, ctxAssert
from contexo.ctx_comp import ctx_log, COMPFile
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

msgSender           = 'ctx.py'
logging.basicConfig(format = '%(asctime)s %(levelname)-8s %(message)s',
                                datefmt='%H:%M:%S',
                                level = logging.DEBUG);

#
# Get configuration.
#
contexo_config_path = os.path.join( ctx_common.getUserCfgDir(), ctx_sysinfo.CTX_CONFIG_FILENAME )
infoMessage("Using config file '%s'"%contexo_config_path,  1)
cfgFile = ctx_cfg.CFGFile( contexo_config_path )

#legacy code: to be rewritten
setInfoMessageVerboseLevel( int(cfgFile.getVerboseLevel()) )

CTX_DEFAULT_BCONF = cfgFile.getDefaultBConf().strip(" '")


def dir_has_rspec(view_dir):
    view_filelist = os.listdir(view_dir)
    for entry in view_filelist:
        if entry.endswith('.rspec'):
            return True
    return False


#TODO: make args not global in ctx.py
#------------------------------------------------------------------------------
# tolerate missing headers was removed since contexo assumed that external headers would be set up correctly, no one bothered to do this, and the compiler didn't complain so this option was mainly a nuicence.
def deprecated_tolerate_missing_headers_warning(args):
    if args.tolerate_missing_headers:
        warningMessage('--tolerate-missing-headers is deprecated and redunant. The default is to ignore missing headers and let the compiler abort compilation if necessary. To get the old behaviour where contexo aborts when headers are missing: use the \'--fail-on-missing-headers\' option.')

# --repo-validaiton caused excessive round trips to the revision control server - bad for usage on vpn - and also exposed a bug with .env switching in ctx export that would cause ctx unable to find git if the path has been set in an .env file.
# A further motivation for removing repo-validation was that it's only needed when communicating with an rcs, not so much when building and exporting to build plugins.
def deprecated_repo_validation_warning(args):
    if args.repo_validation:
        warningMessage('--repo-validation is deprecated. Please run \'ctx view validate\' manually to validate the view.')

#------------------------------------------------------------------------------
def deprecated_nra_warning( args ):

    if args.no_remote_repo_access == True:
        warningMessage("--no-repo-access is deprecated. remote access will always be performed when running 'ctx view update' and 'ctx view validate'. At other times, there will be no network communication and .rspecs will be cached.")

#------------------------------------------------------------------------------
def getBuildConfiguration( cview ,  args):
    from contexo import ctx_bc
    from contexo import ctx_config

    if args.bconf != None:
        bcFilename = args.bconf
    else:
        if CTX_DEFAULT_BCONF != None:
            infoMessage("Using default build configuration '%s'"%(CTX_DEFAULT_BCONF), 2)
            bcFilename = CTX_DEFAULT_BCONF
        else:
            userErrorExit("No build configuration specified.")

    bc = ctx_bc.BCFile( bcFilename, cview, cfgFile)

    return bc

#------------------------------------------------------------------------------
def expand_list_files( view, item_list ):

    expanded_item_list = list()
    for item in item_list:
        item = item.strip(' ')
        if item.startswith('@'):
            infoMessage("Expanding list file '%s'"%item, 2)
            item = item.lstrip('@')
            list_file = view.locateItem( item, ctx_view.REPO_PATH_SECTIONS )
            list_file_items = ctx_common.readLstFile( list_file )
            expanded_item_list.extend( list_file_items )
        else:
            expanded_item_list.append(item)

    return expanded_item_list



#------------------------------------------------------------------------------
# Creates and returns a list of CTXCodeModule objects from the provided list
# of code module names. Unit tests are only enables for main modules (not for
# dependencies)
#------------------------------------------------------------------------------
def create_components( comp_filenames, component_paths_, obj_dir, launch_path ):

    # Construct and validate component objects
    components = list()
    for comp_file_ in comp_filenames:
        comp = COMPFile( comp_file = comp_file_, component_paths = component_paths_, globalOutputDir = obj_dir, launchPath = launch_path )
        components.append( comp )

    return components

#------------------------------------------------------------------------------
def build_libraries( ctx_modules, lib_name, output_path, build_dir, session ):

    #
    # Build either one library of all modules, or one library for each module.
    #

    if not os.path.exists( output_path ):
        os.makedirs( output_path )

    libs = dict()
    if lib_name != None:
        libs[lib_name] = assureList( ctx_modules )
    else:
        for mod in ctx_modules:
            libs[mod.getName()] = [mod,]

    all_objects = list()
    for lib, mods in libs.iteritems():
        ctx_log.ctxlogBeginLibrary( lib )

        obj_list = list()
        for mod in mods:
            mod_objs = mod.buildStaticObjects( session, build_dir )
            obj_list +=  mod_objs

        if len(obj_list) > 0:
            session.buildStaticLibrary( obj_list, lib, output_path )
        else:
            warningMessage("No object files to create library '%s'"%(lib))

        all_objects+= obj_list

        ctx_log.ctxlogEndLibrary()
    return all_objects

#------------------------------------------------------------------------------
def export_public_module_headers ( depmgr, modules, headerPath ):

    if headerPath == None:
        return

    if not os.path.exists( headerPath ):
        os.makedirs( headerPath )

    publicHeaders = depmgr.getPublicHeaders(modules,  True)
    for publicHeader in publicHeaders:
        src = publicHeader
        dst = os.path.join( headerPath, os.path.basename(publicHeader) )
        infoMessage("Exporting header: %s"%(os.path.basename(publicHeader)))
        shutil.copyfile( src, dst )

#------------------------------------------------------------------------------
def export_headers( depmgr, headers, headerDir, cview ):

    if not os.path.exists( headerDir ):
        os.makedirs( headerDir )

    #infoMessage("Exporting headers", 1)
    for header in headers:
        header_found = False
        src = depmgr.getFullPathname ( header )
        dst = os.path.join( headerDir, header )
        if src != None:
            infoMessage("%s -> %s"%(src, dst), 2)
            if not os.path.abspath(dst) == os.path.abspath(src):
                shutil.copyfile( src, dst )
                header_found = True
        else:
            header_extensions = [ '.h','.hpp', ]
            module_paths = cview.getItemPaths('modules')
            for module_path in module_paths:
                if not os.path.isdir( module_path ):
                    continue
                diritems = os.listdir( module_path )
                for modname in diritems:
                    if not os.path.isdir( os.path.join(module_path, modname) ):
                        continue
                    moddir = os.path.join(module_path, modname)
                    for hdrcand in os.listdir( moddir ):
                        if hdrcand != header:
                            continue
                        root, ext = os.path.splitext( hdrcand )
                        if header_extensions.count( ext ) != 0:
                            src = os.path.join( moddir, hdrcand)
                            shutil.copyfile( src , dst )
                            header_found = True
            # infoMessage("Exporting header: %s   (from %s)"%(os.path.basename(src), os.path.dirname(src)))
 
        if not header_found:
            warningMessage("Unable to locate header '%s' for export"%(header))

#------------------------------------------------------------------------------
def buildmodules( depmgr=None, session=None, modules=None, args=None, output_path=None, build_dir=None,  libraryName = None ):
    from contexo import ctx_base
    from contexo import ctx_envswitch

    depmgr.updateDependencyHash()

    all_modules = depmgr.getCodeModulesWithDependencies() if args.deps else modules
    all_modules.sort ()
    dep_modules = set(all_modules) - set(modules)

    ctx_modules = depmgr.createCodeModules( modules, args.tests, force=args.force )
    ctx_modules.extend ( depmgr.createCodeModules( dep_modules, force=args.force ) )

    objs = build_libraries( ctx_modules, libraryName, output_path, build_dir, session )
    return objs


#------------------------------------------------------------------------------
def cmd_info(args):
    userErrorExit("info is deprecated")

#------------------------------------------------------------------------------
def cmd_buildmod(args):
    launch_path = os.path.abspath('.')
    view_dir = get_view_dir(args.view)
    obj_dir = view_dir + os.sep + '.ctx/obj'
    if args.output[0] != '/' and args.output[0] != '\\' and args.output[1:3] != ':\\':
        lib_output = args.output
    else:
        # relative to view root
        lib_output = os.path.join( view_dir, args.output)

    from contexo import ctx_cmod
    from contexo import ctx_base
    from contexo import ctx_envswitch
    from contexo.ctx_depmgr import CTXDepMgr

    # Switch to specified environment
    oldEnv = None
    if args.env != None:
        envLayout   = EnvironmentLayout( cfgFile,  args.env )
        oldEnv      = switchEnvironment( envLayout, True )

    if args.logfile != None:
        ctx_log.ctxlogStart()

    # Prepare all
    deprecated_nra_warning( args )
    deprecated_repo_validation_warning(args)
    cview   = ctx_view.CTXView( view_dir, validate=False )
    modules = expand_list_files(cview, args.modules)
    bc      = getBuildConfiguration( cview,  args )


    deprecated_tolerate_missing_headers_warning(args)
    depmgr = CTXDepMgr ( codeModulePaths = cview.getItemPaths('modules'), failOnMissingHeaders = args.fail_on_missing_headers, archPath = bc.getArchPath(), legacyCompilingMod = args.legacy_compiling_mod, legacyDuplicateSources = args.legacy_duplicate_sources, globalOutputDir = obj_dir, bc = bc )

    depmgr.addCodeModules( modules, args.tests )

    session = ctx_base.CTXBuildSession( bc )

    session.setDependencyManager( depmgr )



    # Register build configuration in log handler
    ctx_log.ctxlogSetBuildConfig( bc.getTitle(),
                                  bc.getCompiler().cdefTitle,
                                  bc.getBuildParams().cflags,
                                  bc.getBuildParams().prepDefines,
                                  "N/A" )

    output_path = os.path.join( lib_output, args.libdir )
    print >>sys.stderr, output_path

    ## TODO: place this in CTXCompiler where it belongs when the spaghetti code is gone
    ## changing working directory to .ctx/obj/[BUILDCONFIGNAME]
    dest_wd = os.path.join(obj_dir, bc.getTitle())
    try:
        os.makedirs(dest_wd)
    except:
        pass
    old_path = os.path.abspath('')
    os.chdir(dest_wd)
    buildmodules( depmgr, session, modules, args, output_path, bc.getTitle(),  libraryName = args.lib)
    old_path = os.path.abspath('')

    header_path = os.path.join(lib_output, args.headerdir )
    export_public_module_headers( depmgr, modules, header_path )


    # Write log if requested
    if args.logfile != None:
        logfilepath = os.path.join( lib_output, args.logfile )
        logpath     = os.path.normpath(os.path.dirname( logfilepath ))
        if len(logpath) and not os.path.isdir(logpath):
            os.makedirs( logpath )

        ctx_log.ctxlogWriteToFile( logfilepath, appendToExisting=False )

    # Switch back to original environment
    if args.env != None:
        switchEnvironment( oldEnv, False )

#------------------------------------------------------------------------------
def cmd_buildcomp(args):
    launch_path = os.path.abspath('.')
    view_dir = get_view_dir(args.view)
    obj_dir = view_dir + os.sep + '.ctx/obj'
    if args.output[0] == '/' or args.output[0] == '\\' or args.output[1:3] == ':\\':
        lib_output = args.output
    else:
        # relative to view root
        lib_output = os.path.join(view_dir,args.output)

    from contexo import ctx_cmod
    from contexo import ctx_base
    from contexo import ctx_envswitch
    from contexo.ctx_depmgr import CTXDepMgr
    absIncDirs = map(os.path.abspath,  args.incdirs)

    # Switch to specified environment
    oldEnv = None
    if args.env != None:
        envLayout = EnvironmentLayout( cfgFile,  args.env )
        oldEnv    = switchEnvironment( envLayout, True )

    if args.logfile != None:
        ctx_log.ctxlogStart()

    # Prepare all
    deprecated_nra_warning( args )
    deprecated_repo_validation_warning(args)
    cview       = ctx_view.CTXView( view_dir, validate=False )
    components  = expand_list_files( cview, args.components )

    bc          = getBuildConfiguration( cview,  args )
    bc.buildParams.incPaths.extend(     absIncDirs ) #TODO: accessing 'private' data?
    deprecated_tolerate_missing_headers_warning(args)
    depmgr = CTXDepMgr ( codeModulePaths = cview.getItemPaths('modules'), failOnMissingHeaders = args.fail_on_missing_headers, archPath = bc.getArchPath(), legacyCompilingMod = args.legacy_compiling_mod, legacyDuplicateSources = args.legacy_duplicate_sources, globalOutputDir = obj_dir, bc = bc  )
    session     = ctx_base.CTXBuildSession( bc )
    session.setDependencyManager( depmgr )

    # Register build configuration in log handler
    ctx_log.ctxlogSetBuildConfig( bc.getTitle(),
                                  bc.getCompiler().cdefTitle,
                                  bc.getBuildParams().cflags,
                                  bc.getBuildParams().prepDefines,
                                  "N/A" )
    ## TODO: place this in CTXCompiler where it belongs when the spaghetti code is gone
    ## changing working directory to .ctx/obj/[BUILDCONFIGNAME]
    dest_wd = os.path.join(obj_dir, bc.getTitle())
    try:
        os.makedirs(dest_wd)
    except:
        pass
    old_path = os.path.abspath('')
    os.chdir(dest_wd)

    deleteModuleSources = set()
 
    # Process components
    components = create_components( components, cview.getItemPaths('comp'), obj_dir, launch_path )
    infoMessage("Building components...", 1)
    allmods = set()
    for comp in components:
        for library, modules in comp.libraries.items():
            mods = expand_list_files( cview, modules )
            depmgr.addCodeModules( mods, args.tests )
            allmods |= set(modules)

    depMods = depmgr.getModuleDependencies(allmods)
    depmgr.emptyCodeModules()
    if len(depMods - set(allmods))  > 0:
        for module in depMods - set(allmods):
            warningMessage('The module \"'+module+'\" was not specified to be built in any specified .comp file, but at least one of its headers were included in another module, linker errors may arise')

    for comp in components:
        ctx_log.ctxlogBeginComponent( comp.name )

        lib_dir = os.path.join( lib_output, args.libdir )
        header_dir = os.path.join( lib_output, args.headerdir )

        # Build component modules.
        for library, modules in comp.libraries.items():
            modules = expand_list_files( cview, modules )

            depmgr.addCodeModules( modules, args.tests )

            args.lib = library
            infoMessage('args: %s'%args,  6)
            buildmodules( depmgr, session,  modules,  args, lib_dir, session.bc.getTitle(),  libraryName = args.lib)
            if args.deletesources == True:
                for module in modules:
                    modPath = depmgr.resolveCodeModulePath(module)
                    deleteModuleSources.add(modPath)

            depmgr.emptyCodeModules()

        export_headers( depmgr, comp.publicHeaders, header_dir, cview )

        ctx_log.ctxlogEndComponent()

    # Write log if requested
    if args.logfile != None:
        logfilepath = os.path.join( lib_output, args.logfile )
        logpath     = os.path.normpath(os.path.dirname( logfilepath ))
        if len(logpath) and not os.path.isdir(logpath):
            os.makedirs( logpath )

        ctx_log.ctxlogWriteToFile( logfilepath, appendToExisting=False )
    os.chdir(old_path)

    # Restore environment
    if args.env != None:
        switchEnvironment( oldEnv, False )

    if args.deletesources == True:
        modPath = depmgr.resolveCodeModulePath(module)
        for modpath in deleteModuleSources:
            try:
                srcdir = os.path.join(modpath, 'src')
                shutil.rmtree(srcdir)
                infoMessage("Removing source directory: " + srcdir, 1)
            except:
                pass
            try:
                incdir = os.path.join(modpath, 'inc')
                shutil.rmtree(incdir)
                infoMessage("Removing private include directory: " + incdir, 1)
            except:
                pass
            try:
                testdir = os.path.join(modpath, 'test')
                shutil.rmtree(testdir)
                infoMessage("Removing test source directory: " + testdir, 1)
            except:
                pass

def get_view_dir( args_view):
    caller_dir = os.path.abspath('.')
    view_dir = os.path.abspath(args_view)
    os.chdir(view_dir)
    view_dir = os.path.abspath('')
    while not dir_has_rspec(view_dir):
        os.chdir('..')
        if view_dir == os.path.abspath(''):
            userErrorExit('ctx could not find an rspec in the supplied argument or any subdirectory')
        view_dir = os.path.abspath('')
    return view_dir
 
def cmd_build(args):
    launch_path = os.path.abspath('.')

    view_dir = get_view_dir(args.view)
    obj_dir = view_dir + os.sep + '.ctx/obj'
    # test if not absolute path
    if args.output[0] != '/' and args.output[0] != '\\' and args.output[1:3] != ':\\':
        lib_output = os.path.join(view_dir,args.output)
    else:
        lib_output = args.output

    lib_dirs = map(os.path.abspath, args.libdirs)

    from contexo import ctx_cmod
    from contexo import ctx_base
    from contexo import ctx_envswitch
    from contexo.ctx_depmgr import CTXDepMgr
    from contexo.ctx_export import CTXExportData

    envLayout = None
    oldEnv = None
    if args.env != None:
        envLayout = EnvironmentLayout( cfgFile,  args.env )
        oldEnv    = switchEnvironment( envLayout, True )

    absIncDirs = map(os.path.abspath,  args.incdirs)

    # Prepare all
    deprecated_nra_warning( args )
    deprecated_repo_validation_warning(args)
    cview   = ctx_view.CTXView( view_dir, validate=False )
    bc      = getBuildConfiguration( cview,  args )
    bc.buildParams.incPaths.extend(     absIncDirs ) #TODO: accessing 'private' data?
    bc.buildParams.ldDirs.extend(lib_dirs)
    bc.buildParams.ldLibs.extend(args.libs)
    archPath = list()
    archPath = bc.getArchPath()
    deprecated_tolerate_missing_headers_warning(args)
    depmgr = CTXDepMgr ( codeModulePaths = cview.getItemPaths('modules'), failOnMissingHeaders = args.fail_on_missing_headers, archPath = bc.getArchPath(), additionalIncDirs = absIncDirs, legacyCompilingMod = args.legacy_compiling_mod, legacyDuplicateSources = args.legacy_duplicate_sources, globalOutputDir = obj_dir, bc = bc  )
    session = ctx_base.CTXBuildSession( bc )
    session.setDependencyManager( depmgr )

    items = expand_list_files( cview, args.items )

    # Make sure we have only one type of item to export
    #TODO:make a more robust recognition than file extention for .comp
    component_build = True
    for item in items:
        if item.endswith( '.comp' ):
            if component_build == False:
                userErrorExit("The operation can either work on a list of components OR a list of modules, not both.")
        else:
            component_build = False

   # Register build configuration in log handler
    ctx_log.ctxlogSetBuildConfig( bc.getTitle(),
                                  bc.getCompiler().cdefTitle,
                                  bc.getBuildParams().cflags,
                                  bc.getBuildParams().prepDefines,
                                  "N/A" )
    outputPath = lib_output
    bin_dir = os.path.join( outputPath, args.bindir )
    header_dir = os.path.join( outputPath, args.headerdir )
    objs = list()
    ## TODO: place this in CTXCompiler where it belongs when the spaghetti code is gone
    ## changing working directory to .ctx/obj/[BUILDCONFIGNAME]
    dest_wd = os.path.join(obj_dir, bc.getTitle())
    try:
        os.makedirs(dest_wd)
    except:
        pass
    old_path = os.path.abspath('')
    os.chdir(dest_wd)
 
    # Process components
    if component_build:
        infoMessage("Building components...",  1)
        components = create_components( items, cview.getItemPaths('comp'), obj_dir, launch_path )

        allmods = set()
        for comp in components:
            for library, modules in comp.libraries.items():
                mods = expand_list_files( cview, modules )
                depmgr.addCodeModules( mods, args.tests )
                allmods |= set(modules)

        depMods = depmgr.getModuleDependencies(allmods)
        depmgr.emptyCodeModules()
        if len(depMods - set(allmods))  > 0:
            for module in depMods - set(allmods):
                warningMessage('The module \"'+module+'\" was not specified to be built in any specified .comp file, but at least one of its headers were included in another module, linker errors may arise')

        for comp in components:
            ctx_log.ctxlogBeginComponent( comp.name )

            # Build component modules.
            for library, modules in comp.libraries.items():
                modules = expand_list_files( cview, modules )
                depmgr.addCodeModules( modules, args.tests )
                args.library_name = library
                infoMessage('args: %s'%args,  6)
                objs += buildmodules( depmgr, session,  modules,  args, bin_dir, session.bc.getTitle(),  args.library_name)

                if (args.all_headers):
                    header_path = os.path.join(lib_output, args.headerdir )
                    export_public_module_headers( depmgr, modules, header_path )

                depmgr.emptyCodeModules()
            export_headers( depmgr, comp.publicHeaders, header_dir, cview )
            ctx_log.ctxlogEndComponent()

    #Process modules
    else:
        infoMessage("Building modules...",  1)
        depmgr.addCodeModules( items, args.tests )

        if args.deps:
            print >>sys.stderr, "Dependencies for:",
            print >>sys.stderr, items
            print >>sys.stderr, depmgr.getCodeModulesWithDependencies()
        objs += buildmodules( depmgr, session, items, args, outputPath, bc.getTitle(),  libraryName=args.library_name)
        export_public_module_headers( depmgr, items, header_dir )

    if args.executable_name:
            session.linkExecutable(objs, bin_dir, args.executable_name)

    # Write log if requested
    if args.logfile != None:
        logfilepath = os.path.join( lib_output, args.logfile )
        logpath     = os.path.normpath(os.path.dirname( logfilepath ))
        if len(logpath) and not os.path.isdir(logpath):
            os.makedirs( logpath )

        ctx_log.ctxlogWriteToFile( logfilepath, appendToExisting=False )

    os.chdir(old_path)

    # Restore environment
    if args.env != None:
        switchEnvironment( oldEnv, False )


#------------------------------------------------------------------------------
def cmd_export(args):
    launch_path = os.path.abspath('.')
    view_dir = get_view_dir(args.view)
    obj_dir = view_dir + os.sep + '.ctx/obj'
    from contexo import ctx_cmod
    from contexo import ctx_base
    from contexo import ctx_envswitch
    from contexo.ctx_depmgr import CTXDepMgr
    from contexo.ctx_export import CTXExportData

    envLayout = None
    oldEnv = None
    if args.env != None:
        envLayout = EnvironmentLayout( cfgFile,  args.env )
        oldEnv    = switchEnvironment( envLayout, True )

    # Prepare all
    deprecated_nra_warning(args)
    deprecated_repo_validation_warning(args)
    cview   = ctx_view.CTXView( view_dir, validate=False )
    bc      = getBuildConfiguration( cview,  args )
    deprecated_tolerate_missing_headers_warning(args)
    depmgr  = CTXDepMgr ( codeModulePaths = cview.getItemPaths('modules'), failOnMissingHeaders = args.fail_on_missing_headers, legacyDuplicateSources = args.legacy_duplicate_sources, archPath = bc.getArchPath(), globalOutputDir = obj_dir, bc = bc  )
    session = ctx_base.CTXBuildSession( bc )
    session.setDependencyManager( depmgr )

    export_items = expand_list_files( cview, args.export_items )

    # Make sure we have only one type of item to export
    component_export = True
    for item in export_items:
        if item.endswith( '.comp' ):
            if component_export == False:
                userErrorExit("An export operation can either export a list of components OR a list of modules, not both.")
        else:
            component_export = False

    components   = list()
    main_modules = list() # Excluding dependency modules
    if component_export:
        # Construct and validate component objects
        components = create_components( export_items, cview.getItemPaths('comp'), obj_dir, launch_path )
        for comp in components:
            for library, compmodules in comp.libraries.items():
                depmgr.addCodeModules( compmodules, args.tests )
                main_modules.extend( compmodules )
    else:
        main_modules = export_items

    # Divert modules into main modules and dependency modules
    export_modules = depmgr.getCodeModulesWithDependencies() if args.deps else main_modules
    export_modules.sort()
    dep_modules = set(export_modules) - set(main_modules)

    ctx_modules = depmgr.createCodeModules( main_modules, args.tests )
    ctx_modules.extend ( depmgr.createCodeModules( dep_modules ) )

    module_map = dict()
    for mod in ctx_modules:
        module_map[mod.getName()] = mod

    depmgr.updateDependencyHash()

    # Dispatch export data to handler (through pipe)
    package = CTXExportData()
    package.setExportData( module_map, components, args.tests, session, depmgr,
                           cview, envLayout, args )
    package.dispatch()

    # Restore environment
    if args.env != None:
        switchEnvironment( oldEnv, False )

#------------------------------------------------------------------------------
def cmd_updateview(args):

    if args.updates_only == True and args.checkouts_only == True:
        userErrorExit("Options '--updates_only' and '--checkouts-only' are mutually exclusive.")
    deprecated_nra_warning(args)
    view_dir = get_view_dir(args.view)

    cview = ctx_view.CTXView( view_dir, updating=True, validate=True )

    if args.checkouts_only == False:
        cview.updateRepositories()

    if args.updates_only == False:
        cview.checkoutRepositories()

#------------------------------------------------------------------------------
def cmd_validateview(args):

    # The view will validate itself in the constructor
    deprecated_nra_warning(args)
    view_dir = get_view_dir(args.view)
    cview = ctx_view.CTXView( view_dir, validate=True )

    infoMessage("Validation complete", 1)

#------------------------------------------------------------------------------
def cmd_freeze(args):
    view_dir = get_view_dir(args.view)

    import xml.sax
    import sys
    #from  contexo.ctx_rspec_file_freeze import rspecFileRevisionFreezer

    fileOut = sys.stdout
    deprecated_nra_warning(args)
    deprecated_repo_validation_warning(args)
    cview = ctx_view.CTXView( view_dir, validate=False )
    if args.output is not None:
        fileOut = open(args.output,  mode = 'wt')
    cview.freeze(output=fileOut)

#------------------------------------------------------------------------------
def cmd_clean(args):
    view_dir = get_view_dir(args.view)
    obj_dir = view_dir + os.sep + '.ctx/obj'
    if args.all == True:
       import shutil
       try:
           shutil.rmtree(obj_dir)
           infoMessage("All objects successfully removed.")
       except:
           warningMessage("No objects removed.")
           pass

###############################################################################
# ENTRY POINT


# Create Parser
parser = ArgumentParser( prog="ctx",
                         description=ctx_sysinfo.CTX_BANNER,
                         version=ctx_sysinfo.CTX_DISPLAYVERSION,
                         fromfile_prefix_chars='@' )

subparsers = parser.add_subparsers ()

standard_description = dict({\
    '--bconf': "Build configuration file (*.bc/*.bconf)",\
      '--env': "One or more enviroment replacement files (*.env)",\
   '--output': "The location (path) in which to place output files",\
   '--libdir': "Relative directory within '--output' in which to place built binaries. Will be created if not already present.",\
'--headerdir': "Directory name within '--output' in which to place exported header files. Will be created if not already present.",\
     '--deps': "If specified, all dependencies (modules) are processed as well.",\
    '--tests': "If specified, the unit tests for each processed code module are included as well.",\
     '--view': "The local view directory to use for this operation. If omitted, current working directory is used.",\
  '--logfile': "Name of logfile to generate. Will be created in output folder as defined by the --output option.",\
'--repo-validation': "DEPRECATED: validation is only performed by the subcommands 'ctx freeze', 'ctx view', and 'ctx validate'",\
'--no-remote-repo-access': "DEPRECATED: this option is ignored. remote access will always be performed when running ctx view update. At all other times: .rspecs will be cached.",\
'--force':"Forces building all source files", \
'--fail-on-missing-headers':"Abort the build if a header is missing.",\
'--legacy-compiling-mod':"Enables legacy COMPILING_MOD_<MODULENAME> preprocessor defines which may be needed to build code which relied on this previous behaviour (in Contexo 0.8.0 and earlier).", \
'--legacy-duplicate-sources':"Continue the build process even if duplicate build sources has been found in order to build legacy code.",\
'--tolerate-missing-headers':"DEPRECATED: print a message about missing headers and go on, relying on the pre-processor to resolve the problem"})

# info parser
parser_info = subparsers.add_parser('info', help="DEPRECATED: info is no longer supported")
parser_info.set_defaults(func=cmd_info)
parser_info.add_argument('module', nargs=1, help="DEPRECATED")
parser_info.add_argument('-v', '--view', default=os.getcwd(), help="DEPRECATED")

# buildmod parser
parser_build = subparsers.add_parser('buildmod', help="build contexo modules." )
parser_build.set_defaults(func=cmd_buildmod)
parser_build.add_argument('modules', nargs='+', help="list of modules to build" )
parser_build.add_argument('-b', '--bconf', help=standard_description['--bconf'] )
parser_build.add_argument('-e', '--env', help=standard_description['--env'] )
parser_build.add_argument('-o', '--output', default=os.getcwd(), help=standard_description['--output'])
parser_build.add_argument('-ld','--libdir', default="", help=standard_description['--libdir'])
parser_build.add_argument('-hd','--headerdir', default="", help=standard_description['--headerdir'])
parser_build.add_argument('-l', '--lib', help="if the build operation results in a single library, this option sets its name")
parser_build.add_argument('-d', '--deps', action='store_true', help=standard_description['--deps'])
parser_build.add_argument('-t', '--tests', action='store_true', help=standard_description['--tests'])
parser_build.add_argument('-v', '--view', default=os.getcwd(), help=standard_description['--view'])
parser_build.add_argument('-lf', '--logfile', default=None, help=standard_description['--logfile'])
parser_build.add_argument('-rv', '--repo-validation', action='store_true', help=standard_description['--repo-validation'])
parser_build.add_argument('-nra', '--no-remote-repo-access', action='store_true', help=standard_description['--no-remote-repo-access'])
parser_build.add_argument('-f', '--force', action='store_true', help=standard_description['--force'])
parser_build.add_argument('--legacy-compiling-mod', action='store_true', help=standard_description['--legacy-compiling-mod'])
parser_build.add_argument('--legacy-duplicate-sources', action='store_true', help=standard_description['--legacy-duplicate-sources'])
parser_build.add_argument('--tolerate-missing-headers',  action='store_true',  help = standard_description['--tolerate-missing-headers'])
parser_build.add_argument('--fail-on-missing-headers',  action='store_true',  help = standard_description['--fail-on-missing-headers'])


# buildcomp parser
parser_build = subparsers.add_parser('buildcomp', help="build contexo components.")
parser_build.set_defaults(func=cmd_buildcomp)
parser_build.add_argument('components', nargs='+', help="list of components to build")
parser_build.add_argument('-b', '--bconf', help=standard_description['--bconf'])
parser_build.add_argument('-e', '--env', help=standard_description['--env'])
parser_build.add_argument('-o', '--output', default=os.getcwd(), help=standard_description['--output'])
parser_build.add_argument('-ld','--libdir', default="", help=standard_description['--libdir'])
parser_build.add_argument('-delete', '--deletesources', action='store_true', help="Delete private headers and the src and test dir of compiled modules.")
parser_build.add_argument('-hd','--headerdir', default="", help=standard_description['--headerdir'])
parser_build.add_argument('-d', '--deps', action='store_true', help=standard_description['--deps'])
parser_build.add_argument('-t', '--tests', action='store_true', help=standard_description['--tests'])
parser_build.add_argument('-v', '--view', default=os.getcwd(), help=standard_description['--view'])
parser_build.add_argument('-lf', '--logfile', default=None, help=standard_description['--logfile'])
parser_build.add_argument('-I',  '--incdirs', nargs='*',  default = [],  help = "additional include paths")
parser_build.add_argument('-rv', '--repo-validation', action='store_true', help=standard_description['--repo-validation'])
parser_build.add_argument('-nra', '--no-remote-repo-access', action='store_true', help=standard_description['--no-remote-repo-access'])
parser_build.add_argument('-f', '--force', action='store_true', help=standard_description['--force'])
parser_build.add_argument('--legacy-compiling-mod', action='store_true', help=standard_description['--legacy-compiling-mod'])
parser_build.add_argument('--legacy-duplicate-sources', action='store_true', help=standard_description['--legacy-duplicate-sources'])
parser_build.add_argument('--tolerate-missing-headers',  action='store_true',  help = standard_description['--tolerate-missing-headers'])
parser_build.add_argument('--fail-on-missing-headers',  action='store_true',  help = standard_description['--fail-on-missing-headers'])


# build parser
parser_build = subparsers.add_parser('build', help="build contexo components or modules, linking them into an executable..")
parser_build.set_defaults(func=cmd_build)
parser_build.add_argument('items', nargs='+', help="list of components to build")
parser_build.add_argument('-b', '--bconf', help=standard_description['--bconf'])
parser_build.add_argument('-e', '--env', help=standard_description['--env'])
parser_build.add_argument('-o', '--output', default=os.getcwd(), help=standard_description['--output'])
parser_build.add_argument('-bd','--bindir', default="", help=standard_description['--libdir'])
parser_build.add_argument('-hd','--headerdir', default="", help=standard_description['--headerdir'])
parser_build.add_argument('-d', '--deps', action='store_true', help=standard_description['--deps'])
parser_build.add_argument('-t', '--tests', action='store_true', help=standard_description['--tests'])
parser_build.add_argument('-v', '--view', default=os.getcwd(), help=standard_description['--view'])
parser_build.add_argument('-lf', '--logfile', default=None, help=standard_description['--logfile'])
parser_build.add_argument('-rv', '--repo-validation', action='store_true', help=standard_description['--repo-validation'])
parser_build.add_argument('-nra', '--no-remote-repo-access', action='store_true', help=standard_description['--no-remote-repo-access'])
parser_build.add_argument('-f', '--force', action='store_true', help=standard_description['--force'])
parser_build.add_argument('--legacy-compiling-mod', action='store_true', help=standard_description['--legacy-compiling-mod'])
parser_build.add_argument('--legacy-duplicate-sources', action='store_true', help=standard_description['--legacy-duplicate-sources'])
parser_build.add_argument('--tolerate-missing-headers',  action='store_true',  help = standard_description['--tolerate-missing-headers'])
parser_build.add_argument('--fail-on-missing-headers',  action='store_true',  help = standard_description['--fail-on-missing-headers'])
parser_build.add_argument('--all-headers', action='store_true', help = "export all public headers")
parser_build.add_argument('-lib', '--library-name', help="(modules) build a single library, with the given name")
parser_build.add_argument('-I',  '--incdirs', nargs='*',  default = [],  help = "additional include paths")
parser_build.add_argument('-exe', '--executable-name',  help = 'link the elements into a single executable')
parser_build.add_argument('-L',  '--libdirs', nargs='*',  default = [],  help = "(linking) directories to search for libs")
parser_build.add_argument('-l',  '--libs', nargs='*',  default = [],  help = "(linking) libraries to link in")


# clean parser
parser_clean = subparsers.add_parser('clean', help="DISABLED: clean a module(s) ( and optionaly its dependencies)")
parser_clean.set_defaults(func=cmd_clean)
parser_clean.add_argument('-a', '--all', action='store_true', help='clean all object files')
# parser_clean.add_argument('modules', nargs='+', help="DISABLED: list of modules to clean")
parser_clean.add_argument('-d', '--deps', action='store_true', help=standard_description['--deps'])
parser_clean.add_argument('-b', '--bconf', help="DISABLED: only clean target files produced from this build configuration.")
parser_clean.add_argument('-t', '--tests', action='store_true', help=standard_description['--tests'])
parser_clean.add_argument('-v', '--view', default=os.getcwd(), help=standard_description['--view'])
parser_clean.add_argument('-rv', '--repo-validation', action='store_true', help=standard_description['--repo-validation'])
parser_clean.add_argument('-nra', '--no-remote-repo-access', action='store_true', help=standard_description['--no-remote-repo-access'])
parser_clean.add_argument('--tolerate-missing-headers',  action='store_true',  help = standard_description['--tolerate-missing-headers'])
parser_clean.add_argument('--fail-on-missing-headers',  action='store_true',  help = standard_description['--fail-on-missing-headers'])

# freeze parser
parser_freeze = subparsers.add_parser('freeze', help="Generate a rspec with either svn revisions or git sha1s frozen in their current state (from working copy).")
parser_freeze.set_defaults(func=cmd_freeze)
#parser_freeze.add_argument('--file',  help="rspec to freeze. Imports will not be frozen")
parser_freeze.add_argument('-o', '--output',  help="file to write to (standard output is used by default)")
parser_freeze.add_argument('-v', '--view', default=os.getcwd(), help=standard_description['--view'])
parser_freeze.add_argument('-nra', '--no-remote-repo-access', action='store_true', help=standard_description['--no-remote-repo-access'])#
parser_freeze.add_argument('-rv', '--repo-validation', action='store_true', help=standard_description['--repo-validation'])
#parser_build.add_argument('--tolerate-missing-headers',  action='store_true',  help = standard_description['--tolerate-missing-headers'])

# export parser
#


export_usage = """

-- USAGE NOTES ------------------------------------------------------

The export command is a plugin interface to Contexo which utilizes
the 'pipe' mechanism to communicate build session data.
Example, exporting to the 'msvc' plugin:

ctx export my.comp -bc my.bc | msvc -pn my_vcproj_title -o out_folder

Instead of building, Contexo transfers the build session data to the
MSVC plugin which in turn renders a Visual Studio project from the
information.

To invoke commandline help for a certain plugin, use the help option
for both ctx and the plugin:

ctx export --help | msvc --help

---------------------------------------------------------------------
"""

parser_export = subparsers.add_parser('export', help="Export utilities.")
parser_export.set_defaults(func=cmd_export)
parser_export.formatter_class = internal_argparse.RawDescriptionHelpFormatter
parser_export.description = export_usage
parser_export.add_argument('export_items', nargs='*', default="", help="List of items to export. Can be omitted if the export plugin doesn't require any items. Code modules and components cannot be mixed in the same export operation.")
parser_export.add_argument('-b', '--bconf', help=standard_description['--bconf'])
parser_export.add_argument('-e', '--env', help=standard_description['--env'])
parser_export.add_argument('-v', '--view', default=os.getcwd(), help=standard_description['--view'])
parser_export.add_argument('-d', '--deps', action='store_true', help=standard_description['--deps'])
parser_export.add_argument('-t', '--tests', action='store_true', help=standard_description['--tests'])
parser_export.add_argument('-rv', '--repo-validation', action='store_true', help=standard_description['--repo-validation'])
parser_export.add_argument('-nra', '--no-remote-repo-access', action='store_true', help=standard_description['--no-remote-repo-access'])
parser_export.add_argument('--tolerate-missing-headers',  action='store_true',  help = standard_description['--tolerate-missing-headers'])
parser_export.add_argument('--fail-on-missing-headers',  action='store_true',  help = standard_description['--fail-on-missing-headers'])
parser_export.add_argument('--legacy-duplicate-sources', action='store_true', help=standard_description['--legacy-duplicate-sources'])

#
#

parser_view = subparsers.add_parser( 'view', help="View operations" )
view_subparsers = parser_view.add_subparsers()

parser_view_update = view_subparsers.add_parser('update', help="Update/synchronize a view")
parser_view_update.set_defaults(func=cmd_updateview)
parser_view_update.add_argument('view', nargs='?', default=os.getcwd(), help="Relative or absolute path to a view directory. If omitted, current working directory is used.")
parser_view_update.add_argument('-co', '--checkouts-only', action='store_true', help="Checkout missing repositories only. Don't update existing repositories.")
parser_view_update.add_argument('-uo', '--updates-only', action='store_true', help="Update existing repositories only. Don't checkout missing repositories.")
parser_view_update.add_argument('-nra', '--no-remote-repo-access', action='store_true', help="DEPRECATED: will emit a warning..")

parser_view_validate = view_subparsers.add_parser('validate', help="Validate consistency of view structure")
parser_view_validate.set_defaults(func=cmd_validateview)
parser_view_validate.add_argument('view', nargs='?', default=os.getcwd(), help="Relative or absolute path to a view directory. If omitted, current working directory is used.")
parser_view_validate.add_argument('-nra', '--no-remote-repo-access', action='store_true', help="DEPRECATED: will emit a warning.")

###############################################################################

# Parse cmdline
argsa=parser.parse_args()
argsa.func(argsa)
infoMessage("Contexo " + ctx_sysinfo.CTX_DISPLAYVERSION + " finished successfully.", 1)

