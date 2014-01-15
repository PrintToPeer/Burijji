from printrun.printcore     import printcore
from printrun               import gcoder
from machine                import BurijjiMachine
from time                   import sleep
import re

class repWrapper(BurijjiMachine):
    _temp_exp = re.compile("([TB]\d*):([-+]?\d*\.?\d*)")
    _uuid_exp = re.compile("UUID:([0-F]{8}-[0-F]{4}-4[0-F]{3}-[89AB][0-F]{3}-[0-F]{12})", re.I)

    def __init__(self, server):
        super(repWrapper, self).__init__(server)
        self.__printer     = printcore()
        self._machine_info = {'type': 'RepRap', 'model':  'Unknown', 'uuid': None}

    def _update(self):
        printer        = self.__printer
        printer.recvcb = self._parse_line
        printer.endcb  = self._end_print
        printer.connect(self._server.port, self._server.baud)
        sleep(1)
        printer.send_now('M115')


        while self._server.running:
            sleep(1)
            printer.send_now('M105')
            self._mutex.acquire()
            self._current_line = printer.queueindex
            self._printing     = printer.printing
            self._paused       = printer.paused
            self._mutex.release()

        self.__printer.disconnect()

    def _send_commands(self, commands):
        for command in commands:
            self.__printer.send_now(command)

    def _print_file(self, data):
        gcode = gcoder.GCode([i.strip() for i in open(data)])
        self.__printer.startprint(gcode)

    def _end_print(self):
        if 'end_print' in self._routines: self._send_commands(self._routines['end_print'])

    def _stop_print(self):
        self.__printer.pause()
        self._end_print()

    def _pause_print(self):
        self.__printer.pause()

    def _reumse_print(self):
        self.__printer.resume()

    def _parse_line(self, line):
        self._mutex.acquire()
        self._raw_output.append(line)
        self._mutex.release()

        temp_matches = self._temp_exp.findall(line)
        temps        = dict((m[0].lower(), float(m[1])) for m in temp_matches)
        self._mutex.acquire()
        self._temperatures.update(temps)
        self._mutex.release()

        if 'FIRMWARE' in line:
            firmware_name  = line.split('FIRMWARE_NAME:')[1].split(';')[0]
            machine_type   = line.split('MACHINE_TYPE:')[1].split()[0]
            extruder_count = int(line.split('EXTRUDER_COUNT:')[1].split()[0])

            uuid_match = self._uuid_exp.findall(line.lower())
            if len(uuid_match): uuid = uuid_match[0]
            else:               uuid = None

            info_dict = {'firmware_name': firmware_name, 'machine_type': machine_type, 'extruder_count': extruder_count, 'uuid': uuid}
            
            self._mutex.acquire()
            self._machine_info.update(info_dict)
            self._mutex.release()