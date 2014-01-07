import makerbot_driver
from machine     import BurijjiMachine
from time        import sleep
from collections import deque
import threading

class mbWrapper(BurijjiMachine):

    def __init__(self, server):
        super(mbWrapper, self).__init__(server)
        factory               = makerbot_driver.MachineFactory()
        self.__printer        = factory.build_from_port(self._server.port)
        self.__parser         = getattr(self.__printer, 'gcodeparser')
        self.__command_queue  = deque()
        self.__command_mutex  = threading.Lock()
        heated_bed            = len(self.__printer.profile.values['heated_platforms']) > 0
        self._machine_info    = {'type': 'MakerBot', 'model':  self.__printer.profile.name, 'extruder_count': len(self.__printer.profile.values['tools']), 'heated_bed': heated_bed}
        self._print_data      = None

    def _update(self):
        printer = self.__printer

        while self._server.running:
            sleep(1)
            temps = {}

            try:
                if self._machine_info['extruder_count'] is 1:
                    temps['t'] = float(printer.s3g.get_toolhead_temperature(0))
                else:
                    for i in xrange(self._machine_info['extruder_count']):
                        temps['t'+str(i)] = float(printer.s3g.get_toolhead_temperature(i))

                if self._machine_info['heated_bed']:
                    temps['b'] = float(printer.s3g.get_platform_temperature(0))
            except:
                pass

            self._mutex.acquire()
            self._temperatures.update(temps)
            self._mutex.release()

    def _send_commands(self, commands):
        if self._printing:
            self.__command_mutex.acquire()
            for command in commands:
                self.__command_queue.append(command)
            self.__command_mutex.release()
        else:
            for command in commands:
                self._send_command(command)

    def _print_file(self, data):
        build_name = data.split('/')[-1].split('.')[0]
        self.__parser.state.values['build_name'] = build_name[:15]
        threading.Thread(target=self._do_print, args=[data]).start()

    def _do_print(self, data):
        self._printing         = True
        if not self._paused:
            self._current_line = 0
            self._print_data   = deque([i.strip() for i in open(data)])

        self._exec_command_queue()

        while self._printing and len(self._print_data) and not self._paused:
            self._exec_command_queue()
            if not self._printing: break
            self._send_command(self._print_data.popleft())
            self._current_line += 1

        self._exec_command_queue()

        if not self._paused:
            self._stop_print()
            self._current_line = None
            self._print_data   = None
            if 'end_print' in self._routines: self._send_commands(self._routines['end_print'])

    def _stop_print(self):
        self._printing = False
        if len(self._print_data): self.__printer.s3g.build_end_notification()

    def _cancel_print(self):
        self._printing = False
        try:
            for i in xrange(self._machine_info['extruder_count']): self.__printer.s3g.set_toolhead_temperature(tool_index=i,temperature=0)
            if self._machine_info['heated_bed']: self.__printer.s3g.set_platform_temperature(tool_index=0,temperature=0)
        except: pass
        self._mutex.acquire()
        info_subscribers = self._info_subscribers
        self._mutex.release()
        for fileno in info_subscribers: self._server.add_to_queue(fileno, {'action': 'print_cancelled', 'data': {}})

    def _pause_print(self):
        self._printing = False
        self._paused   = True

    def _resume_print(self):
        self._printing = True
        threading.Thread(target=self._do_print, args=(False)).start()

    def _exec_command_queue(self):
        self.__command_mutex.acquire()
        while len(self.__command_queue):
            self._send_command(self.__command_queue.popleft())
        self.__command_mutex.release()

    def _send_command(self, command):
        while True:
            try:
                self.__parser.execute_line(command)
                break
            except(makerbot_driver.BufferOverflowError, makerbot_driver.TransmissionError):
                sleep(0.2)
            except (makerbot_driver.BuildCancelledError, makerbot_driver.ActiveBuildError):
                self._cancel_print()
                break
