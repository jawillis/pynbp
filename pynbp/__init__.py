#!/usr/bin/env python
# -*- coding: utf-8 -*-
import time
from collections import namedtuple
import logging
import threading
from pathlib import Path
import socket
import serial
from bluetooth import *
import errno

"""
Python Numeric Broadcast Protocol

This module implements HP Tuners / Track Addict Numeric Broadcast Protocol

WiFI Implementation
"""

__version__ = '0.0.24'
home = str(Path.home())

NbpKPI = namedtuple('NbpKPI', 'name, unit, value')
NbpPayload = namedtuple('NbpPayload', 'timestamp, packettype, nbpkpilist')

logger = logging.getLogger('pynbp')
fh = logging.FileHandler('{0}/pynbp.log'.format(home))
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s\n%(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)
logging.basicConfig(level=logging.WARNING)


class BasePyNBP(threading.Thread):
    def __init__(self, nbpqueue, device_name='PyNBP', protocol_version='NBP1', min_update_interval=0.2):
        self.device_name = device_name
        self.protocol_version = protocol_version
        self.last_update_time = 0
        self.packettime = 0
        self.kpis = {}
        self.nbpqueue = nbpqueue
        self.updatelist = []
        self.min_update_interval = min_update_interval
        threading.Thread.__init__(self)

    def run(self):
        raise NotImplemented

    def metedata(self):
        return str.encode("@NAME:{0}\n\n".format(self.device_name))

    def _genpacket(self, type='ALL'):
        packet = "*{0},{1},{2:.6f}\n".format(self.protocol_version, type, self.packettime)

        if self.updatelist and type != 'ALL':
            kpis = [self.kpis[k] for k in self.updatelist]
        else:
            kpis = self.kpis.values()

        for kpi in kpis:
            if kpi.unit:
                packet += '"{0}","{1}":{2}\n'.format(kpi.name, kpi.unit, kpi.value)
            else:
                packet += '"{0}":{1}\n'.format(kpi.name, kpi.value)

        packet += "#\n\n"

        return str.encode(packet)


class PyNBP(BasePyNBP):
    def __init__(self, nbpqueue, device='/dev/rfcomm0', device_name='PyNBP', protocol_version='NBP1',
                 min_update_interval=0.2):
        super().__init__(nbpqueue, device_name=device_name, protocol_version=protocol_version,
                         min_update_interval=min_update_interval)
        self.device = device

    def run(self):
        connected = False
        serport = None

        while True:
            nbppayload = self.nbpqueue.get()

            self.packettime = nbppayload.timestamp

            for kpi in nbppayload.nbpkpilist:
                if kpi.name not in self.updatelist:
                    self.updatelist.append(kpi.name)
                self.kpis[kpi.name] = kpi

            if not connected:
                try:
                    serport = serial.serial_for_url(self.device)
                    connected = True
                except:
                    logging.info('Comm Port conection not open - waiting for connection')

            if connected and serport.is_open:
                try:
                    if serport.in_waiting > 0:
                        logger.info(serport.read(serport.in_waiting).decode())

                    if time.time() - self.last_update_time > self.min_update_interval:
                        if nbppayload.packettype == 'UPDATE':
                            nbppacket = self._genpacket(type=nbppayload.packettype)
                        elif nbppayload.packettype == 'ALL':
                            nbppacket = self._genpacket(type=nbppayload.packettype)
                        elif nbppayload.packettype == 'METADATA':
                            nbppacket = self.metedata()
                        else:
                            logging.info('Invalid packet type {0}.'.format(nbppayload.packettype))

                        logger.warning(nbppacket.decode())

                        serport.write(nbppacket)
                        self.updatelist = []
                        self.last_update_time = time.time()

                except:
                    logging.exception('Serial Write Failed. Closing port.')
                    serport.close()
                    connected = False


