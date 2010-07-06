#!/usr/bin/python
###############################################################################
#                                                                             #
#   git-ctx.py                                                                #
#   Contexo rspec multi repository tool support for the Git toolsuite         #
#                                                       (c) Scalado AB 2010   #
#                                                                             #
#   Author: Thomas Eriksson (thomas.eriksson@scalado.com)                     #
#   License GPL v2. See LICENSE.txt.                                          #
#   ------------                                                              #
#                                                                             #
#                                                                             #
###############################################################################
# coding=UTF-8

import os
import os.path
import sys
from contexo import ctx_repo
from contexo import ctx_rspec
from contexo import ctx_view
def dir_has_rspec(view_dir):
    view_filelist = os.listdir(view_dir)
    for entry in view_filelist:
        if entry.endswith('.rspec'):
            return True
    return False



class GITCtx:
    def __init__( self ):
        self.git = 'git'
        self.git_repos = list()
        self.ignored_repos = list()
        # instead of manually specifying rspec (as is the de facto uage convention
        # with contexo)
        # search backwards in path until an rspec file is found (the de-facto
        # git usage convention)
        self.view_dir = os.path.abspath('')
        while not dir_has_rspec(self.view_dir):
            os.chdir('..')
            self.view_dir = os.path.abspath('')
        ctxview = ctx_view.CTXView(self.view_dir)

        for repo in ctxview.getRSpec().getRepositories():
            if repo.getRcs() == 'git':
                self.git_repos.append(repo.getAbsLocalPath())
            else:
                self.ignored_repos.append(repo.getAbsLocalPath())

    def help( self ):
        print """
git ctx is a component of the Contexo build system which integrates with the git toolsuite.
Any git command supplied to 'git ctx' will be executed for each subrepository in the view as defined by the Contexo .rspec.

usage: git ctx [git-command] [options] [--] <filepattern>...
        """
	sys.exit(42)
    def print_all( self ):

        print self.git_repos
        print self.ignored_repos
        #ctxview.printView()

        #path = os.abs
    def _banner_branch( self ):
        print """	    
# Changed but not updated:
#   (use "git ctx add/rm <file>..." to update what will be committed)
#   (use "git ctx checkout -- <file>..." to discard changes in working directory)
#
        """
    def _banner_untracked( self ):
        print """
# Untracked files:
#   (use "git ctx add <file>..." to include in what will be committed)
        """
    def _postbanner_untracked( self ):
        print """
no changes added to commit (use "git add" and/or "git commit -a")
        """


    def status( self, git_argv ):
	print 'git status'
	statusdict = dict()
	statusdict['M'] = list()
	statusdict['??'] = list()
	statusdict['A'] = list()
	statusdict['U'] = list()
	statusdict['R'] = list()
	statusdict['D'] = list()

	untracked_files = list()
	modified_files = list()
        for repo_path in self.git_repos:
            if not os.path.isdir(repo_path):
                return ''
            os.chdir(repo_path)
            import subprocess
            args = [self.git, 'status', '--porcelain']
            args.extend(git_argv)
            p = subprocess.Popen(args, bufsize=4096, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stderr = p.stderr.read()
            stdout = p.stdout.read()
            retcode = p.wait()

            if retcode != 0:
                print stderr
                errorMessage("GIT execution failed with error code %d"%(retcode))
                exit(retcode)

            os.chdir(self.view_dir)
	    print "# %s is on branch master"
            for line in stdout.split('\n'):
                split_line = line.split()
                if len(split_line) == 2:
		    if statusdict.has_key( split_line[0] ):
		        statusdict[ split_line[0] ].append( repo_path + split_line[1] )
		    else:
		        warningMessage("unknown git status code %s"%(split_line[0]))
        return ''

    def generic( self, git_cmd, git_argv ):
        for repo_path in self.git_repos:
            if not os.path.isdir(repo_path):
                return ''
            os.chdir(repo_path)

            import subprocess
            args = [self.git, git_cmd ]
            args.extend(git_argv)

	    p = subprocess.Popen(args, bufsize=4096, stdin=None)
            retcode = p.wait()

            if retcode != 0:
                errorMessage("GIT execution failed with error code %d"%(retcode))
                exit(retcode)

            os.chdir(self.view_dir)
	sys.exit(retcode)
    

gitctx = GITCtx()

if len(sys.argv) == 0:
    gitctx.help()
    sys.exit(1)
if sys.argv[1] == '-h' or sys.argv[1] == '--help':
    gitctx.help()
    sys.exit(1)
#
git_argv = list(sys.argv[2:])
if sys.argv[1] == 'status':
    gitctx.status(git_argv)
else:
    gitctx.generic(sys.argv[1], git_argv)

