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
from colorama import Fore, Back, Style, init

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

    controllerConnected = False
    ampConnected = False

    def setup(self):
        """ Perform initial setup for midi etc """
        # create virtual midi output
        if enableVirtualControllerDevice:
            self.midiout = rtmidi.MidiOut()
            self.midiin = rtmidi.MidiIn()

            self.midiout.open_virtual_port(VIRTUAL_PORT)
            self.midiin.open_virtual_port(VIRTUAL_PORT)

            print(mido.get_output_names())

    def findAmpMidiPort(self, printPorts=False):
        allPorts = mido.get_output_names()

        if (printPorts):
            print(allPorts)

        for p in allPorts:
            if (AMP_PORT in p):
                return p

        # amp not found in midi ports list, must be disconnected
        return None

    def reconnect(self):

        self.logInfo("Reconnecting all devices")

        # connect or reconnect to all devices
        ampPort = self.findAmpMidiPort()

        if (ampPort):
            # reconnect amp
            self.amp = mido.open_output(ampPort)

        if (self.controllerConnected):            
            self.openControllerDevice()

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
                data = endpoint.read(9, timeout) # experiment with ready byte values here 3-64, midi messages are up to 3 bytes but controller can send several in a batch

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

        if (self.device):
            print("device may already be connected, closing")
            try:
                usb.util.release_interface(self.device, 0)
            except:
                pass

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
    
        while True:
            try:
                if (self.controllerConnected and self.epRead is not None):
                    data = self.read_from_endpoint(self.epRead, 0)

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
                self.logError("Exception during controller read.")
                self.logError(e)


    def startDeviceWatcher(self):
        """
        Continuously check USB device list, detected if changes have occurred
        """

        while True:
            try:

                controllerDevice = usb.core.find(
                    idVendor=VENDOR_ID, idProduct=PRODUCT_ID)

                ampPort = self.findAmpMidiPort()

                configChanged = False

                if (controllerDevice is None):
                    if (self.controllerConnected is True):
                        self.logInfo("Controller disconnected")
                        self.controllerConnected = False
                        configChanged = True
                else:
                    if (self.controllerConnected is False):
                        # reconnect if not already connected
                        self.logInfo("Controller [re]connected")
                        self.controllerConnected = True
                        configChanged = True

                if (ampPort is None):
                    if (self.ampConnected is True):
                        self.logInfo("Amp disconnected")
                        self.ampConnected = False
                        configChanged = True
                else:
                    if (self.ampConnected is False):
                        self.logInfo("Amp [re]connected")
                        self.ampConnected = True  
                        configChanged = True

                if (configChanged and self.ampConnected and self.controllerConnected):
                    self.reconnect()

                time.sleep(1)

            except Exception as e:
                self.logError(repr(e))

    def startMessageProcessing(self):
        """ 
        Start message processing loop
        Continuously reads from USB, converts data (if any) to midi and send to both virtual midi and directly to connected amp
        """
        self.logInfo(Fore.RED + "Podtana HD Started V1.1")

        if (self.amp is not None):
            self.logInfo(Fore.GREEN+"Amp Connected")
        else:
            self.logInfo(Fore.RED+"Amp Not Connected")

        if (self.device is not None):
            self.logInfo(Fore.GREEN+"Controller Connected")
        else:
            self.logInfo(Fore.RED+"Controller Not Connected")

      
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
                    
                    if (midiMsg.type == 'program_change'):
                        # send reset for max volume before changing patch
                        if (self.amp is not None):
                            self.logInfo("Setting volume max")
                            self.amp.send(mido.Message('control_change', control=81, value=127))

                    self.lastMsgSent = midiMsg

                    self.logVerbose("SENDING: {}".format(midiMsg))

                    # send message to amp, if enabled
                    if (self.amp is not None):
                        self.amp.send(midiMsg)

            except Exception as e:
                self.logError(e)
      
controllerBridge = ControllerBridge()

controllerBridge.setup()

# listen for controller and amp device changes
threading.Thread(target=controllerBridge.startDeviceWatcher,daemon=True).start()

# listen for controller midi events
threading.Thread(target=controllerBridge.startMessageReader,daemon=True).start()

# process midi events
threading.Thread(target=controllerBridge.startMessageProcessing,daemon=True).start()

print("Starting event loop")

try:
    while True:
        time.sleep(10)
except KeyboardInterrupt:
    print("cleanup and close")
    controllerBridge.cleanup()
    quit()
