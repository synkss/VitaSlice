%load_ext autoreload
%autoreload 2

from concurrent.futures import ThreadPoolExecutor, as_completed
import os, re
os.environ["QT_API"] = "pyside6"
os.environ["NAPARI_QT_API"] = "pyside6"
import vispy.app
vispy.app.use_app('pyside6')

import napari
from napari.layers import Image
import sys
import numpy as np
import ctypes
import cv2

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QGridLayout, QVBoxLayout, QSplitter, QDialog
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QMdiArea, QMdiSubWindow, QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPalette, QColor
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PySide6.QtCore import QThread, Signal


from napari.utils.theme import get_theme, register_theme

from Camera_Widget_py import Camera_Widget
from Filterwheels_Widget_py import Filterwheels_Widget
from Lasers_Widget_py import Lasers_Widget
from Scanner_Widget_py import Scanner_Widget
from Stages_Widget_py import Stages_Widget
from YStack_Widget_py import YStack_Widget
from File_Explorer_py import File_Explorer
from Launcher_py import ALM_Launcher

import json
from skimage.transform import pyramid_gaussian

from pylablib.devices import DCAM
from Extra_Files.Acquisition_Thread_Code import Acquisition_Thread
from Extra_Files.Devices_Connections import device_initializations, device_closings
from Extra_Files.Floating_Widget import FloatingWidget


from skimage.transform import resize
import time

import shutil
import numpy as np
import zarr
from ome_zarr.io import parse_url
from ome_zarr.writer import write_multiscales_metadata
from ome_zarr.format import FormatV04
from skimage.transform import downscale_local_mean

####################################################################################################

def set_napari_background(viewer, color="#303030"):
    """Sets only the background color in Napari."""
    theme = get_theme("dark")  # Load the existing dark theme
    theme.background = color   # Change only the background color

    register_theme('custom_dark', theme, 'custom')  # Register the new theme
    viewer.theme = "custom_dark"  # Apply it to Napari



class FrameGrabberThread(QThread):
    """ Continuously grabs frames from a camera on its own thread. """
    frame_ready = Signal(np.ndarray, int)  
    # (frame, camera_id) so you can distinguish Camera 1 vs 2

    def __init__(self, camera, cam_id, interval_ms=50):
        super().__init__()
        self.camera   = camera
        self.cam_id   = cam_id
        self.interval = interval_ms
        self._running = False

    def run(self):
        self._running = True

        while self._running:

            try:
                self.camera.wait_for_frame(timeout=5)
                frame = self.camera.read_newest_image(peek=True)
                
            # Exception that allow the code to progress while the camera is changing parameters when Live
            except Exception as e:
                continue
            
            if frame is not None:
                self.frame_ready.emit(frame, self.cam_id)

            time.sleep(0.03)

    def stop(self):
        self._running = False
        self.wait()


####################################################################################################

from PySide6.QtCore import Slot

