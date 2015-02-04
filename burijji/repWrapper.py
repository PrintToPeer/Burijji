from printrun.printcore     import printcore
from printrun               import gcoder
from time                   import sleep
from collections            import deque
import threading
import re

import sys

def log(message):
  print message
  sys.stdout.flush()

class repWrapper:
    _temp_exp = re.compile("([TB]\d*):([-+]?\d*\.?\d*)")
    _uuid_exp = re.compile("UUID:([0-F]{8}-[0-F]{4}-4[0-F]{3}-[89AB][0-F]{3}-[0-F]{12})", re.I)

    def __init__(self, server):
        self._server           = server
        self._mutex            = threading.Lock()
        self._temp_subscribers = []
        self._info_subscribers = []
        self._raw_subscribers  = []
        self._temperatures     = {}
        self._current_line     = None
        self._printing         = False
        self._paused           = False
        self._ok               = True
        self._machine_info     = {}
        self._routines         = {}
        self._raw_output       = deque()
        self._other_messages   = deque()
        self.__printer         = printcore()
        self._machine_info     = {'type': 'RepRap', 'model':  'Unknown', 'uuid': None}
        self._current_segment  = 'none'
        self._gcode_file       = None

        self.__printer.errorcb = self.errorcb
        self.__printer.sendcb = self.sendcb
        self.printer_lock = threading.Lock()

    def errorcb(self, error):
        log("* Error: " + error.strip())

    def sendcb(self, command):
        log("> " + command.strip())

    def start(self):
        threading.Thread(target=self._update).start()
        threading.Thread(target=self._run).start()

    def _run(self):
        while self._server.running:
            sleep(1)

            self._mutex.acquire()
            temp_msg         = {'action': 'temperature', 'data': self._temperatures}
            info_msg         = {'action': 'info', 'data': {'current_line': self._current_line, 'printing': self._printing, 'paused': self._paused, 'machine_info': self._machine_info, 'current_segment': self._current_segment}}
            temp_subscribers = self._temp_subscribers
            info_subscribers = self._info_subscribers
            raw_subscribers  = self._raw_subscribers
            ok               = self._ok
            raw_output       = list(self._raw_output)
            other_messages   = list(self._other_messages)
            self._raw_output.clear()
            self._other_messages.clear()

            log("- status ok? " + str(ok) + " __printer p:" + str(self.__printer.printing) + " ol:" + str(self.__printer.online) + " c:" + str(self.__printer.clear))

            self._mutex.release()

            if not self._ok:
              print "burijji: disconnected"
              other_messages.append({'action': 'disconnected'})

            for fileno in temp_subscribers: self._server.add_to_queue(fileno, temp_msg)
            for fileno in info_subscribers:
                self._server.add_to_queue(fileno, info_msg)
                for message in other_messages:
                    self._server.add_to_queue(fileno, message)
            for fileno in raw_subscribers:
                for line in raw_output:
                    self._server.add_to_queue(fileno, {'action': 'raw', 'data': line})

            if not self._ok:
              self._server.stop()

    def _update(self):
        printer        = self.__printer
        printer.recvcb = self._parse_line
        printer.endcb  = self._advance_segment
        printer.connect(self._server.port, self._server.baud)
        sleep(1)

        with self.printer_lock:
            printer.send_now('M115')


        while self._server.running:
            sleep(1)
            with self.printer_lock:
                printer.send_now('M105')
            self._mutex.acquire()
            self._current_line = printer.queueindex
            self._printing     = printer.printing
            self._paused       = printer.paused
            self._ok           = (printer.writefailures < 10)
            self._mutex.release()

        with self.printer_lock:
            self.__printer.disconnect()

    def machine_info(self, fileno, data):
        self._server.add_to_queue(fileno, {'action': 'machine_info', 'data': self._machine_info})

    def send_commands(self, fileno, data):
        if type(data) is list:
            self._send_commands(data)
        else:
            self.bad_data_sent(fileno)

    def print_file(self, fileno, data):
        self._mutex.acquire()
        if fileno not in self._info_subscribers: self._info_subscribers.append(fileno)
        self._mutex.release()

        self.add_other_message({'action': 'print_started', 'data': ''})
        self._gcode_file = data
        self._advance_segment()

    def stop_print(self, fileno, data):
        self._stop_print()
        self.add_other_message({'action': 'print_stopped', 'data': ''})

    def pause_print(self, fileno, data):
        if self._printing:
            self._pause_print()
            if 'pause_print' in self._routines: self._send_commands(self._routines['pause_print'])
            self.add_other_message({'action': 'print_paused', 'data': ''})

    def print_complete(self):
        self._current_segment  = 'none'
        self.add_other_message({'action': 'print_complete', 'data': ''})

    def resume_print(self, fileno, data):
        if self._paused:
            self.add_other_message({'action': 'print_resumed', 'data': ''})
            if 'resume' in self._routines: self._send_commands(self._routines['resume_print'])
            self._resume_print()

    def run_routine(self, fileno, data):
        if data in self._routines:
            self._send_commands(self._routines[data])
        else: self._server.add_to_queue(fileno, {'action': 'routine_error', 'data': 'routine not defined'})

    def update_routines(self, fileno, data):
        if type(data) is dict:
            for key,val in data.iteritems():
                if type(val) is not list: return(self.bad_data_sent(fileno))
            self._routines.update(data)
        else:
            self.bad_data_sent(fileno)

    def add_other_message(self, message):
        self._mutex.acquire()
        self._other_messages.append(message)
        self._mutex.release()

    def subscribe(self, fileno, data):
        subscription = data['type']
        if subscription not in ['temperature','info','raw','all']:
            return(self._server.add_to_queue(fileno, {'action': 'data_error', 'data': 'Invalid subscription type.'}))

        self._mutex.acquire()
        if subscription == 'temperature':
            self._temp_subscribers.append(fileno)
        elif subscription == 'info':
            self._info_subscribers.append(fileno)
        elif subscription == 'raw':
            self._raw_subscribers.append(fileno)
        elif subscription == 'all':
            self._temp_subscribers.append(fileno)
            self._info_subscribers.append(fileno)
            self._raw_subscribers.append(fileno)
        self._mutex.release()

    def unsubscribe(self, fileno, data):
        subscription = data['type']
        if subscription not in ['temperature','info','raw','all']:
            return(self._server.add_to_queue(fileno, {'action': 'data_error', 'data': 'Invalid subscription type.'}))

        self._mutex.acquire()
        if subscription == 'temperature':
            try:
                self._temp_subscribers.remove(fileno)
            except:
                pass
        elif subscription == 'info':
            try:
                self._info_subscribers.remove(fileno)
            except:
                pass
        elif subscription == 'raw':
            try:
                self._raw_subscribers.remove(fileno)
            except:
                pass
        else:
            try:
                self._temp_subscribers.remove(fileno)
            except:
                pass
            try:
                self._info_subscribers.remove(fileno)
            except:
                pass
            try:
                self._raw_subscribers.remove(fileno)
            except:
                pass
        self._mutex.release()

    def bad_data_sent(self, fileno):
        self._server.add_to_queue(fileno, {'action': 'data_error', 'data': 'Malformed data.'})

    def _send_commands(self, commands):
        with self.printer_lock:
            for command in commands:
                self.__printer.send_now(command)

    def _advance_segment(self):
        log("* Advance Segment c: " + self._current_segment)
        if self._current_segment == 'none':
            self._current_segment = 'starting'
            if 'start_print' in self._routines:
                threading.Thread(target=self._delayed_start, args=[self._routines['start_print']]).start()
            else:
                self._advance_segment()

        elif self._current_segment == 'starting':
            self._current_segment = 'printing'
            threading.Thread(target=self._delayed_start, args=[[i.strip() for i in open(self._gcode_file)]]).start()
            self.add_other_message({'action': 'segment_completed', 'data': 'start_segment'})

        elif self._current_segment == 'printing':
            self._current_segment = 'ending'
            if 'end_print' in self._routines:
                threading.Thread(target=self._delayed_start, args=[self._routines['end_print']]).start()
            else:
                self._advance_segment()
            self.add_other_message({'action': 'segment_completed', 'data': 'print_segment'})

        elif self._current_segment == 'ending':
            self.print_complete()
            self._current_segment = 'none'
            self.add_other_message({'action': 'segment_completed', 'data': 'end_segment'})

    def _delayed_start(self, data):
        sleep(0.1)
        gcode = gcoder.GCode(data)
        self.__printer.endcb  = self._advance_segment

        log("* Delayed start c: " + str(self.__printer.clear))
        
        print_started = False
        while True:
            with self.printer_lock:
                log("* startprint attempt c: " + str(self.__printer.clear))
                print_started = self.__printer.startprint(gcode)

            if print_started:
                break

            sleep(0.1)


        log("* Starting print. Total lines: " + str(len(data)))
        log("* Clear: " + str(self.__printer.clear))
        log("* GCode Sample:")
        lines = 0
        for line in data:
          log("* ==> " + line.strip())
          lines += 1
          if lines > 30:
            break

    def _end_print(self):
        if 'cancel_print' in self._routines: self._send_commands(self._routines['cancel_print'])
        self.print_complete()

    def _stop_print(self):
        self._mutex.acquire()
        self.printing = False
        self._mutex.release()

        with self.printer_lock:
            self.__printer.endcb = None
            self.__printer.pause()

        self._mutex.acquire()
        self.printing = False
        self._mutex.release()

        self._end_print()

    def _pause_print(self):
        with self.printer_lock:
            self.__printer.pause()

    def _reumse_print(self):
        with self.printer_lock:
            self.__printer.resume()

    def _parse_line(self, line):
        self._mutex.acquire()
        log("< " + line.strip())
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
