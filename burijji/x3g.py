
import Queue
import os
import threading
import time
import subprocess
import sys
import tempfile

class X3GPrinter:
  def __init__(self, baud, port, settings):
    self.baud = baud
    self.port = port

    self.lock = threading.Lock()
    self.running = True
    self.on_receive = self._null_on_receive
    self.on_complete = self._null_on_complete
    self.gpx = None
    self.ok = True
    self.ready = False
    self.is_sending_many = False

    self.waiting_for_ok = False
    self.commands_to_send = []
    self.print_queue_size = 0

    self.settings = settings

    threading.Thread(target=self._run).start()

  def send_now(self, commands):
    with self.lock:
      if type(commands) is list:
        self.commands_to_send = commands + self.commands_to_send
      else:
        self.commands_to_send.insert(0, commands.strip())

  def send_many(self, lines):
    with self.lock:
      self.print_queue_size = len(lines)
      self.is_sending_many = True
      self.commands_to_send = [l.strip() for l in lines]

  def _create_config_file(self, config):
    config_file = tempfile.mktemp('.ini')
    f = open(config_file, 'w')
    f.write('[machine]\n')
    f.write('nominal_filament_diameter=1.75\n')
    f.write('extruder_count=1\n')
    f.write('timeout=20\n')
    for axis in ['x', 'y', 'z']:
      f.write('[' + axis + ']\n')
      f.write('max_feedrate=' + config[axis + '_max_feedrate'] + '\n')
      f.write('home_feedrate=' + config[axis + '_home_feedrate'] + '\n')
      f.write('steps_per_mm=' + config[axis + '_steps_per_mm'] + '\n')
      f.write('endstop=' + ('1' if config[axis + '_endstop_is_max'] == 'true' else '0') + '\n')

    f.write('[a]\n')
    f.write('max_feedrate=' + config['e_max_feedrate'] + '\n')
    f.write('steps_per_mm=' + config['e_steps_per_mm'] + '\n')
    f.write('motor_steps=' + config['e_motor_steps'] + '\n')
    f.write('has_heated_build_platform=' + ('1' if config['has_heated_bed'] == 'true' else '0') + '\n')

    f.flush()
    f.close()
    return config_file

  def _null_on_receive(self, line):
    print "on_receive:", line

  def _null_on_complete(self):
    print "on_complete"

  def _run(self):
    config_file = self._create_config_file(self.settings)

    gpx_command = [os.getenv("HOME") + '/Burijji/GPX/gpx', '-i', '-s', '-v', '-r', '-c', config_file, '-b', str(self.baud), self.port]
    print " ".join(gpx_command)
    self.gpx = subprocess.Popen(gpx_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    self.read_queue = Queue.Queue()
    read_thread = threading.Thread(target=self._threaded_read_from_gpx, args=(self.gpx.stdout, self.read_queue))
    read_thread.daemon = True # Don't wait for this to be done on exit
    read_thread.start()

    read_thread = threading.Thread(target=self._threaded_read_from_gpx, args=(self.gpx.stderr, self.read_queue))
    read_thread.daemon = True # Don't wait for this to be done on exit
    read_thread.start()

    time.sleep(3)
    self.ready = True
    print "X3G Ready"

    while self.running:
      self._read()
      self._write()
      self._check_for_exit()

    self.gpx.kill()

  def _threaded_read_from_gpx(self, stream, queue):
    for line in iter(stream.readline, b''):
      queue.put(line.strip())
      sys.stdout.flush()

      if not self.running:
        break

    stream.close()

  def _read(self):
    try:
      with self.lock:
        read_line = self.read_queue.get_nowait()

        if read_line.strip() == "ok":
          self.waiting_for_ok = False

        if read_line.strip() == "fail":
          self.ok = False

      self.on_receive(read_line)
    except Queue.Empty:
      pass
    except Exception as e:
      print "_run exception", e
      self.ok = False

  def _write(self):
    with self.lock:
      if (not self.waiting_for_ok) and len(self.commands_to_send) > 0:
        command_to_send = self.commands_to_send[0]
        del self.commands_to_send[0]

        try:
          self.waiting_for_ok = True
          self.gpx.stdin.write(command_to_send.strip() + "\n")
        except IOError as io:
          print "X3G / IOError writing '" + str(command_to_send.strip()) + "'", io
          self.ok = False
        except Exception as e:
          print "X3G Error", e
          self.ok = False

        if self.is_sending_many and len(self.commands_to_send) == 0:
          self.is_sending_many = False

          if self.on_complete != None:
            self.on_complete()

  def _check_for_exit(self):
    with self.lock:
      has_terminated = self.gpx.poll()
      if has_terminated != None:
        self.ok = False

  def end_print(self):
    with self.lock:
      print "x3g.py end print"
      self.commands_to_send = []
      self.is_sending_many = False

  def stop(self):
    self.running = False

  @property
  def printing(self):
    return self.is_sending_many

  @property
  def queueindex(self):
    index = self.print_queue_size - len(self.commands_to_send)

    if index < 0:
      return 0

    return index
    

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
