from printrun.printcore import printcore
from printrun.GCodeAnalyzer import GCodeAnalyzer
from time import sleep
import threading

class repWrapper():

	def __init__(self, server):
		self.printer    = printcore()
		self.__server   = server
		self.__analyzer = GCodeAnalyzer()

		self.__mutex    = threading.Lock()

	def start(self):
		threading.Thread(target=self.__run)

	def stop(self):
		pass

	def __run(self):
		self.printer.connect(self.__server.port, self.__server.baud)

		while self.server.running:
			sleep(1)

		self.printer.disconnect()