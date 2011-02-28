#!/usr/bin/python
import os
import sys

f = open( sys.argv[1] ) # Open for reading
f_new = open( sys.argv[1]+'.tmp',"w" )
lines = f.readlines()   # Read in the contents
for line in lines:
    if line.startswith("#include"):
        pos1 = line.find('"') +1
        pos2 = line.find('"',line.find('"')+1)
        if pos1 * pos2 > 0:
            orig_header = line[pos1:pos2]
            header = os.path.basename(orig_header)
            f_new.write('#include "'+header+'"\n')
        else:
            f_new.write(line)
    else:
        f_new.write(line)
f_new.close()
f.close()
shutil.move(sys.argv[1]+'.tmp', sys.argv[1])



