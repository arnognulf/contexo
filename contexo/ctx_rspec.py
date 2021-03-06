###############################################################################
#                                                                             #
#   ctx_rspec.py                                                              #
#   Component of Contexo Shell - (c) Scalado AB 2007                          #
#                                                                             #
#   Author:                                                                   #
#   Manuel Astudillo ( manuel.astudillo@scalado.com)                          #
#   ------------                                                              #
#                                                                             #
#   RSpec Classes.                                                            #
#                                                                             #
#   Support:                                                                  #
#                                                                             #
#   20080519 - RSpec format version 0.1                                       #
#                                                                             #
###############################################################################

from xml.sax            import  make_parser
from xml.sax.handler    import  ContentHandler

from ctx_repo_svn       import *
from ctx_repo_git       import *
from ctx_repo_fs        import *
from ctx_common         import userErrorExit, warningMessage, infoMessage
from ctx_common         import getVerboseLevel, ctxAssert, getUserTempDir
import ctx_repo
import os.path
import shutil
#------------------------------------------------------------------------------
class LIFOStack( list ):
    def __init__ (self):
        self.push = lambda e: self.append(e)
        self.peek = lambda: self[ len(self)-1 ] if len(self) else None

#------------------------------------------------------------------------------
def createRepoFromRCS( rcs, id, path, href, rev ):

    rcs = rcs.lower() if rcs != None else None

    if rcs == 'svn':
        return CTXRepositorySVN( id, path, href, rev )
    elif rcs == 'git':
        return CTXRepositoryGIT( id, path, href, rev )
    elif rcs == None or rcs =='':
        return CTXRepositoryFS( id, path, href, rev )
    else:
        userErrorExit("Unsupported RCS for repository '%s'"%(id))

#------------------------------------------------------------------------------
class rspecXmlHandler(ContentHandler):
    def __init__ (self, rspecFile=str(),view=None):
        self.rspecFile = rspecFile
        self.default_version = "1"
        self.current_repo = None
        self.id_list = list()
        self.view = view
        self.parent_element = LIFOStack()
        self.msgSender = "rspecXmlHandler"

    #--------------------------------------------------------------------------
    def startElement(self, name, attrs):

        # .....................................................................
        if name == 'ctx-rspec':
            if self.parent_element.peek() != None:
                userErrorExit("'<ctx-rspec>' can only be used as root element")

        # .....................................................................
        elif name == 'ctx-import':
            # Make sure this element is used in correct context
            if self.parent_element.peek() != 'ctx-rspec':
                userErrorExit("'%s' elements can only be used within '%s' elements"%(name, 'ctx-rspec'))

            #
            # Digest import and check for errors/inconsistencies
            #

            href = attrs.get('href', None)
            if href == None:
                userErrorExit("<ctx-import>: Missing mandatory attribute '%s' in RSpec '%s'"%('href', self.rspecFile.getFilename()))

            rcs = attrs.get('rcs', None)
            if rcs == None and attrs.has_key('rev'):
                userErrorExit("<ctx-import>: Revision ('rev') specified without specifying 'rcs' in RSpec '%s'"%(self.rspecFile.getFilename()))

            rev = attrs.get('rev', None )
            if rcs != None and rev == None:
                warningMessage("<ctx-import>: No revision specified for import in RSpec '%s'. Assuming 'HEAD'"%(self.rspecFile.getFilename()))
                rev = 'HEAD'

            # Prepare locator object and add import to current RSpec
            rspecFileLocator = RSpecFileLocator( rcs=rcs, href=href, revision=rev, updating = False, wipe_cache=False, view=self.view )
            self.rspecFile.addImport( rspecFileLocator ) # POINT OF RECURSION

        # .....................................................................
        elif name == 'ctx-repo':

            # Make sure this element is used in correct context
            if self.parent_element.peek() != 'ctx-rspec':
                userErrorExit("'%s' elements can only be used within '%s' elements"%(name, 'ctx-rspec'))

            # Make sure 'id' attribute is unique within RSpec
            if attrs.has_key('id'):
                if attrs.get('id') in self.id_list:
                    userErrorExit("Multiple occurances of id '%s' in '%s'"%(attrs.get('id'), self.rspecFile.getFilename()))
                else:
                    self.id_list.append(attrs.get('id'))

            self.current_repo = createRepoFromRCS( attrs.get('rcs', None),
                                                   attrs.get('id', ""),
                                                   attrs.get('path', ""),
                                                   attrs.get('href', ""),
                                                   attrs.get('rev', ""))
            self.rspecFile.addRepository ( self.current_repo )

        # .....................................................................
        elif name == 'ctx-path':

           # Make sure this element is used in correct context
            if self.parent_element.peek() not in ['ctx-repo',]:
                userErrorExit("'<%s>' elements cannot be used within '<%s>' elements"%(name, self.parent_element.peek()))

            #
            # Assure presence of mandatory attributes
            #

            attribute = 'type'
            if not attrs.has_key(attribute):
                userErrorExit("Missing mandatory attribute '%s' in element '<%s>'"%(attribute, name))

            attribute = 'spec'
            if not attrs.has_key(attribute):
                userErrorExit("Missing mandatory attribute '%s' in element '<%s>'"%(attribute, name))

            ctx_path_type = attrs.get( 'type' ).lower()
            self.current_repo.addPath( ctx_path_type, attrs.get('spec').replace('\\','/') )

        # .....................................................................
        else:
            warningMessage("Ignoring unknown element '<%s>' in RSpec '%s'.\nThis might be a normal compatibility issue."%(name, self.rspecFile.getFilename()))

        self.parent_element.push( name )


    #--------------------------------------------------------------------------
    def endElement(self, name):
        self.parent_element.pop()

        if name == 'ctx-rspec':
            pass
        elif name == 'ctx-import':
            pass
        elif name == 'ctx-repo':
            self.current_repo = None
        elif name == 'ctx-path':
            pass

        #depending on what is the current state,
        #put the character in the correct bin
        def characters (self, ch):
            warningMessage("Ignoring character data '%s' found in element '%s'"%(ch, self.parent_element.peek()))

