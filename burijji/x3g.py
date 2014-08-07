
import Queue
import os
import threading
import time
import subprocess
import sys

class X3GPrinter:
  def __init__(self, baud, port):
    self.baud = baud
    self.port = port

    self.lock = threading.Lock()
    self.running = True
    self.on_receive = self._null_on_receive
    self.on_complete = self._null_on_complete
    self.gpx = None
    self.ok = True
    self.ready = False

    self.commands_to_send = []
    self.waiting_for_ok = 0

    threading.Thread(target=self._run).start()

  def send_now(self, line):
    with self.lock:
      if self.gpx == None or not self.ready:
        print "send_now not ready"
        return

      try:
        print "send_now", self.waiting_for_ok, len(self.commands_to_send), line
        self.waiting_for_ok += 1
        self.gpx.stdin.write(line + "\n")
      except IOError as io:
        print "X3G / IOError writing '" + str(line.strip()) + "'", io
        self.ok = False
      except Exception as e:
        print "X3G Error", e
        self.ok = False

  def send_many(self, lines):
    with self.lock:
      self.waiting_for_ok = 0
      self.commands_to_send += lines

  def _null_on_receive(self, line):
    print "on_receive:", line

  def _null_on_complete(self):
    print "on_complete"

  def _run(self):
    self.gpx = subprocess.Popen([os.getenv("HOME") + '/Burijji/GPX/gpx', '-i', '-s', '-v', '-r', '-b', str(self.baud), self.port], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    read_queue = Queue.Queue()
    read_thread = threading.Thread(target=self._read_from_gpx, args=(self.gpx.stdout, read_queue))
    read_thread.daemon = True # Don't wait for this to be done on exit
    read_thread.start()

    read_thread = threading.Thread(target=self._read_from_gpx, args=(self.gpx.stderr, read_queue))
    read_thread.daemon = True # Don't wait for this to be done on exit
    read_thread.start()

    time.sleep(3)
    self.ready = True
    print "X3G Ready"

    while self.running:
      try:
        with self.lock:
          read_line = read_queue.get_nowait()
          if read_line.strip() == "ok":
            self.waiting_for_ok -= 1
          if read_line.strip() == "fail":
            self.ok = False

        self.on_receive(read_line)
      except Queue.Empty:
        pass
      except Exception as e:
        print "_run exception", e
        self.ok = False

      if (self.waiting_for_ok < 10) and len(self.commands_to_send) > 0:
        with self.lock:
          command_to_send = self.commands_to_send[0]
          self.commands_to_send = self.commands_to_send[1:]

        self.send_now(command_to_send)

        if len(self.commands_to_send) == 0:
          self.on_complete()

      has_terminated = self.gpx.poll()
      if has_terminated != None:
        self.ok = False


    self.gpx.kill()

  def _read_from_gpx(self, stream, queue):
    for line in iter(stream.readline, b''):
      queue.put(line.strip())
      sys.stdout.flush()

      if not self.running:
        break

    stream.close()

  def end_print(self):
    with self.lock:
      self.commands_to_send = []
      self.waiting_for_ok = 0

  def stop(self):
    self.running = False

if __name__ == "__main__":
  p = X3GPrinter(115200, "/dev/ttyACM0")
  try:
    time.sleep(3)

    print "Sending commands..."
    p.send_many([line.strip() for line in open("../GPX/test.gcode")])

    while True:
      time.sleep(2)
      p.send_now("M105")

      if not p.ok:
        print "Not OK"
        break

  except KeyboardInterrupt:
    p.stop()
