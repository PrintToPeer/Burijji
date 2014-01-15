import os, sys, socket, select, threading, msgpack, serial
import serial.tools.list_ports as lp
from collections import deque
from time        import time
from time        import sleep

class BurijjiServer():
    __epoll_ro = (select.EPOLLIN | select.EPOLLPRI | select.EPOLLHUP | select.EPOLLERR)
    __epoll_rw = __epoll_ro | select.EPOLLOUT

    def __init__(self, port, sock, baud = 115200):
        self.port              = port
        self.baud              = baud
        self.port_name         = self.port.split('/')[-1]

        hw_info                = lp.hwinfo(self.port)
        vid_pid                = hw_info.split('PID=')[1].split()[0]
        self.iserial           = hw_info.split('SNR=')[1]
        self.vid               = vid_pid.split(':')[0]
        self.pid               = vid_pid.split(':')[1]

        self.running           = True
        self.__sock            = sock
        self.__epoll           = select.epoll()
        self.__socketserver    = None
        self.__outbound_queues = {}
        self.__connections     = {}
        self.__unpackers       = {}
        self.__mutex           = threading.Lock()
        self._operations       = ['machine_info', 'send_commands', 'print_file', 'pause_print', 'resume_print']
        self._operations      += ['run_routine', 'update_routines', 'subscribe', 'unsubscribe', 'stop_print']

        if self.vid == '23c1':
            from mbWrapper import mbWrapper
            self.__machine = mbWrapper(self)
        else:
            from repWrapper import repWrapper
            self.__machine = repWrapper(self)

    def start(self):
        threading.Thread(target=self.__run).start()

    def stop(self):
        self.running = False

    def add_to_queue(self, fileno, data):
        try:
            self.__mutex.acquire()
            self.__outbound_queues[fileno].append(data)
        except:
            pass
        finally:
            self.__mutex.release()

    def __run(self):
        self.__machine.start()
        self.__setup_server()

        while self.running:
            sleep(0.01)
            events = self.__epoll.poll(0)
            for fileno, event in events:
                if fileno == self.__socketserver.fileno():
                    if event == select.EPOLLIN:                            self.__setup_connection(self.__socketserver.accept()[0])
                elif event == select.EPOLLOUT:                             self.__send(fileno)
                elif event == select.EPOLLIN  or event == select.EPOLLPRI: self.__recv(fileno)
                elif event == (select.EPOLLIN | select.EPOLLOUT):
                    self.__recv(fileno)
                    self.__send(fileno)
                elif event == (select.EPOLLIN | select.EPOLLHUP):
                    self.__recv(fileno)
                    self.__teardown_connection(fileno)
                elif event == (select.EPOLLIN | select.EPOLLOUT | select.EPOLLHUP):
                    self.__recv(fileno)
                    self.__teardown_connection(fileno)
                elif event == select.EPOLLHUP or event == select.EPOLLERR: self.__teardown_connection(fileno)

        self.__teardown_server()

    def __setup_server(self):
        socketserver = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        socketserver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        socketserver.bind(self.__sock)
        socketserver.listen(5)
        socketserver.setblocking(0)
        self.__epoll.register(socketserver.fileno(), self.__epoll_ro)
        self.__socketserver = socketserver

    def __teardown_server(self):
        for fileno in self.__connections:
            if fileno != self.__socketserver.fileno(): self.__teardown_connection(fileno)
        self.__epoll.unregister(self.__socketserver.fileno())
        self.__epoll.close()
        self.__socketserver.close()
        os.remove(self.__sock)

    def __setup_connection(self, connection):
        connection.setblocking(0)
        fileno = connection.fileno()
        self.__epoll.register(fileno, self.__epoll_ro)
        self.__connections[fileno]     = connection
        self.__unpackers[fileno]       = msgpack.Unpacker()
        self.__outbound_queues[fileno] = deque()
        self.add_to_queue(fileno,{'action': 'server_info', 'data': {'version': '0.3.0', 'pid': os.getpid()}})

    def __teardown_connection(self, fileno):
        try:
            self.__epoll.unregister(fileno)
            self.__connections[fileno].close()
            if self.running:
                self.__machine.unsubscribe(fileno, {'type': 'all'})
                del self.__connections[fileno]
                del self.__unpackers[fileno]
                del self.__outbound_queues[fileno]
        except: pass

    def __send(self, fileno):
        self.__mutex.acquire()
        if len(self.__outbound_queues[fileno]) == 0:
            self.__mutex.release()
            return(None)
        message = self.__outbound_queues[fileno].popleft()
        self.__mutex.release()

        try:
            message = msgpack.packb(message)
            return(self.__connections[fileno].send(message))
        except:
            self.__teardown_connection(fileno)

    def __recv(self, fileno):
        try:
            data     = self.__connections[fileno].recv(1024)
            unpacker = self.__unpackers[fileno]
        except:
            self.__teardown_connection(fileno)
        
        if data:
            self.__epoll.modify(fileno, self.__epoll_rw)
            unpacker.feed(data)
            for pack in unpacker:
                if type(pack) is not dict or 'action' not in pack or 'data' not in pack:
                    self.__machine.bad_data_sent(fileno)
                elif pack['action'] not in self._operations:
                    self.add_to_queue(fileno, {'action': 'action_error', 'data': 'Invalid action.'})
                else:
                    getattr(self.__machine, pack['action'])(fileno, pack['data'])
        else:
            self.__teardown_connection(fileno)