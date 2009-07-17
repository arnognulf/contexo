#! /usr/bin/env python

import sys
from argparse import ArgumentParser
from contexo.ctx_export import *
from contexo.ctx_common import *
import contexo.ctx_bc
import contexo.ctx_cmod
import contexo.ctx_msvc

msgSender = 'MSVC Export'

default_projname = "MSVC_EXPORT"


#------------------------------------------------------------------------------
def create_module_mapping_from_module_list( ctx_module_list ):

    code_module_map = list()

    for mod in ctx_module_list:
        srcFiles = list()
        privHdrs = list()
        pubHdrs  = list()

        rawMod = mod #ctx_cmod.CTXRawCodeModule( mod )

        srcNames = rawMod.getSourceFilenames()
        for srcName in srcNames:
            srcFiles.append( os.path.join( rawMod.getSourceDir(), srcName ) )

        privHdrNames = rawMod.getPrivHeaderFilenames()
        for privHdrName in privHdrNames:
            privHdrs.append( os.path.join( rawMod.getPrivHeaderDir(), privHdrName ) )

        pubHdrNames = rawMod.getPubHeaderFilenames()
        for pubHdrName in pubHdrNames:
            pubHdrs.append( os.path.join( rawMod.getPubHeaderDir(), pubHdrName ) )


        modDict = { 'MODNAME': rawMod.getName(), 'SOURCES': srcFiles, 'PRIVHDRS': privHdrs, 'PUBHDRS': pubHdrs, 'PRIVHDRDIR': rawMod.getPrivHeaderDir() }
        code_module_map.append( modDict )
    
    return code_module_map
    
#------------------------------------------------------------------------------
def allComponentModules( component_list ):
    
    modules = list()
    for comp in component_list:
        for lib, libmods in comp.libraries.iteritems():
            modules.extend( libmods )

    return modules
        
#------------------------------------------------------------------------------
def cmd_parse( args ):

    infoMessage( "Receiving export data from Contexo...", 1, msgSender )
    package = CTXExportData()
    package.receive() # Reads pickled export data from stdin
    
    infoMessage( "Received export data:", 4, msgSender )
    for item in package.export_data.keys():
        infoMessage( "%s: %s"%(item, str(package.export_data[item])), 4 ) 
    
    # Retrieve build config from session
    bc_file =  package.export_data['SESSION'].getBCFile()
    build_params = bc_file.getBuildParams()

    debugmode = bool( not args.release )
    
    #
    # Add module paths/repositories as include directories
    #
    
    modTags     = list()
    incPaths    = list()
    depRoots    = package.export_data['PATHS']['MODULES']
    for depRoot in depRoots:
        incPathCandidates = os.listdir( depRoot )
        for cand in incPathCandidates:
            path = os.path.join(depRoot, cand)
            if contexo.ctx_cmod.isContexoCodeModule( path ):
                rawMod = contexo.ctx_cmod.CTXRawCodeModule(path)
                incPaths.append( path )
                
                # Only include private headers for projects containing the specified module
                #incPaths.append( os.path.join(rawMod.getRootPath(), rawMod.getPrivHeaderDir()) )
                
                modTags.append( 'COMPILING_MOD_' + string.upper( rawMod.getName() ) )

    #
    # Collect additional include paths    
    #
    
    user_includepaths = list()
    if args.additional_includes != None:
        filename = args.additional_includes
        if not os.path.exists( filename ):
            userErrorExit( "Cannot find option file '%s'"%filename, msgSender )
        file = open( filename, "r" )
        for line in file.readlines():
            line = line.strip( " \n\r" )
            user_includepaths += line.split(";")
        file.close()
        user_includepaths = filter(lambda x: x.strip(" ") != '',user_includepaths)
        incPaths += user_includepaths

    #
    # Determin if we're exporting components or modules, and do some related 
    # sanity checks
    #

    comp_export = bool( package.export_data['COMPONENTS'] != None )
    
    if comp_export:
    #Exporting components
    
        if args.mirror_components == True and args.project_name != None:
            warningMessage( "Ignoring option --project-name (-pn) when option --mirror-components (-mc) is used", msgSender )
            args.project_name = None    
    else:
    # Exporting modules
        
        if args.mirror_components == True:
            warningMessage( "Ignoring option --mirror-components (-mc) when exporting modules", msgSender )    
            args.mirror_components = False

        if package.export_data['MODULES'] == None:
            userErrorExit( "No components or modules specified for export.", msgSender )
                
    
    project_name = args.project_name
    if project_name == None and args.mirror_components == False:
        project_name = default_projname
        
    
    # strip vcproj extension if user included it.
    if project_name != None and project_name[ -7: ].lower() == '.vcproj':
        project_name = project_name[0:-7]


    #
    # If exporting components and the user specified --mirror-components we 
    # create one vcproj per component library, otherwise we create one large 
    # library of all code modules.
    #
    
    vcprojList = list() # list of dict['PROJNAME':string, 'LIBNAME':string, 'MODULELIST':listof( see doc of make_libvcproj7 ) ]

    # Regardless if we export components or modules, all modules are located in export_data['MODULES']
    module_map = create_module_mapping_from_module_list( package.export_data['MODULES'].values() )
    
    if comp_export and args.mirror_components:
        for comp in package.export_data['COMPONENTS']:
            for library, modules in comp.libraries.iteritems():
                lib_modules = [ mod for mod in module_map if mod['MODNAME'] in modules  ]
                vcprojList.append( { 'PROJNAME': library, 'LIBNAME': library, 'MODULELIST': lib_modules } )

    else: # Module export OR component export without mirroring component structure
        vcprojList.append( {'PROJNAME': project_name, 'LIBNAME': project_name, 'MODULELIST': module_map } )


    #
    # Generate the projects
    #
    
    if not os.path.exists( args.output ):
        os.makedirs( args.output )

    
    guidDict = dict()
    for proj in vcprojList:
        guidDict[proj['PROJNAME']] = contexo.ctx_msvc.make_libvcproj8( proj['PROJNAME'],
                                                                       build_params.cflags,
                                                                       build_params.prepDefines + modTags,
                                                                       proj['MODULELIST'],
                                                                       proj['LIBNAME'] + '.lib',
                                                                       debugmode, 
                                                                       incPaths, 
                                                                       args.output,
                                                                       args.platform,
                                                                       proj['PROJNAME'])
    
    #
    # Handle external project if specified
    #
    
    external_vcproj = None
    
    if args.external_vcproj != None:
        external_vcproj = contexo.ctx_msvc.get_info_vcproj8( os.path.abspath( args.external_vcproj ) )
        external_vcproj['DEBUG'] = debugmode
        attrs = list()
        attrs.append(   dict({ "DEBUG":debugmode, 
                                "TOOL":"VCCLCompilerTool",
                                 "KEY":"AdditionalIncludeDirectories",
                               "VALUE":";".join(incPaths) }))
                               
        contexo.ctx_msvc.update_vcproj8(external_vcproj['FILENAME'],attrs)
    
    #
    # Create solution if specified
    #
    
    if args.solution != None:
    
        slnProjects = list()
        for proj in vcprojList:
            slnProjects.append( { 'PROJNAME': proj['PROJNAME'], 'PROJGUID': guidDict[proj['PROJNAME']], 'DEBUG': debugmode } )
    
        contexo.ctx_msvc.make_solution8( args.solution, args.output, slnProjects, external_vcproj, args.platform )


    #
    # The End
    #
    infoMessage( "Export done.", 1, msgSender )

    
