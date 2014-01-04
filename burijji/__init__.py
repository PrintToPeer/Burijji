import os, sys

mb_path = os.path.abspath('./s3g')
serial_path = os.path.abspath('./mb_serial')
printrun_path = os.path.abspath('./Printrun')

sys.path.append(mb_path)
sys.path.append(serial_path)
sys.path.append(printrun_path)