class WifiPyNBP(BasePyNBP):
    def __init__(self, nbpqueue, ip='127.0.0.1', port=35000, device_name='PyNBP', protocol_version='NBP1',
                 min_update_interval=0.2):
        super().__init__(nbpqueue, device_name=device_name, protocol_version=protocol_version,
                         min_update_interval=min_update_interval)
        self.ip = ip
        self.port = port

    def run(self):
        connected = False
        serport = None
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        logging.warning('Binding to {0}:{1}'.format(self.ip, self.port))
        sock.bind((self.ip, self.port))
        sock.listen(1)

        while True:
            nbppayload = self.nbpqueue.get()

            self.packettime = nbppayload.timestamp

            for kpi in nbppayload.nbpkpilist:
                if kpi.name not in self.updatelist:
                    self.updatelist.append(kpi.name)
                self.kpis[kpi.name] = kpi

            if not connected:
                try:
                    conn, client_address = sock.accept()
                    connected = True
                    logging.warning('Connection from {0} open'.format(client_address))
                except:
                    logging.info('Socket conection not open - waiting for connection')

            if connected:
                try:
                    data = conn.recv(1024)
                    if data:
                        text = data.decode().strip()
                        logger.info(text)
                        if text == "!ALL":
                            logging.warning('ALL Packet Requested. Sending')
                            conn.sendall(self._genpacket('ALL'))

                    if time.time() - self.last_update_time > self.min_update_interval:
                        if nbppayload.packettype == 'UPDATE':
                            nbppacket = self._genpacket(type=nbppayload.packettype)
                        elif nbppayload.packettype == 'ALL':
                            nbppacket = self._genpacket(type=nbppayload.packettype)
                        elif nbppayload.packettype == 'METADATA':
                            nbppacket = self.metedata()
                        else:
                            logging.info('Invalid packet type {0}.'.format(nbppayload.packettype))

                        logger.warning(nbppacket.decode())

                        conn.sendall(nbppacket)
                        self.updatelist = []
                        self.last_update_time = time.time()

                except:
                    logging.exception('Wifi Write Failed. Closing port.')
                    conn.close()
                    connected = False

class BTPyNBP(BasePyNBP):
    def __init__(self, nbpqueue, device_name='PyNBP', protocol_version='NBP1',
                 min_update_interval=0.2, loglevel=logging.WARNING):
        logging.basicConfig(level=loglevel)
        super().__init__(nbpqueue, device_name=device_name, protocol_version=protocol_version,
                         min_update_interval=min_update_interval)

    def run(self):
        connected = False
        serport = None
        sock = BluetoothSocket( RFCOMM )
        sock.settimeout(1.0)
        sock.setblocking(False)
        # logging.warning('Binding to {0}:{1}'.format(self.ip, self.port))
        sock.bind(("", PORT_ANY))
        sock.listen(1)

        port = sock.getsockname()[1]

        uuid = "94f39d29-7d6d-437d-973b-fba39e49d4ee"

        advertise_service(sock, "SampleServer",
                          service_id=uuid,
                          service_classes=[uuid, SERIAL_PORT_CLASS],
                          profiles=[SERIAL_PORT_PROFILE],
                          #                   protocols = [ OBEX_UUID ]
                          )

        print("Waiting for connection on RFCOMM channel %d" % port)

        while True:
            # logging.warning('1')
            nbppayload = self.nbpqueue.get()
            # logging.warning('2')
            self.packettime = nbppayload.timestamp

            for kpi in nbppayload.nbpkpilist:
                if kpi.name not in self.updatelist:
                    self.updatelist.append(kpi.name)
                self.kpis[kpi.name] = kpi

            if not connected:
                # logging.warning('3')
                try:
                    conn, client_address = sock.accept()
                    conn.setblocking(False)
                    connected = True
                    logging.warning('Connection from {0} open'.format(client_address))
                except:
                    logging.info('Socket conection not open - waiting for connection')

            if connected:
                # logging.warning('4')
                try:
                    data = conn.recv(1024)
                except BluetoothError as e:
                    pass
                    # err, msg = e.args[0]
                    # if err == errno.EAGAIN or err == errno.EWOULDBLOCK:
                    #     logging.warning('no data received...')
                    #     pass
                    # else:
                    #     logging.exception('some bullshit happened')
                    #     logging.exception('err is {}'.format(err))
                    #     raise
                else:
                    text = data.decode().strip()
                    logging.info(text)
                    if text == "!ALL":
                        logging.info('ALL Packet Requested. Sending')
                        conn.sendall(self._genpacket('ALL'))
                # logging.warning('5')
                try:
                    if time.time() - self.last_update_time > self.min_update_interval:
                        if nbppayload.packettype == 'UPDATE':
                            nbppacket = self._genpacket(type=nbppayload.packettype)
                        elif nbppayload.packettype == 'ALL':
                            nbppacket = self._genpacket(type=nbppayload.packettype)
                        elif nbppayload.packettype == 'METADATA':
                            nbppacket = self.metedata()
                        else:
                            logging.warning('Invalid packet type {0}.'.format(nbppayload.packettype))

                        logging.info(nbppacket.decode())

                        conn.sendall(nbppacket)
                        self.updatelist = []
                        self.last_update_time = time.time()
                    else:
                        logging.info('not enough time has passed..')

                except:
                    logging.warning('Bluetooth Write Failed. Closing port.')
                    conn.close()
                    connected = False
