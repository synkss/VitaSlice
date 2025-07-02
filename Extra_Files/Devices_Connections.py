# Filterwheel imports
import microscope
from microscope.controllers.zaber import _ZaberFilterWheel, _ZaberConnection

# Laserbox import
import pyvisa

# Scanner import
import ctypes

# Stages import
from pipython import GCSDevice
from pipython import GCSDevice, pitools

# Cameras imports
from pylablib.devices import DCAM


class device_initializations:
    
    def filterwheel_1(self):
        filter_conn_1 = _ZaberConnection(port="COM9", baudrate=115200, timeout=0.05)
        filterwheel_1 = _ZaberFilterWheel(filter_conn_1, 1)
        return filterwheel_1
    
    def filterwheel_2(self):
        filter_conn_2 = _ZaberConnection(port="COM4", baudrate=115200, timeout=0.05)
        filterwheel_2 = _ZaberFilterWheel(filter_conn_2, 1)
        return filterwheel_2
    
    def laserbox(self):
        rm = pyvisa.ResourceManager()
        laserbox = rm.open_resource('ASRL7::INSTR')
        laserbox.baud_rate = 115200
        laserbox.read_termination = "\r\n"
        laserbox.write_termination = "\r\n"

        return laserbox
    
    def scanner(self):
        """Load the rtc5_board dll"""

        dll_path = "RTC5DLLx64"
        rtc5_board = ctypes.windll.LoadLibrary(dll_path)
        print("Loading DLL from:", dll_path)
        rtc5_board = ctypes.windll.LoadLibrary(dll_path)

        # Initializing the dll
        init_result = rtc5_board.init_rtc5_dll()
        print("Initialization:", init_result)

        # Mode
        mode = rtc5_board.set_rtc4_mode()
        print("Mode:", mode)

        execution = rtc5_board.stop_execution()
        print("Stop Execution:", execution)

        program_files = rtc5_board.load_program_file(0)
        print("Program Files:", program_files)

        load = rtc5_board.load_correction_file(0,1,2)
        print("Correction File Load:", load)

        table = rtc5_board.select_cor_table(1,0)
        print("Correction Table Selection:", table)

        # Set the jump speed
        rtc5_board.set_jump_speed(ctypes.c_double(800000))

        # Set laser control
        rtc5_board.set_laser_control(1)

        # Set Laser Mode 6
        rtc5_board.set_laser_mode(6)

        return rtc5_board
    
    def stages(self):
        """Initialize and Reference the Stages"""

        CONTROLLERNAME = 'C-884'
        STAGES = ['M-110.1DG1', 'M-110.1DG1', 'M-112.1DG1']

        pidevice = GCSDevice(CONTROLLERNAME)
        pidevice.ConnectUSB(serialnum='118067518')
        pitools.startup(pidevice, stages=STAGES)

            # set the stage velocities to the maximum
        velocity_x = 1
        velocity_y = 1
        velocity_z = 1.5
        pidevice.VEL(['1', '2', '3'], [velocity_x, velocity_y, velocity_z])


            # reference Z to the maximum position
        pidevice.SPA('3', 0x70, 6)
        pidevice.SPA('3', 0x16, 25)
        pidevice.FRF('3')
        pitools.waitontarget(pidevice, axes=['3'])
        pidevice.RON('3', 0)  
        pidevice.POS('3', 25)

            # initialize and reference the Rotation Stage
        pidevice.SVO('4', True)
        pidevice.FRF('4')
        pitools.waitontarget(pidevice, axes=['4'])

            # move the XY stages to the middle positions
        pidevice.MOV("1", 2.50000)    # move X
        pidevice.MOV("2", 2.50000)    # move Y

        return pidevice

    def camera(self, idx):
        camera = DCAM.DCAMCamera(idx)

        return camera


import time
class device_closings:

    def filterwheel_closing(device):
        device.shutdown()

    def laserbox_closing(device):
        device.close()

    def scanner_closing(device):
        device.release_rtc(1)
        device.free_rtc5_dll()

    def stages_closing(device):
        device.CloseConnection()

    def camera_closing(acq_thread):
        acq_thread.camera.stop_acquisition()
        time.sleep(1)
        acq_thread.camera.clear_acquisition()
        time.sleep(1)
        acq_thread.camera.close()

    



