from printrun.printcore     import printcore
from printrun               import gcoder
from machine                import BurijjiMachine
from time                   import sleep
import re

class repWrapper(BurijjiMachine):
    _temp_exp = re.compile("([TB]\d*):([-+]?\d*\.?\d*)")

    def __init__(self, server):
        super(repWrapper, self).__init__(server)
        self.__printer     = printcore()
        self._machine_info = {'type': 'RepRap', 'model':  'Unknown'}

    def _update(self):
        printer        = self.__printer
        printer.recvcb = self._parse_line
        printer.connect(self._server.port, self._server.baud)

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
        gcoder.GCode([i.strip() for i in open(data)])
        self.__printer.startprint(gcode)

    def _pause_print(self):
        self.__printer.pause()

    def _reumse_print(self):
        self.__printer.resume()

    def _parse_line(self, line):
        matches = self._temp_exp.findall(line)
        temps   = dict((m[0], float(m[1])) for m in matches)

        self._mutex.acquire()
        self._temperatures.update(temps)
        self._mutex.release()