#!/usr/bin/python
from contexo import ctx_view
from contexo import ctx_depmgr
from contexo import ctx_cmod
import os
import shutil
def rewrite_source(view, depmgr, file):
    f = open( file ) # Open for reading
    f_new = open( file + '.tmp',"w" )
    lines = f.readlines()   # Read in the contents
    for line in lines:
        if line.startswith("#include"):
            pos1 = line.find('"') +1
            pos2 = line.find('"',line.find('"')+1)
            if pos1 * pos2 > 0:
                orig_header = line[pos1:pos2]
                header = os.path.basename(orig_header)
                new_header_path = orig_header
                header_path = depmgr.locate(header)
                if header_path != None:
                    max_length = -1
                    for header_cand in view.getItemPaths('modules'):
                        if len(header_cand) < len(os.path.dirname(os.path.abspath(header_path))):
                            if header_cand == header_path[:len(header_cand)] and len(header_cand) > max_length:
                                new_header_path = header_path[len(header_cand)+1:]
                                max_length = len(header_cand)

                f_new.write('#include "'+new_header_path+'"\n')
            else:
                f_new.write(line)
        else:
            f_new.write(line)
    f_new.close()
    f.close() # Close the file
    shutil.move(file + '.tmp', file)

source_extensions = ['.cpp','.h','.c','.cpp','.inl']

view = ctx_view.CTXView( os.path.abspath(''), validate=False )
depmgr = ctx_depmgr.CTXDepMgr ( codeModulePaths = view.getItemPaths('modules'))


sources = set() 

for module_path in view.getItemPaths('modules'):
    for name in os.listdir(module_path):
        module = module_path + os.sep + name
        if not os.path.isdir(module):
            print 'not ' + module

        if ctx_cmod.isContexoCodeModule(module):
            print module
            depmgr.addCodeModules( os.path.basename(module), unitTests=True )

for module_path in view.getItemPaths('modules'):
    directories = [module_path]
    while len(directories)>0:
        directory = directories.pop()
        for name in os.listdir(directory):
            item = os.path.join(directory,name)
            if os.path.isfile(item):
                if item[item.rfind('.'):] in source_extensions:
                    sources.add(item)
            elif os.path.isdir(item):
                directories.append(item)

depmgr.updateDependencyHash()
for sourcefile in sources:
    print sourcefile
    rewrite_source(view, depmgr, sourcefile)