class ALM_Lightsheet(QMainWindow):

    # prevent system sleep
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000002)

    #-------------------------------------------------------------------------------------------------
    # Window Functions

    def on_frame_received(self, frame: np.ndarray, cam_id: int):

        name = f"Camera {cam_id}"

        # Mirror the view for Camera 1
        if cam_id == 1:

            # Mirror the frame
            frame = np.fliplr(frame)

            # Ensure it’s C-contiguous so OpenCV can see it as a Mat
            frame = np.ascontiguousarray(frame)

            if "Camera 1" in self.viewer.layers:
                layer = self.viewer.layers["Camera 1"]
                # contrast_limits is a (min, max) tuple
                contrast_val = int(layer.contrast_limits[1])
            else:
                contrast_val = int(frame.max())

            base_org = (10, 85)
            # Current frame dimensions
            cur_width  = self.camera_widget_1.width_x
            cur_height = self.camera_widget_1.height_y
            # Scale factors relative to the 2048×2048 design
            scale_x = cur_width  / 2048
            scale_y = cur_height / 2048

            # Write on the frame
            text       = "Camera 1"
            org        = (int(base_org[0] * scale_x), int(base_org[1] * scale_y))
            font       = cv2.FONT_HERSHEY_DUPLEX
            font_scale = 3.5 * scale_x  # Update font size by the size of the frame
            color = contrast_val
            thickness  = int(4 * scale_x) # Update font size by the size of the frame
            line_type  = cv2.LINE_AA

            cv2.putText(frame, text, org, font, font_scale, color, thickness, line_type)

            if name in self.viewer.layers:
                self.viewer.layers[name].data = frame
            else:
                self.viewer.add_image(frame, name=name, colormap="gray")
                QTimer.singleShot(0, lambda: self.viewer.fit_to_view(margin=0.05))

        elif cam_id == 2:

            # Ensure it’s C-contiguous so OpenCV can see it as a Mat
            frame = np.ascontiguousarray(frame)

            if "Camera 2" in self.viewer.layers:
                layer = self.viewer.layers["Camera 2"]
                # contrast_limits is a (min, max) tuple
                contrast_val = int(layer.contrast_limits[1])
            else:
                contrast_val = int(frame.max())

            # Write on the frame
            text       = "Camera 2"
            org        = (10, 85)
            font       = cv2.FONT_HERSHEY_DUPLEX
            font_scale = 3.5 * self.camera_widget_2.width_x / 2048 # Update font size by the size of the frame
            color = contrast_val
            thickness  = int(4 * self.camera_widget_2.width_x / 2048) # Update font size by the size of the frame
            line_type  = cv2.LINE_AA

            cv2.putText(frame, text, org, font, font_scale, color, thickness, line_type)

            if name in self.viewer.layers:
                self.viewer.layers[name].data = frame
            else:
                self.viewer.add_image(frame, name=name, colormap="gray")
                QTimer.singleShot(0, lambda: self.viewer.fit_to_view(margin=0.05))


    @Slot(bool)
    def on_camera1_live_toggled(self, live: bool):
        # Live ON
        if live:
            self.camera_1.stop_acquisition()
            self.camera_1.clear_acquisition()

            self.camera_1.setup_acquisition(mode="sequence", nframes=200)     
            self.camera_1.start_acquisition()     

            # start grabbing
            self.grabber_1.start()

            # Fit the viewer
            QTimer.singleShot(0, lambda: self.viewer.fit_to_view(margin=0.05))

            # if the camera is at External Trigger, make a lightsheet
            if self.camera_widget_1.cameramode_combobox.currentText() == "Normal Mode":
                self.scanner_widget.pushbutton_2.setChecked(True)
                self.scanner_widget.pushbutton_2.setText("Stop\nLightsheet")
                self.scanner_widget.toggle_lightsheet(checked=True)
                self.scanner_widget.lineedit_0.setEnabled(False)
                self.scanner_widget.lineedit_1.setEnabled(False)

                # Automatic Laser Activation
                if self.laser_widget.automatic_laser_activation_checkbox.isChecked():
                    if self.laser_widget.last_laser_on != 0:
                        last_laser = self.laser_widget.last_laser_on
                        self.laser_widget.activate_laser_by_number(last_laser, 1)


        # Live OFF
        else:
            self.camera_1.stop_acquisition()
            self.camera_1.clear_acquisition()
            # stop grabbing
            self.grabber_1.stop()
            # turn lasers off
            self.laser_widget.turn_all_off()
            # turn scanner off
            self.scanner_widget.lightsheet_stop()


    @Slot(bool)
    def on_camera2_live_toggled(self, live: bool):
        # Live ON
        if live:

            self.camera_2.stop_acquisition()
            self.camera_2.clear_acquisition()

            self.camera_2.setup_acquisition(mode="sequence", nframes=200)     
            self.camera_2.start_acquisition()     

            # start grabbing
            self.grabber_2.start()

            # Fit the viewer
            QTimer.singleShot(0, lambda: self.viewer.fit_to_view(margin=0.05))

            # if the camera is at Internal Trigger, make a lightsheet
            if self.camera_widget_2.cameramode_combobox.currentText() == "Normal Mode":
                self.scanner_widget.pushbutton_2.setChecked(True)
                self.scanner_widget.pushbutton_2.setText("Stop\nLightsheet")
                self.scanner_widget.toggle_lightsheet(checked=True)
                self.scanner_widget.lineedit_0.setEnabled(False)
                self.scanner_widget.lineedit_1.setEnabled(False)

                # Automatic Laser Activation
                if self.laser_widget.automatic_laser_activation_checkbox.isChecked():
                    if self.laser_widget.last_laser_on != 0:
                        last_laser = self.laser_widget.last_laser_on
                        self.laser_widget.activate_laser_by_number(last_laser, 1)

        # Live OFF
        else:
            self.camera_2.stop_acquisition()
            self.camera_2.clear_acquisition()
            # stop grabbing
            self.grabber_2.stop()
            # turn lasers off
            self.laser_widget.turn_all_off()
            # turn scanner off
            self.scanner_widget.lightsheet_stop()

            

    @Slot(np.ndarray, int)
    def _on_frame_ready(self, frame, cam_id):
        """Keep the newest incoming frame in memory."""
        self.latest_frames[cam_id] = frame.copy()

    @Slot(str)
    def _on_path_changed(self, new_path: str):
        self.current_save_directory = new_path

        if hasattr(self, 'ystack_widget'):
            self.ystack_widget.update_save_directory(new_path)


    #-------------------------------------------------------------------------------------------------
    # For the Floating Widgets

    def add_widget_at_position(self, widget, title, x, y):
        """Adds a widget inside a floating window at a specific position."""
        floating_widget = FloatingWidget(widget, title)
        self.mdi_area.addSubWindow(floating_widget)

        floating_widget.move(x, y)  # Manually position the window
        floating_widget.show()

    #-------------------------------------------------------------------------------------------------
    # Snap Capture

    def _get_next_snap_number(self, save_directory, prefix):
        """
        Scan self.snap_directory for files named 'Snap<N>.png',
        find the highest N, and return N+1 (or 1 if none).
        """
        esc = re.escape(prefix)
        pat = re.compile(rf"^{esc}_Snap(\d+)\.ome\.zarr$")
        nums = []
        for fname in os.listdir(save_directory):
            m = pat.match(fname)
            if m:
                nums.append(int(m.group(1)))
        return max(nums) + 1 if nums else 1
    

    def on_camera1_snap(self, save_directory):
        # ——— load your latest frame ———
        frame: np.ndarray = self.latest_frames.get(1)

        # get the number for the file name
        prefix = "Camera1"
        file_number = self._get_next_snap_number(save_directory, prefix)

        # ——— open Zarr store ———
        output_file = os.path.join(
            save_directory,
            f"Camera1_Snap{file_number}.ome.zarr"
        )
        store = parse_url(output_file, mode="w").store
        root = zarr.group(store=store, overwrite=True)

        # ——— build an XY-only 3-level pyramid ———
        pyramid = [frame.astype(np.uint16)]
        max_levels = 3
        for level in range(1, max_levels):
            prev = pyramid[-1]
            # downsample by 2× in Y and X only:
            ds = downscale_local_mean(prev, (2, 2)).astype(prev.dtype)
            pyramid.append(ds)

        # ——— write each pyramid level as its own array ———
        for idx, img in enumerate(pyramid):
            # choose chunks (here, keep full width for simplicity)
            chunks = (min(256, img.shape[0]), min(256, img.shape[1]))
            root.create_dataset(
                str(idx),
                data=img,
                chunks=chunks,
                dtype=img.dtype
            )

        # ——— assemble the multiscale metadata ———
        # pixel size (µm) in Y and X:
        base_pixel_size = 0.65
        datasets = []
        for idx in range(len(pyramid)):
            scale_factor = 2 ** idx
            datasets.append({
                "path": str(idx),
                "coordinateTransformations": [
                    {
                        "type": "scale",
                        "scale": [
                            base_pixel_size * scale_factor,  # Y spacing
                            base_pixel_size * scale_factor,  # X spacing
                        ],
                    }
                ],
            })

        axes = [
            {"name": "y", "type": "space", "unit": "um"},
            {"name": "x", "type": "space", "unit": "um"},
        ]

        # ——— write only the multiscales metadata ———
        write_multiscales_metadata(
            group=root,
            datasets=datasets,
            fmt=FormatV04(),
            axes=axes,
            name="image"
        )


    def on_camera2_snap(self, save_directory):
        # ——— load your latest frame ———
        frame: np.ndarray = self.latest_frames.get(2)

        # get the number for the file name
        prefix = "Camera2"
        file_number = self._get_next_snap_number(save_directory, prefix)

        # ——— open Zarr store ———
        output_file = os.path.join(
            save_directory,
            f"Camera2_Snap{file_number}.ome.zarr"
        )
        store = parse_url(output_file, mode="w").store
        root = zarr.group(store=store, overwrite=True)

        # ——— build an XY-only 3-level pyramid ———
        pyramid = [frame.astype(np.uint16)]
        max_levels = 3
        for level in range(1, max_levels):
            prev = pyramid[-1]
            # downsample by 2× in Y and X only:
            ds = downscale_local_mean(prev, (2, 2)).astype(prev.dtype)
            pyramid.append(ds)

        # ——— write each pyramid level as its own array ———
        for idx, img in enumerate(pyramid):
            # choose chunks (here, keep full width for simplicity)
            chunks = (min(256, img.shape[0]), min(256, img.shape[1]))
            root.create_dataset(
                str(idx),
                data=img,
                chunks=chunks,
                dtype=img.dtype
            )

        # ——— assemble the multiscale metadata ———
        # pixel size (µm) in Y and X:
        base_pixel_size = 0.65
        datasets = []
        for idx in range(len(pyramid)):
            scale_factor = 2 ** idx
            datasets.append({
                "path": str(idx),
                "coordinateTransformations": [
                    {
                        "type": "scale",
                        "scale": [
                            base_pixel_size * scale_factor,  # Y spacing
                            base_pixel_size * scale_factor,  # X spacing
                        ],
                    }
                ],
            })

        axes = [
            {"name": "y", "type": "space", "unit": "um"},
            {"name": "x", "type": "space", "unit": "um"},
        ]

        # ——— write only the multiscales metadata ———
        write_multiscales_metadata(
            group=root,
            datasets=datasets,
            fmt=FormatV04(),
            axes=axes,
            name="image"
        )

    #-------------------------------------------------------------------------------------------------
    # Camera restarts

    def camera1_restart(self):
        """Function that restarts Camera 2"""

        self.camera_1.close()
        self.camera_1.open()

        print(self.camera_2.get_status())

    def camera2_restart(self):
        """Function that restarts Camera 2"""

        self.camera_2.close()
        self.camera_2.open()

        print(self.camera_2.get_status())

    #-------------------------------------------------------------------------------------------------
    # Device enabling/disabling

    def before_acquisition(self):
        """Function that acts on the widgets before the acquisition starts"""

        # Turn off all of the Lasers and uncheck the button
        self.laser_widget.turn_all_off()
        # If making a lightsheet, stop it
        if self.scanner_widget.pushbutton_2.isChecked():
            self.scanner_widget.pushbutton_2.setChecked(False)

        # Turn ON the Live button of the Cameras
        if self.camera_2 is None:
            if self.camera_widget_1.camera_checkbox.isChecked():
                if self.camera_widget_1.live_button.isChecked() is False:
                    self.camera_widget_1.live_button.setChecked(True)
                    self.camera_widget_1.live_button.setText("Stop")

                    self.camera_widget_1.snap_button.setEnabled(False)
                    self.camera_widget_1.restart_button.setEnabled(False)
        elif self.camera_1 is None:
            if self.camera_widget_2.camera_checkbox.isChecked():
                if self.camera_widget_2.live_button.isChecked() is False:
                    self.camera_widget_2.live_button.setChecked(True)
                    self.camera_widget_2.live_buttonEnabled("Stop")

                    self.camera_widget_2.snap_button.setEnabled(False)
                    self.camera_widget_2.restart_button.setEnabled(False)
        else:
            if self.camera_widget_1.camera_checkbox.isChecked():
                if self.camera_widget_1.live_button.isChecked() is False:
                    self.camera_widget_1.live_button.setChecked(True)
                    self.camera_widget_1.live_button.setText("Stop")

                    self.camera_widget_1.snap_button.setEnabled(False)
                    self.camera_widget_1.restart_button.setEnabled(False)
            if self.camera_widget_2.camera_checkbox.isChecked():
                if self.camera_widget_2.live_button.isChecked() is False:
                    self.camera_widget_2.live_button.setChecked(True)
                    self.camera_widget_2.live_button.setText("Stop")

                    self.camera_widget_2.snap_button.setEnabled(False)
                    self.camera_widget_2.restart_button.setEnabled(False)


        # Disable the Device Widgets
        if self.camera_2 is None:
            self.camera_widget_1.setDisabled(True)
        elif self.camera_1 is None:
            self.camera_widget_2.setDisabled(True)
        else:
            self.camera_widget_1.setDisabled(True)
            self.camera_widget_2.setDisabled(True)
        self.laser_widget.setDisabled(True)
        self.scanner_widget.setDisabled(True)
        self.filterwheels_widget.setDisabled(True)

        self.ystack_widget.start_button.setDisabled(True)
        self.ystack_widget.multipositions_checkbox.setDisabled(True)

        self.stages_widget.setDisabled(True)

        # In case I want to reset the contrast limits
        #QTimer.singleShot(3000, self._reset_all_image_contrast)



    def enable_devices(self):
        if self.camera_2 is None:
            self.camera_widget_1.setEnabled(True)
        elif self.camera_1 is None:
            self.camera_widget_2.setEnabled(True)
        else:
            self.camera_widget_1.setEnabled(True)
            self.camera_widget_2.setEnabled(True)
        self.laser_widget.setEnabled(True)
        self.scanner_widget.setEnabled(True)
        self.filterwheels_widget.setEnabled(True)

        self.ystack_widget.start_button.setEnabled(True)
        self.ystack_widget.multipositions_checkbox.setEnabled(True)

        self.stages_widget.setEnabled(True)

    def _reset_all_image_contrast(self):
        """
        Reset contrast limits on every Image layer
        in the current Napari viewer.
        """
        viewer = napari.current_viewer()
        if viewer is None:
            return

        for layer in viewer.layers:
            if isinstance(layer, Image):
                layer.reset_contrast_limits()
                # layer.reset_contrast_limits_range()
                print(f"Reset contrast on layer: {layer.name!r}")

    #-------------------------------------------------------------------------------------------------
    # Initialization

    def center_on_screen(self):
        """Centers the window on the screen."""
        screen = QApplication.primaryScreen().availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(screen.center())
        self.move(frame.topLeft())


    def __init__(self, initial_path=None):
        super().__init__()


        self.setWindowTitle("")
        self.setWindowIcon(QIcon("ALM.ico"))

        with open("Extra_Files//Filter_List.json", 'r') as file:
            self.filter_json_data = json.load(file)

        self.latest_frames = {}

        #---------------------------------------------------------------------------
        # Initialize the devices
        # self.filterwheel1 = device_initializations.filterwheel_1(self)
        # self.filterwheel2 = device_initializations.filterwheel_2(self)
        # self.laserbox = device_initializations.laserbox(self)
        # self.rtc5_board = device_initializations.scanner(self)
        # self.pidevice = device_initializations.stages(self)

        # list out each init call as a (name, callable) tuple
        init_tasks = [
            ("filterwheel1",     lambda: device_initializations.filterwheel_1(self)),
            ("filterwheel2",     lambda: device_initializations.filterwheel_2(self)),
            ("laserbox",         lambda: device_initializations.laserbox(self)),
            ("rtc5_board",       lambda: device_initializations.scanner(self)),
            ("pidevice",         lambda: device_initializations.stages(self)),
        ]

        # Submit them all at once
        self._init_results = {}
        with ThreadPoolExecutor(max_workers=len(init_tasks)) as exe:
            futures = { exe.submit(fn): name for name, fn in init_tasks }
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    device_obj = fut.result()
                except Exception as e:
                    # log or re-raise if something goes catastrophically wrong
                    raise RuntimeError(f"Failed to init {name}: {e}")
                self._init_results[name] = device_obj

        # unpack them into attributes
        self.filterwheel1 = self._init_results["filterwheel1"]
        self.filterwheel2 = self._init_results["filterwheel2"]
        self.laserbox     = self._init_results["laserbox"]
        self.rtc5_board   = self._init_results["rtc5_board"]
        self.pidevice     = self._init_results["pidevice"]


        # Initialize the cameras
        self.number_of_cameras = DCAM.DCAM.get_cameras_number()

        self.single_camera = None
        # if number_of_cameras == 0:
        if self.number_of_cameras == 1:
            self.camera = device_initializations.camera(self, idx=0)
            self.serial_number = self.camera.get_device_info()[2]

            if self.serial_number == "S/N: 302077":
                self.camera_1 = self.camera
                del self.camera
                self.acquisition_thread_1 = Acquisition_Thread(self.camera_1)
                self.single_camera = 1

                self.camera_2 = None

            elif self.serial_number == "S/N: 302079":
                self.camera_2 = self.camera
                del self.camera
                self.acquisition_thread_2 = Acquisition_Thread(self.camera_2)
                self.single_camera = 2

                self.camera_1 = None


        elif self.number_of_cameras == 2:
            self.camera_1 = device_initializations.camera(self, idx=1)
            self.camera_2 = device_initializations.camera(self, idx=0)

            self.acquisition_thread_1 = Acquisition_Thread(self.camera_1)
            self.acquisition_thread_2 = Acquisition_Thread(self.camera_2)



        # #---------------------------------------------------------------------------
        # # Create GUI

        # # # Create a central widget with a grid layout.        
        splitter_layout = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter_layout)
        splitter_layout.setContentsMargins(0, 0, 0, 0)


        # _________________________________________
        # Vertical Layout for Cameras

        cameras_container = QWidget()
        cameras_layout = QVBoxLayout(cameras_container)
        cameras_layout.setContentsMargins(0, 0, 0, 0)
        cameras_layout.setSpacing(0)

        
        # if number_of_cameras == 0:
        if self.number_of_cameras == 1:
            
            if self.single_camera == 1:
                    # Create the first camera widget
                self.camera_widget_2 = None
                self.camera_widget_1 = Camera_Widget(idx=0, label="Camera 1:", acq_thread = self.acquisition_thread_1)
                self.camera_widget_1.setMaximumHeight(300)
                cameras_layout.addWidget(self.camera_widget_1, alignment=Qt.AlignTop)

                    # Create the thread
                self.grabber_1 = FrameGrabberThread(camera=self.camera_1, cam_id=1, interval_ms=50)
                self.grabber_1.frame_ready.connect(self.on_frame_received)
                self.grabber_1.frame_ready.connect(self._on_frame_ready)

                self.camera_widget_1.live_toggled.connect(self.on_camera1_live_toggled)
                self.camera_widget_1.snap_clicked.connect(lambda: self.on_camera1_snap(self.current_save_directory))
                self.camera_widget_1.restart_clicked.connect(self.camera1_restart)
                
                
            elif self.single_camera == 2:
                    # Create the first camera widget
                self.camera_widget_1 = None
                self.camera_widget_2 = Camera_Widget(idx=0, label="Camera 2:", acq_thread = self.acquisition_thread_2)
                self.camera_widget_2.setMaximumHeight(300)
                cameras_layout.addWidget(self.camera_widget_2, alignment=Qt.AlignTop)

                    # Create the thread
                self.grabber_2 = FrameGrabberThread(camera=self.camera_2, cam_id=2, interval_ms=50)
                self.grabber_2.frame_ready.connect(self.on_frame_received)
                self.grabber_2.frame_ready.connect(self._on_frame_ready)

                self.camera_widget_2.live_toggled.connect(self.on_camera2_live_toggled)
                self.camera_widget_2.snap_clicked.connect(lambda: self.on_camera2_snap(self.current_save_directory))
                self.camera_widget_2.restart_clicked.connect(self.camera2_restart)


        elif self.number_of_cameras == 2:
                # Create the first camera widget
            self.camera_widget_1 = Camera_Widget(idx=1, label="Camera 1:", parent=self, acq_thread=self.acquisition_thread_1)
            self.camera_widget_1.setMaximumHeight(300)
            cameras_layout.addWidget(self.camera_widget_1, alignment=Qt.AlignTop)

                # Create the second camera widget
            self.camera_widget_2 = Camera_Widget(idx=0, label="Camera 2:", parent=self, acq_thread=self.acquisition_thread_2)
            self.camera_widget_2.setMaximumHeight(300)
            cameras_layout.addWidget(self.camera_widget_2, alignment=Qt.AlignTop)

                # Create the threads
            self.grabber_1 = FrameGrabberThread(camera=self.camera_1, cam_id=1, interval_ms=75)
            self.grabber_2 = FrameGrabberThread(camera=self.camera_2, cam_id=2, interval_ms=75)

                # Connect the received frames
            self.grabber_1.frame_ready.connect(self.on_frame_received)
            self.grabber_1.frame_ready.connect(self._on_frame_ready)
            self.grabber_2.frame_ready.connect(self.on_frame_received)
            self.grabber_2.frame_ready.connect(self._on_frame_ready)

                # Connect the received button signals
            self.camera_widget_1.live_toggled.connect(self.on_camera1_live_toggled)
            self.camera_widget_1.snap_clicked.connect(lambda: self.on_camera1_snap(self.current_save_directory))
            self.camera_widget_1.restart_clicked.connect(self.camera1_restart)
            self.camera_widget_2.live_toggled.connect(self.on_camera2_live_toggled)
            self.camera_widget_2.snap_clicked.connect(lambda: self.on_camera2_snap(self.current_save_directory))
            self.camera_widget_2.restart_clicked.connect(self.camera2_restart)

        # print("Grabber thread is running:", self.grabber_1.isRunning())

        cameras_layout.addStretch()  # Ensure widgets stay at the top
        
        #_________________________________________
        # Mdi Area for Lasers, Filterwheels, Scanner and Stages

        x_offset = 13
        y_offset = -50

        self.mdi_area = QMdiArea()
        self.mdi_area.setMinimumWidth(800)
        self.mdi_area.setBackground(QBrush(QColor(48, 48, 48))) # Color in hex - #303030

        # Create a label for the microscope's name
        viewport = self.mdi_area.viewport()
        self.fixed_label = QLabel(parent=viewport)
        self.fixed_label.setTextFormat(Qt.RichText)
        self.fixed_label.setText("<i>VitaSlice</i> – ALM's Light-Sheet Microscope")
        self.fixed_label.setStyleSheet("""
            QLabel {
                color: white;
                background-color: rgb(48, 48, 48);
                padding: 4px;
                font-size: 18px;
                font: Roboto;
            }
        """)
        self.fixed_label.move(0, 0)  # adjust padding from top-left
        self.fixed_label.show()

        self.stages_widget = Stages_Widget(self.pidevice, parent=self)
        self.stages_widget.setMaximumWidth(600)
        self.stages_widget.setMaximumHeight(600)
        self.add_widget_at_position(self.stages_widget, "Stages", 631 + x_offset, 373 + y_offset)


        self.scanner_widget = Scanner_Widget(self.rtc5_board, parent=self)
        self.scanner_widget.setMaximumHeight(600)
        self.add_widget_at_position(self.scanner_widget, "Scanner", 634 + x_offset, 114 + y_offset)

        self.filterwheels_widget = Filterwheels_Widget(self.filter_json_data, self.filterwheel1, self.filterwheel2, parent=self)
        self.filterwheels_widget.setMaximumHeight(300)
        self.filterwheels_widget.setMaximumHeight(600)
        self.add_widget_at_position(self.filterwheels_widget, "Filter Wheels", 297 + x_offset, 114 + y_offset)


        self.laser_widget = Lasers_Widget(self.filter_json_data, self.laserbox, parent=self)
        self.laser_widget.setMaximumWidth(600)
        self.laser_widget.setMaximumHeight(350)
        self.add_widget_at_position(self.laser_widget, "Lasers", 16 + x_offset, 326 + y_offset)

        self.file_manager_widget = File_Explorer(start_path=initial_path, parent=self)


        #self.file_manager_widget = File_Explorer(parent=self)
        self.add_widget_at_position(self.file_manager_widget, "File Manager", 573 + x_offset, 731 + y_offset)
        # Initiate the save directory
        self.current_save_directory = self.file_manager_widget.current_path
        self.file_manager_widget.currentPathChanged.connect(self._on_path_changed)


        self.ystack_widget = YStack_Widget(self.file_manager_widget.current_path, self.filterwheel1, self.filterwheel2, 
                                           self.laserbox, self.rtc5_board, self.pidevice, self.camera_1, self.camera_2, 
                                           self.laser_widget, self.scanner_widget, self.camera_widget_1, self.camera_widget_2)
        
        self.add_widget_at_position(self.ystack_widget, "Y-Stack Acquisition", 91 + x_offset, 706 + y_offset)

        # Connect with the Signals
        self.ystack_widget.acquisition_started.connect(self.before_acquisition)
        self.ystack_widget.acquisition_finished.connect(self.enable_devices)
        #self.ystack_widget.frame_acquired.connect(self.on_frame_acquired)

        # Return the remaining devices to their defaults after the Y-Stack
            # Scanner
        self.ystack_widget.acquisition_finished.connect(self.scanner_widget.center_beam_after_ystack)
            # Filter Wheels
        self.ystack_widget.acquisition_finished.connect(self.filterwheels_widget.restore_filters_after_ystack)
            # Lasers
        self.ystack_widget.acquisition_finished.connect(self.laser_widget.turn_all_off)
            # Cameras
        if self.number_of_cameras == 1:
            if self.single_camera == 1:
                self.ystack_widget.acquisition_finished.connect(self.camera_widget_1.apply_parameters_after_ystack)
            elif self.single_camera == 2:
                self.ystack_widget.acquisition_finished.connect(self.camera_widget_2.apply_parameters_after_ystack)
        elif self.number_of_cameras == 2:
            self.ystack_widget.acquisition_finished.connect(self.camera_widget_1.apply_parameters_after_ystack)
            self.ystack_widget.acquisition_finished.connect(self.camera_widget_2.apply_parameters_after_ystack)
        
            
        #_________________________________________
        # Napari Viewer

        self.viewer = napari.Viewer(show=False)

        set_napari_background(self.viewer, "#303030")  # Change background

        qt_napari_window = self.viewer.window._qt_window
        qt_napari_window.setWindowFlags(Qt.Widget)
        qt_napari_window.menuBar().setNativeMenuBar(False)
        qt_napari_window.setMinimumWidth(900)
        qt_napari_window.setMinimumHeight(900)



        # # Set the stylesheet
        splitter_layout.setStyleSheet("""           
            /* ----------- QSplitter ----------- */
            QSplitter {
                background-color: #303030;  /* Background color for the entire splitter */
            }
            QSplitter::handle {
                background-color: #555555;  /* Color for the draggable handle */
                width: 10px;                /* Thickness of the handle for horizontal splitter */
            }
        """)

        # Effectively place the widgets
            # Mdi layout for the devices
        splitter_layout.addWidget(self.mdi_area)
            # Add the left container to the grid (column 0)
        splitter_layout.addWidget(cameras_container)
            # Place the Napari widget in the grid (column 1)
        splitter_layout.addWidget(qt_napari_window)
        
        splitter_layout.setStretchFactor(0, 6)  # QMdiArea (equal priority with cameras)
        splitter_layout.setStretchFactor(1, 2)  # Cameras Container (equal priority with QMdiArea)
        splitter_layout.setStretchFactor(2, 10)  # Napari (Expands the most)

    
    def closeEvent(self, event):

        for sub in self.mdi_area.subWindowList():
            if hasattr(sub, "inner_widget") and hasattr(sub.inner_widget, "shutdown"):
                sub.inner_widget.shutdown()
        
        device_closings.filterwheel_closing(self.filterwheel1)
        device_closings.filterwheel_closing(self.filterwheel2)
        device_closings.scanner_closing(self.rtc5_board)

        self.laserbox.query("SOURce2:AM:STATe OFF")
        self.laserbox.query("SOURce3:AM:STATe OFF")
        self.laserbox.query("SOURce4:AM:STATe OFF")
        self.laserbox.query("SOURce5:AM:STATe OFF")
        device_closings.laserbox_closing(self.laserbox)
        

        device_closings.stages_closing(self.pidevice)
        
        self.pidevice = None

        if self.single_camera == None:
            self.camera_widget_1.shutdown()
            self.camera_widget_2.shutdown()

        elif self.single_camera == 1:
            self.camera_widget_1.shutdown()

        elif self.single_camera == 2:
            self.camera_widget_2.shutdown()

        event.accept()
        


#######################################################################################

in_path = r"C:\Users\ALM_Light_Sheet\Desktop\testes_acqs"

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("ALM.ico"))
    app.setApplicationDisplayName("")

    # 1. Initialize the software, and choose the path
    dlg = ALM_Launcher()
    if dlg.exec() != QDialog.Accepted:
        sys.exit(0)    

    # 2. After this open the software
    main_window = ALM_Lightsheet(initial_path=dlg.selected_path)#)
    main_window.showMaximized()
    sys.exit(app.exec())