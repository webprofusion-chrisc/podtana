##
# Podtana HD
# Bridge from USB Line 6 POD HD 400 to Boss Katana MKII (100 etc), Also advertises controller as virtual midi output
##

import os
import sys
import platform
import usb.core
import usb.util
import time
import mido
import time
import datetime as dt
import rtmidi
import threading
import queue
from colorama import Fore, Back, Style

VENDOR_ID = 0x0e41  # controller USB device vendor ID (Line 6)
PRODUCT_ID = 0x5058  # product USB device id (POD HD 400)
AMP_PORT = "KATANA:KATANA MIDI 1"
VIRTUAL_PORT = "VIRTUAL MIDI DEVICE"

CONTROLLER_WRITE_ENDPOINT = '3'
CONTROLLER_READ_ENDPOINT = '132'

enableVirtualControllerDevice = True
enableVerboseLogs = False

class ControllerBridge:
    device = None
    """ The controller device e.g. the POD HD 400"""

    amp = None
    """ The target amp to send midi to e.g. the Boss Katana MKII 100 """

    midiout = None
    """ The virtual midi output, used to allow general purpose output of the controller via a virtual midi port """

    midiin = None
    """ The virtual midi in, used to allow general purpose output of the controller via a virtual midi port """

    was_kernel_driver_active = False

    epRead = None
    """ controller read USB endpoint """

    epWrite = None
    """ controller write USB endpoint """

    lastMsgSent = None
    """ last message sent to the amp """

    messageQueue = queue.SimpleQueue()

    def setup(self):
        """ Perform initial setup for midi etc """
        # create virtual midi output
        if enableVirtualControllerDevice:
            self.midiout = rtmidi.MidiOut()
            self.midiin = rtmidi.MidiIn()

            # find matching amp name port
            allPorts = mido.get_output_names()
            print(allPorts)

            selectedAmpPort = AMP_PORT
            for p in allPorts:
                if (AMP_PORT in p):
                    selectedAmpPort = p

            self.amp = mido.open_output(selectedAmpPort)

            self.midiout.open_virtual_port(VIRTUAL_PORT)
            self.midiin.open_virtual_port(VIRTUAL_PORT)

            print(mido.get_output_names())

    def cleanup(self):
        """ Perform cleanup on exit """

        print("Cleaning up on exit")

        # remove virtual midi output
        if self.midiout is not None:
            del self.midiout

        if self.midiin is not None:
            del self.midiin

        # free interface
        if self.device is not None:
            usb.util.release_interface(self.device, 0)

            # This applies to Linux only - reattach the kernel driver if we previously detached it
            if self.was_kernel_driver_active == True:
                self.device.attach_kernel_driver(0)

    def read_from_endpoint(self, endpoint, timeout):
        """ read from the given endpoint, allowing given timeout """

        allBytes = bytearray(b'')
        try:
            # read n bytes from endpoint, append output until there is no more data or we have reached max reads

            maxRead = 4
            while maxRead > 0:
                maxRead = maxRead-1
                data = endpoint.read(8, timeout)

                if data is not None:
                    bData = bytes(data)
                    allBytes += bData
                else:
                    print("no data, breaking")
                    break

            return allBytes

        except usb.core.USBError as usbError:
            return allBytes
        except Exception as e:
            print("read :: {}".format(e))
            return None

    def logVerbose(self, msg):
        if enableVerboseLogs:
            print(Fore.BLUE+msg)

    def logInfo(self, msg):
        print(Fore.WHITE+msg)

    def logError(self, msg):
        print(Fore.RED+msg)

    def openControllerDevice(self):

        # derived from https://www.ontrak.net/LibUSBPy.htm

        if platform.system() == 'Windows':
            # required for Windows only
            # libusb DLLs from: https://sourcefore.net/projects/libusb/
            arch = platform.architecture()
            if arch[0] == '32bit':
                # 32-bit DLL, select the appropriate one based on your Python installation
                backend = usb.backend.libusb1.get_backend(
                    find_library=lambda x: "libusb/x86/libusb-1.0.dll")
            elif arch[0] == '64bit':
                backend = usb.backend.libusb1.get_backend(
                    find_library=lambda x: "libusb/x64/libusb-1.0.dll")  # 64-bit DLL

            self.device = usb.core.find(
                backend=backend, idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        elif platform.system() == 'Linux':
            self.device = usb.core.find(
                idVendor=VENDOR_ID, idProduct=PRODUCT_ID)

            if (self.device is not None):
                # if the OS kernel already claimed the device
                if self.device.is_kernel_driver_active(0) is True:
                    # tell the kernel to detach - requires elevated privileges
                    self.device.detach_kernel_driver(0)
                    self.was_kernel_driver_active = True
        else:
            self.device = usb.core.find(
                idVendor=VENDOR_ID, idProduct=PRODUCT_ID)

        if self.device is None:
            self.logError(
                "Controller Device not found. Please ensure it is connected.")
        else:
            self.device.reset()

            # Set the active configuration. With no arguments, the first configuration will be the active one
            self.device.set_configuration(1)

            # important for POD HD400 - set altsetting to read/write as midi
            self.device.set_interface_altsetting(
                interface=0, alternate_setting=5)

            cfg = self.device.get_active_configuration()

            intf = cfg[(0, 5)]

            # get read and write endpoints
            for ep in intf:
                sys.stdout.write('\t\t' +
                                 str(ep.bEndpointAddress) +
                                 '\n')
                if str(ep.bEndpointAddress) == CONTROLLER_WRITE_ENDPOINT:
                    self.epWrite = ep
                elif str(ep.bEndpointAddress) == CONTROLLER_READ_ENDPOINT:
                    self.epRead = ep

            assert self.epRead is not None
            assert self.epWrite is not None

            self.logVerbose("Endpoints:")
            self.logVerbose(str(self.epRead))
            self.logVerbose(str(self.epWrite))

            # send midi reset message
            self.epWrite.write(mido.Message('reset').bytes())

    def startMessageReader(self):
        """
        Continuously read from USB, add messages to queue
        """
        try:
            while True:
                try:

                    data = self.read_from_endpoint(self.epRead, 25)

                    if data != None:
                        try:
                            messages = mido.parse_all(data)

                            if messages is not None and len(messages) > 0:

                                for midiMsg in messages:
                                    self.messageQueue.put(midiMsg)

                        except Exception as midiErr:
                            self.logError(midiErr)
                            pass

                except Exception as e:
                    self.logError(e)
        except:
            self.cleanup()
            quit()

    def startMessageProcessing(self):
        """ 
        Start message processing loop
        Continuously reads from USB, converts data (if any) to midi and send to both virtual midi and directly to connected amp
        """
        self.logInfo(Fore.RED + "Podtana HD Started")
        if (self.amp is not None):
            self.logInfo(Fore.GREEN+"Amp Connected")
        else:
            self.logInfo(Fore.RED+"Amp Not Connected")

        if (self.device is not None):
            self.logInfo(Fore.GREEN+"Controller Connected")
        else:
            self.logInfo(Fore.RED+"Controller Not Connected")
            self.cleanup()
            quit()

        start_time = dt.datetime.today().timestamp()
        i = 0

        try:
            while True:
                try:
                    midiMsg = self.messageQueue.get(True, 1000)
                    if (midiMsg is not None):

                        # send message to virtual port, if enabled
                        if (self.midiout is not None):
                            self.midiout.send_message(midiMsg.bytes())

                        # transpose/map controller values to amp midi values
                        if (midiMsg.is_cc()):

                            if (midiMsg.control == 7):  # map vol
                                midiMsg.control = 81
                            elif (midiMsg.control == 4):  # map wah

                                #midiMsg.channel = 1
                                midiMsg.control = 80
                                if (midiMsg.value > 0):  # scale wah 0-64
                                    midiMsg.value = round(midiMsg.value/2)

                            if (self.lastMsgSent is not None and self.lastMsgSent.is_cc()):
                                if midiMsg.control == self.lastMsgSent.control and midiMsg.value == self.lastMsgSent.value:
                                    self.logVerbose('skipping duplicate')
                                    continue

                        self.lastMsgSent = midiMsg

                        self.logVerbose("SENDING: {}".format(midiMsg))

                        # send message to amp, if enabled
                        if (self.amp is not None):
                            self.amp.send(midiMsg)

                    time_diff = dt.datetime.today().timestamp() - start_time
                    i += 1
                    opsPerSecond = i / time_diff
                  
                except Exception as e:
                    self.logError(e)
        except Exception as e:
            self.logError(e)
            self.cleanup()
            quit()

# pause a few seconds if we are starting from boot to allow all devices to be ready.
time.sleep(3)

controllerBridge = ControllerBridge()

controllerBridge.setup()
controllerBridge.openControllerDevice()

# listen for controller midi events
threading.Thread(target=controllerBridge.startMessageReader,
                 daemon=True).start()

# process midi events
threading.Thread(target=controllerBridge.startMessageProcessing,
                 daemon=True).start()
while True:
    time.sleep(1)

controllerBridge.cleanup()
quit()
