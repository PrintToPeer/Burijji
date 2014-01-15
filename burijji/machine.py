import threading
from time import sleep
from collections import deque

class BurijjiMachine(object):
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
        self._machine_info     = {}
        self._routines         = {}
        self._port_info        = {'vid': self._server.vid, 'pid': self._server.pid, 'iserial': self._server.iserial}

    def start(self):
        threading.Thread(target=self._update).start()
        threading.Thread(target=self._run).start()

    def _update(self):
        raise NotImplementedError()

    def _run(self):
        while self._server.running:
            sleep(1)

            self._mutex.acquire()
            temp_msg         = {'action': 'temperature', 'data': self._temperatures}
            info_msg         = {'action': 'info', 'data': {'current_line': self._current_line, 'printing': self._printing, 'paused': self._paused, 'port_info': self._port_info, 'machine_info': self._machine_info}}
            temp_subscribers = self._temp_subscribers
            info_subscribers = self._info_subscribers
            self._mutex.release()

            for fileno in temp_subscribers: self._server.add_to_queue(fileno, temp_msg)
            for fileno in info_subscribers: self._server.add_to_queue(fileno, info_msg)

    def machine_info(self):
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

        if 'start_print' in self._routines: self._send_commands(self._routines['start_print'])
        self._print_file(data)

    def stop_print(self, fileno, data):
        self._stop_print()

    def pause_print(self, fileno, data):
        if self._printing:
            self._pause_print()
            if 'pause' in self._routines: self._send_commands(self._routines['pause_print'])

    def resume_print(self, fileno, data):
        if self._paused:
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

    def subscribe(self, fileno, data):
        subscription = data['type']
        if subscription not in ['temperature','info','all']:
            return(self._server.add_to_queue(fileno, {'action': 'data_error', 'data': 'Invalid subscription type.'}))

        self._mutex.acquire()
        if subscription is 'temperature':
            self._temp_subscribers.append(fileno)
        elif subscription is 'info':
            self._info_subscribers.append(fileno)
        elif subscription is 'raw':
            self._raw_subscribers.append(fileno)
        else:
            self._temp_subscribers.append(fileno)
            self._info_subscribers.append(fileno)
        self._mutex.release()

    def unsubscribe(self, fileno, data):
        subscription = data['type']
        if subscription not in ['temperature','info','all']:
            return(self._server.add_to_queue(fileno, {'action': 'data_error', 'data': 'Invalid subscription type.'}))

        self._mutex.acquire()
        if subscription is 'temperature':
            try:
                self._temp_subscribers.remove(fileno)
            except:
                pass
        elif subscription is 'info':
            try:
                self._info_subscribers.remove(fileno)
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
        self._mutex.release()

    def bad_data_sent(self, fileno):
        self._server.add_to_queue(fileno, {'action': 'data_error', 'data': 'Malformed data.'})

    def _send_commands(self, data):
        raise NotImplementedError()

    def _print_file(self, data):
        raise NotImplementedError()

    def _pause_print(self):
        raise NotImplementedError()