#------------------------------------------------------------------------------
class RSpecFileLocator:
    def __init__(self, rcs=None, href=None, revision=None, updating = False, wipe_cache=False, view = None ):
        self.rcs = rcs
        self.href = href
        if type(self.href) != type(str()) and type(self.href) != type(u''):
            self.href = href.getHref()
        # is the rspec path absolute or network path?
        if self.href[0:7] == 'file://' or self.href[0:6] == 'svn://' or self.href[0:8] == 'https://' or self.href[0:7] == 'http://' or self.href[0] == '/' or self.href[0:1] == '\\' or self.href[1:3] == ':\\':
            pass
        else:
            self.href = os.path.normpath(view.getRoot() + os.sep + self.href)

        self.revision = revision
        self.updating = updating
        self.rspec_cache_dir = view.getRoot() + os.sep + '.ctx' + os.sep + 'rspec-cache' + os.sep
        if wipe_cache == True and updating == True and os.path.exists(self.rspec_cache_dir):
             shutil.rmtree(self.rspec_cache_dir)
        self.msgSender = 'RSpecFileLocator'

    #--------------------------------------------------------------------------
    # Returns a guaranteed local path to the RSpec file. The returned path might
    # be temporary and should not be stored for later access. The path is
    # guaranteed to be available during the entire build session.
    #--------------------------------------------------------------------------
    def getLocalAccessPath(self):
        # TODO: wipe cache if root element and first export ok
        src = str()

        local_access_path = os.path.join( self.rspec_cache_dir, os.path.basename(self.getHref()))
        if not os.path.exists(self.rspec_cache_dir):
            os.makedirs(self.rspec_cache_dir)
 
        if self.rcs == None:
            if not os.path.exists( local_access_path ):
                infoMessage("No RCS specified for RSpec '%s', attempting regular file access"\
                         %(self.getHref()), 4)
                if not os.path.exists(self.href):
                    userErrorExit("RSpec unreachable with regular file access: \n  %s"%(self.href))
                shutil.copyfile( self.getHref(), local_access_path )
            # access the local rspec if accessable
            # otherwise the user may be confused why changes in a locally modified would not be applied.
            if os.path.exists(self.href):
                local_access_path = self.getHref()

        else:
            if self.updating == True or not os.path.exists( local_access_path ):
                temp_dir = getUserTempDir()
                rspec_name = os.path.basename(self.getHref())
                temp_rspec = os.path.join( temp_dir, rspec_name )

                infoMessage("Downloading (svn-exporting) RSpec from '%s' to '%s' using RCS '%s'"\
                         %(str(self.getHref()), str(temp_rspec), str(self.rcs)), 1)

                if os.path.exists(temp_rspec):
                    os.remove( temp_rspec )

                # rspec access is still handled by svn
                if self.rcs == 'svn' or self.rcs == 'git':

                    svn = ctx_svn_client.CTXSubversionClient()
                    # does this fail if rspec cannot be fetched?
                    svn.export( self.getHref(), temp_dir, self.revision )
                    if not os.path.exists( os.path.join(temp_dir, os.path.basename(self.getHref()))):
                        userErrorExit("RSpec unreachable with remote Subversion access: \n  %s"%(self.getHref()))

                else:
                    userErrorExit("Unsupported RCS: %s"%(self.rcs))
                src = os.path.join( temp_dir, rspec_name)
                shutil.copyfile( src, local_access_path )

        infoMessage("RSpec local access path resolved to: %s"\
                     %(local_access_path), 4)

        return local_access_path

    #--------------------------------------------------------------------------
    def getHref(self):
        return str(self.href)

