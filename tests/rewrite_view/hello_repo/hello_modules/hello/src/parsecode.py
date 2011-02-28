import os
import sys
f = open( sys.argv[1] ) # Open for reading
#f_mod = open( sys.argv[1] + '.new.c )
lines = f.readlines()   # Read in the contents
for line in lines:
    if line.startswith("#include"):
        pos1 = line.find('"') +1
        pos2 = line.find('"',line.find('"')+1)
        if pos1 * pos2 > -1:
            header = os.path.basename(line[pos1:pos2])
            print header
        else:
            print line
    else:
        print line

f.close()                     # Close the file