##### ENTRY POINT #############################################################

# Create Parser
parser = ArgumentParser( description="""MSVC project export - 
 plugin to Contexo Build System (c) 2006-2009 Scalado AB""", 
 version="0.1")

parser.set_defaults(func=cmd_parse)

parser.add_argument('-vcver', '--vcversion', default='8',
 help="Resulting export will comply to this major version of MSVC. Supported versions: 8" )

parser.add_argument('-pn', '--project-name', default=None,
 help="""Used as the title and filename for the resulting project. If the 
 export operation generates multiple projects, this parameter will be ignored.
 If omitted, default name '%s' will be used."""%default_projname )

parser.add_argument('-sln', '--solution', default=None, 
 help="""Name of solution file (*.sln). If specified, all projects generated 
 during the export are bundled into a solution with this name.""")

parser.add_argument('-mc', '--mirror-components', action='store_true', 
 help="""If specified, the export will mirror the exact distribution of 
 libraries from any included components, resulting in one VS project for each 
 library within the components. The name of each library will be used as both 
 project name and output library name. If this option is omitted, one VS project 
 will be created including all sourcefiles from all components. In this case the 
 --project-name option sets the name of the project.""")

parser.add_argument('-r', '--release', action='store_true', 
 help="""If specified, the resulting VS projects will be set to release mode. 
 Otherwise debug mode is used. Note that this option does not affect any 
 potential debugging parameters introduced by the build configuration specified 
 with the -b or --bconf option""")

parser.add_argument('-ev', '--external-vcproj', default=None,
 help="""Specifies the path to an external VS project. If this option is used, 
 all include paths added to the generated project(s) will also be added to the 
 external project. Additionally, if the --solution option is used, the external
 project is added to the resulting solution and set to depend on all other projects
 generated in the export.""")

parser.add_argument('-ai', '--additional-includes', default=None,
 help="""Path to a file with include paths to append to the include directories 
 of all VS projects generated. The paths in the file can be separated by line 
 or by semicolon.""")

parser.add_argument('-pl', '--platform', default='Win32',
 help="""If specified, the resulting VS projects will use
 the specified platform. Default is "Win32". Note that this option does not affect 
 any settings introduced by the build configuration specified with the -b or 
 --bconf option.""")

parser.add_argument('-o', '--output', default=os.getcwd(), 
 help="The output directory for the export.")

#parser.add_argument('-ld','--libdir', default="", help=standard_description['--libdir'])
#parser.add_argument('-l', '--lib', help="if the build operation results in a single library, this option sets its name")

args = parser.parse_args()
args.func(args)