#------------------------------------------------------------------------------
class RSpecFile:
    def __init__(self, rspec_file=None, parent=None, view=str(), wipe_cache=False ):
        self.repositories       = dict()
        self.rspecFileLocator   = None
        self.imports            = list() # List of RSpecFile objects, note the recursion.
        self.view               = view
        self.msgSender          = 'RSpecFile'
        self.wipe_cache         = wipe_cache
        #---
 
        if type(rspec_file) is str:
            self.wipe_cache = True
            self.rspecFileLocator = RSpecFileLocator( rcs=None, href=rspec_file, revision=None, updating=view.updating, wipe_cache=True, view=self.view )
        else:
            self.rspecFileLocator = rspec_file

        _wipe_cache=False
        if parent == None:
            _wipe_cache=True
        # self.rspecFileLocator = RSpecFileLocator( rcs=None, href=rspec_file, revision=None, updating=view.updating, wipe_cache=_wipe_cache, view=self.view )

        localPath = self.rspecFileLocator.getLocalAccessPath()

        parser = make_parser()
        handler = rspecXmlHandler(self, view=view)
        parser.setContentHandler(handler)
        parser.parse( open(localPath) ) # POINT OF RECURSION

        if parent == None:

            if getVerboseLevel() > 1:
                self.printRSpecHierarchy()

            # This is the root RSpec. At this point all imported RSpecs
            # has been processed recursively and we now have a tree of
            # RSpecFile objects, starting with this one.
            #
            # Now we need to traverse the tree and flatten all RSpecs into
            # one, also applying rules for override and presedence.
            self.processImports() # POINT OF RECURSION

        #self.filename = os.path.basename(rspecFilename) ??

    #--------------------------------------------------------------------------
    def getFilename(self):
        return os.path.basename( self.getFilePath() )

    #--------------------------------------------------------------------------
    def getFilePath(self):
        return self.rspecFileLocator.getLocalAccessPath()

    #--------------------------------------------------------------------------
    def addImport( self, rspecFileLocator ):
        self.imports.append( RSpecFile(rspecFileLocator, self, self.view) )

    #--------------------------------------------------------------------------
    # Returns all imports as a list of RSpecFile objects.
    #--------------------------------------------------------------------------
    def getImports( self ):
        return self.imports

    #--------------------------------------------------------------------------
    # Returns a list of paths to all imported RSpec files.
    #--------------------------------------------------------------------------
    def getImportPaths( self, recursive = True ):
        import_paths = list()

        for rspec in self.getImports():
            if recursive:
                import_paths.extend( rspec.getImportPaths(recursive) ) # POINT OF RECURSION

            import_paths.append( rspec.getFilePath() )

        return import_paths

    #--------------------------------------------------------------------------
    # Returns a list of filenames of all imported RSpec files.
    #--------------------------------------------------------------------------
    def getImportFilenames( self, recursive = True ):
        import_filenames = list()

        for rspec in self.getImports():
            if recursive:
                import_filenames.extend( rspec.getImportFilenames(recursive) ) # POINT OF RECURSION

            import_filenames.append( rspec.getFilename() )

        return import_filenames

    #--------------------------------------------------------------------------
    def addRepository(self, repository):
        self.repositories[repository.id_name] = repository
        repository.setViewRoot( self.view.getRoot() )

    #--------------------------------------------------------------------------

    def getRepositories(self):
        return self.repositories.values()

    #--------------------------------------------------------------------------
    def getRepoPaths( self, path_section ):
        ctxAssert( path_section in ctx_repo.REPO_PATH_SECTIONS, "Unknown path section '%s'"%(path_section) )
        paths = list()
        for repo in self.getRepositories():
            paths.extend( repo.getFullPaths( path_section ) )

        return paths

    #--------------------------------------------------------------------------
    def delRepository(self, name):
        if not name in self.repositories:
            print >>sys.stderr, "repository %s not found", name
        del self.repositories[name]

    #--------------------------------------------------------------------------
    def processImports( self ):

        # Import rules
        #
        # - In the case of multiple imports, duplicate data is overridden
        #   by the successing import. This rule is implied by the iteration
        #   order of the imports list.
        #
        # - Repositories from an imported RSpec are overriden/discarded by any
        #   repository in the importing RSpec, if they share the same ID. IDs
        #   are case insensitive.
        #
        # - Import instructions are not inherited/imported. An import is regarded
        #   as obsolete once it has been processed.
        #

        for rspec in self.imports:

            # First let the imported rspec process its own imports.
            rspec.processImports() # POINT OF RECURSION

            # Generate repository ID record
            existing_repo_ids = list()
            for r in self.getRepositories():
                existing_repo_ids.append( r.getID() )

            # Add all repositories from the imported RSpec, but skip those
            # with IDs we already have (override).
            for r in rspec.getRepositories():
                if r.getID() not in existing_repo_ids:
                    self.addRepository( r )
                else:
                    infoMessage("Repository '%s' in '%s' overridden by repository '%s' in '%s'"\
                                 %(r.getID(), rspec.rspecFileLocator.getHref(), r.getID(), self.rspecFileLocator.getHref()), 1)

        # All imports processed, so they can be discarded.
        # COMMENTED OUT, it's probably useful to have the structure intact for later analysis
        # self.imports = list()

    #--------------------------------------------------------------------------
    def printRSpecHierarchy(self, level=0):
        import sys
        if level == 0:
            sys.stderr.write( "\n--- RSpec hierarchy -----------------\n");

        sys.stderr.write( '   '*level,); sys.stderr.write('\n')
        sys.stderr.write( '[ctx-rspec: ' + self.rspecFileLocator.getHref() + ']'); sys.stderr.write('\n')

        for r in self.getRepositories():
            sys.stderr.write( '   '*level,);
            sys.stderr.write( ' ',);
            sys.stderr.write( '[ctx-repo: ' + r.getID() + ']'); sys.stderr.write('\n')
            for section in REPO_PATH_SECTIONS:
                for p in r.getFullPaths( section ):
                    sys.stderr.write( '   '*level,);
                    sys.stderr.write( '   ',);
                    sys.stderr.write( "[ctx-path type='%s': %s]"%(section, p)); sys.stderr.write('\n')

        sys.stderr.write( '\n');

        for i in self.imports:
            i.printRSpecHierarchy( level + 1 ) # POINT OF RECURSION

        if level == 0:
            sys.stderr.write( "\n------------------------------------"); sys.stderr.write('\n')
