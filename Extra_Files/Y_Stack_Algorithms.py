import os
import shutil
import numpy as np
import json
import zarr
from ome_zarr.io import parse_url
from ome_zarr.writer import write_multiscales_metadata, write_image
from ome_zarr.format import FormatV04
from zarr.storage import DirectoryStore

from pathlib import Path

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

# Cameras
from pylablib.devices import DCAM

import time

from pathlib import Path

import numpy as np
from pathlib import Path
import zarr
from ome_zarr.writer import write_image, write_multiscales_metadata, write_multiscale
from ome_zarr.format import FormatV04
from ome_zarr.scale import Scaler
from skimage.transform import downscale_local_mean

import numpy as np
import zarr
from zarr.convenience import copy
from skimage.transform import downscale_local_mean
from ome_zarr.writer import write_multiscales_metadata
from ome_zarr.format import FormatV04
from pathlib import Path
from zarr.convenience import copy
from zarr import group, Blosc
from zarr.storage import DirectoryStore


class y_stack():

    #################################################################################
    # For the lY Stack first

    def camera_parameters(self, camera, dynamic_range, binning, format_width_x, format_height_y, single_stack_n_frames):
        """Function that defines a single camera's parameters and starts the acquisition"""

        # 0) Convert the Dynamic Range parameter for input
        if dynamic_range == 8:
            dynamic_range = 1
        elif dynamic_range == 16:
            dynamic_range = 2

        roi_x_start = (2048 - format_width_x) // 2
        roi_y_start = (2048 - format_height_y) // 2
        roi_x_end = roi_x_start + format_width_x
        roi_y_end = roi_y_start + format_height_y


        # 1) stop acquisition and clear the camera
        camera.stop_acquisition()
        camera.clear_acquisition()

        time.sleep(1)

        # 3) arrange the External Trigger Mode
        camera.set_trigger_mode("ext")
        camera.set_attribute_value("TRIGGER ACTIVE", 2)
        camera.set_attribute_value("TRIGGER POLARITY", 2)
        camera.set_attribute_value("TRIGGER GLOBAL EXPOSURE", 5)

        # 4) Set the parameters
        camera.set_attribute_value("IMAGE PIXEL TYPE", dynamic_range)
        camera.set_roi(roi_x_start, roi_x_end, roi_y_start, roi_y_end, binning, binning)


        # 5) Set up the camera for acquisition
        camera._allocate_buffer(single_stack_n_frames)
        camera.setup_acquisition(mode="sequence", nframes=single_stack_n_frames)
        camera.start_acquisition()

    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


    def mark_toptobottom(self, board, Xtop, Xbottom, speed):
        """Function that scans the laser through the FOV, exposing the camera at the same time"""

        Zi = Xtop
        Yi = 0
        Zf = Xbottom
        Yf = 0

        board.set_start_list(1)

        board.set_jump_speed(ctypes.c_double(800000))
        board.set_mark_speed(ctypes.c_double(speed))

        board.jump_abs(ctypes.c_int(Zi), ctypes.c_int(Yi))
        board.mark_abs(ctypes.c_int(Zf), ctypes.c_int(Yf))

        board.set_end_of_list()

        board.execute_list(1)


    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def _interruptible_sleep(self, duration, stop_event):
        """
        Wait up to `duration` seconds, but return immediately if stop_event is set.
        Returns True if the wait was cut short (i.e. stop_event was set), False otherwise.
        """
        return stop_event.wait(duration)
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


    def lY_stack(self,
                Yis, Yfs, Y_spacings,
                Xs, Zs, Thetas,
                Time_points, Time_spacings, Time_step_units,
                filterwheel1, filterwheel2, laserbox, rtc5_board, pidevice, camera1, camera2, selected_cameras,
                lasers, laser_powers_W,
                filters1, filters2,
                camera1_format_x, camera1_format_y, camera1_binning, camera1_dynamic_range,
                camera2_format_x, camera2_format_y, camera2_binning, camera2_dynamic_range,
                scan_top, scan_bottom, mark_speed,
                save_dir,
                slice_callback=None, channel_callback=None, timepoint_callback=None, position_callback=None,
                stop_event=None):
        """Function that performs Y Stacks with the Lambda-Y order, doing all time points in a single position, and then moving on to the next"""
        
        #.................................................................................................................
        # Setup the acquisition

        nr_positions = len(Yis)

        for pos_idx in range(nr_positions):

            if position_callback:
                position_callback(pos_idx+1, nr_positions)

            # Create the directory for this position
            acq_name = f"Position {pos_idx+1}"
            acq_dir = os.path.join(save_dir, acq_name)
            os.makedirs(acq_dir, exist_ok=True)

            # Get the positions from the parameters
            Y_spacing = Y_spacings[pos_idx]
            Yi = Yis[pos_idx]
            Yf = Yfs[pos_idx]
            X = Xs[pos_idx]
            Z = Zs[pos_idx]
            theta = Thetas[pos_idx]

            # Get the correct time dimensions
            time_points = Time_points[pos_idx]
            time_spacing = Time_spacings[pos_idx]
            time_step_unit = Time_step_units[pos_idx]

            # Correct t points
            if time_points == 0:
                time_points = 1


            # Convert the time step into seconds:
            if time_step_unit == "seconds":
                pass
            elif time_step_unit == "minutes":
                time_spacing *= 60
            elif time_step_unit == "hours":
                time_spacing *= 60*60
            elif time_step_unit == "days":
                time_spacing *= 60*60*24

            # Calculate the number of steps
            if Y_spacing == 0 or Yi == Yf:
                Y_steps = 1
            else:
                N_steps = int ( np.floor( np.round( abs(Yf - Yi) / Y_spacing) ) ) or 1
                Y_steps = int(N_steps+1)

            print()
            print(f"N_frames: {Y_steps}")

            # Get the number of selected Lasers
            nr_lasers = len(lasers)

            # Construct the array of Ys
            if Y_spacing == 0 or Yi == Yf:
                Ys = np.array([Yi, Yi], float)
            elif Yf > Yi:
                Yf_real = Yi + N_steps * Y_spacing
                Ys = np.linspace(Yi, Yf_real, Y_steps)
            elif Yi > Yf:
                Yf_real = Yi - N_steps * Y_spacing
                Ys = np.linspace(Yi, Yf_real, Y_steps)

            # Make sure theta is in [0, 360] degrees
            theta = theta % 360

            # Move to the correct X ('1'), Z ('3') and Theta ('4') position
            pidevice.MOV('1', X)
            pitools.waitontarget(pidevice, axes=['1'])
            pidevice.MOV('3', Z)
            pitools.waitontarget(pidevice, axes=['3'])
            pidevice.MOV('4', theta)
            pitools.waitontarget(pidevice, axes=['4'])

            #.................................................................................................................
            # Effectively start the acquisition

            # Selected Cameras:
            # 0 - Both
            # 1 - only Camera 1
            # 2 - only Camera 2

            # Both Cameras
            if selected_cameras == 0:

                # Effective Format of the Images
                camera1_effective_format_x = int(camera1_format_x / camera1_binning)
                camera1_effective_format_y = int(camera1_format_y / camera1_binning)
                camera2_effective_format_x = int(camera2_format_x / camera2_binning)
                camera2_effective_format_y = int(camera2_format_y / camera2_binning)

                # Create the zarr storage for both Cameras
                store_path1 = Path(acq_dir) / f"Position{pos_idx+1}_Camera1.ome.zarr"
                store1 = DirectoryStore(str(store_path1))
                root1 = group(store=store1, overwrite=True)

                store_path2 = Path(acq_dir) / f"Position{pos_idx+1}_Camera2.ome.zarr"
                store2 = DirectoryStore(str(store_path2))
                root2 = group(store=store2, overwrite=True)

                full_array1 = root1.create_dataset(
                    name="0",
                    shape=(time_points, nr_lasers, Y_steps, camera1_effective_format_y, camera1_effective_format_x),
                    chunks=(1, 1, 1, camera1_effective_format_y, camera1_effective_format_x),
                    dtype = "uint16" if camera1_dynamic_range == 16 else "uint8",
                    compressor=Blosc()
                )
                full_array2 = root2.create_dataset(
                    name="0",
                    shape=(time_points, nr_lasers, Y_steps, camera2_effective_format_y, camera2_effective_format_x),
                    chunks=(1, 1, 1, camera2_effective_format_y, camera2_effective_format_x),
                    dtype = "uint16" if camera2_dynamic_range == 16 else "uint8",
                    compressor=Blosc()
                )
                
                # Loop to iterate over the time points
                for i in range(time_points):

                    # Loop to iterate over the Lasers
                    for j in range(nr_lasers):

                        # Set the correct parameters on both Cameras and start acquisition
                        # For just 1 Stack. For just 1 Laser
                        self.camera_parameters(camera1, camera1_dynamic_range, camera1_binning, camera1_format_x, camera1_format_y, Y_steps)
                        self.camera_parameters(camera2, camera2_dynamic_range, camera2_binning, camera2_format_x, camera2_format_y, Y_steps)
                        
                        # Change the filters for both Cameras
                        filterwheel1.set_position(filters1[j])
                        filterwheel2.set_position(filters2[j])

                        # Loop to iterate over the Y positions
                        k = 0     # This is the index of the Y positions, and the number of acquired frames
                        while k < Y_steps:

                            # stop check
                            if stop_event and stop_event.is_set():
                                return [i, j, k]  # unwind immediately
                            #----------------

                            # Move the stage
                            pidevice.MOV('2', Ys[k])
                            pitools.waitontarget(pidevice, axes=['2'])

                            # Information emission and stop check
                            if stop_event.is_set():
                                return [i, j, k]
                            if channel_callback:
                                channel_callback(j+1, nr_lasers)
                            if timepoint_callback:
                                timepoint_callback(i+1, time_points)
                            #----------------

                            if k == 0:
                                # Turn ON the laser
                                if laser_powers_W[j] == 0:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")
                                else:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe ON")
                                    laserbox.write(f"SOURce{lasers[j]}:POWer:LEVel:IMMediate:AMPLitude %.5f" % laser_powers_W[j])
                                if self._interruptible_sleep(0.3, stop_event):    # wait 300 ms for the laser to turn ON
                                    return [i, j, k]
                                
                            # Wait for the previous frame to reach memory
                            while (camera1.get_frames_status()[0] < k) or (camera2.get_frames_status()[0] < k):
                                if self._interruptible_sleep(0.001, stop_event):
                                    return [i, j, k]
                            
                            # Mark and acquire
                            self.mark_toptobottom(rtc5_board, scan_top, scan_bottom, mark_speed)

                            # Add a frame to the counter
                            k += 1

                            # information emission
                            if slice_callback:
                                slice_callback(k, Y_steps)

                        # Wait for the frames
                        while (camera1.get_frames_status()[0] < Y_steps) or (camera2.get_frames_status()[0] < Y_steps):
                            if self._interruptible_sleep(0.001, stop_event):
                                return [i, j, k]

                        # After using this laser, turn it OFF
                        laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")

                        # Initialize frame counters for both cameras - 1 to miss the dummy frame
                        camera1_frame_counter = 0
                        camera2_frame_counter = 0

                        # Define batch size
                        batch_size = 100

                        if Y_steps > batch_size:

                            # Loop to read frames in batches
                            for k_start in range(0, Y_steps, batch_size):
                                k_end = min(k_start + batch_size, Y_steps)
                                n_frames = k_end - k_start

                                # Calculate the range of frames to read
                                rng1 = (camera1_frame_counter, camera1_frame_counter + n_frames)
                                rng2 = (camera2_frame_counter, camera2_frame_counter + n_frames)

                                # Read frames using the calculated ranges
                                batch1 = camera1.read_multiple_images(rng=rng1)
                                batch2 = camera2.read_multiple_images(rng=rng2)

                                # Update the full arrays with the new batches
                                full_array1[i, j, k_start:k_end, :, :] = batch1
                                full_array2[i, j, k_start:k_end, :, :] = batch2

                                # Update frame counters
                                camera1_frame_counter += n_frames
                                camera2_frame_counter += n_frames

                        else:

                            full_array1[i,j,:,:,:] = camera1.read_multiple_images(rng=(0,Y_steps))
                            full_array2[i,j,:,:,:] = camera2.read_multiple_images(rng=(0,Y_steps))

                    
                        # Clear the Cameras for another Stack
                        camera1.stop_acquisition()
                        camera1.clear_acquisition()
                        camera2.stop_acquisition()
                        camera2.clear_acquisition()


                    # Stop the system for the Time Spacing
                    if i == time_points - 1:
                        time_spacing = 0
                    if self._interruptible_sleep(time_spacing, stop_event):
                        return [i, j, k]

                print(full_array1.shape, full_array2.shape)
                

            #------------------------------------------------------------------------------------------------------------------------------------
            # Just Camera 1
            elif selected_cameras == 1:

                # Effective Format of the Images
                camera1_effective_format_x = int(camera1_format_x / camera1_binning)
                camera1_effective_format_y = int(camera1_format_y / camera1_binning)

                # Create the zarr storage for both Cameras
                store_path1 = Path(acq_dir) / f"Position{pos_idx+1}_Camera1.ome.zarr"
                store1 = DirectoryStore(str(store_path1))
                root1 = group(store=store1, overwrite=True)

                full_array1 = root1.create_dataset(
                    name="0",
                    shape=(time_points, nr_lasers, Y_steps, camera1_effective_format_y, camera1_effective_format_x),
                    chunks=(1, 1, 1, camera1_effective_format_y, camera1_effective_format_x),
                    dtype = "uint16" if camera1_dynamic_range == 16 else "uint8",
                    compressor=Blosc()
                )

                # Loop to iterate over the Time positions
                for i in range(time_points):

                    # Loop to iterate over the Lasers
                    for j in range(nr_lasers):

                        # Set the correct parameters on both Cameras and start acquisition
                        # For just 1 Stack. For just 1 Laser
                        self.camera_parameters(camera1, camera1_dynamic_range, camera1_binning, camera1_format_x, camera1_format_y, Y_steps)
                        if self._interruptible_sleep(1, stop_event):
                            return [i, j, k]

                        # Change the filters for both Cameras
                        filterwheel1.set_position(filters1[j])

                        # Loop to iterate over the Y positions
                        k = 0     # This is the index of the Y positions, and the number of acquired frames
                        while k < Y_steps:

                            if stop_event.is_set():
                                return [i, j, k]  
                            
                            # Move the stage
                            pidevice.MOV('2', Ys[k])
                            pitools.waitontarget(pidevice, axes=['2'])

                            # Information emission and stop check
                            if stop_event.is_set():
                                return [i, j, k]
                            if channel_callback:
                                channel_callback(j+1, nr_lasers)
                            if timepoint_callback:
                                timepoint_callback(i+1, time_points)
                            #----------------


                            if k == 0:
                                # Turn ON the laser
                                if laser_powers_W[j] == 0:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")
                                else:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe ON")
                                    laserbox.write(f"SOURce{lasers[j]}:POWer:LEVel:IMMediate:AMPLitude %.5f" % laser_powers_W[j])
                                if self._interruptible_sleep(0.3, stop_event):    # wait 300 ms for the laser to turn ON
                                    return [i, j, k]

                            # Wait for the previous frame to reach memory
                            while (camera1.get_frames_status()[0] < k):
                                if self._interruptible_sleep(0.001, stop_event):
                                    return [i, j, k]
                                
                            # Mark and acquire
                            self.mark_toptobottom(rtc5_board, scan_top, scan_bottom, mark_speed)

                            # Add a frame to the counter
                            k += 1

                            # information emission
                            if slice_callback:
                                slice_callback(k, Y_steps)

                        #print(camera1.get_frames_status())

                        # Wait for the very last frame
                        while (camera1.get_frames_status()[0] < Y_steps):
                            #print(camera1.get_frames_status())
                            if self._interruptible_sleep(0.001, stop_event):
                                return [i, j, k]
                            
                        # After using this laser, turn it OFF
                        laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")

                        # Initialize frame counters for both cameras - 0 to miss the dummy frame
                        camera1_frame_counter = 0

                        # Define batch size
                        batch_size = 250

                        if Y_steps > batch_size:
                            # Loop to read frames in batches
                            for k_start in range(0, Y_steps, batch_size):

                                k_end = min(k_start + batch_size, Y_steps)
                                n_frames = k_end - k_start

                                # Calculate the range of frames to read
                                rng1 = (camera1_frame_counter, camera1_frame_counter + n_frames)

                                # Read frames using the calculated ranges
                                batch1 = camera1.read_multiple_images(rng=rng1)

                                # Update the full arrays with the new batches
                                full_array1[i, j, k_start:k_end, :, :] = batch1

                                # Update frame counters
                                camera1_frame_counter += n_frames

                        else:
                            full_array1[i,j,:,:,:] = camera1.read_multiple_images(rng=(0,Y_steps))

                    
                        # Clear the Cameras for another Stack
                        camera1.stop_acquisition()
                        camera1.clear_acquisition()


                    # Stop the system for the Time Spacing
                    if i == time_points - 1:
                        time_spacing = 0
                    if self._interruptible_sleep(time_spacing, stop_event):
                        return [i, j, k]
                    
                print(full_array1.shape)
                
            

            #------------------------------------------------------------------------------------------------------------------------------------
            # Just Camera 2
            elif selected_cameras == 2:

                # Effective Format of the Images
                camera2_effective_format_x = int(camera2_format_x / camera2_binning)
                camera2_effective_format_y = int(camera2_format_y / camera2_binning)

                store_path2 = Path(acq_dir) / f"Position{pos_idx+1}_Camera2.ome.zarr"
                store2 = DirectoryStore(str(store_path2))
                root2 = group(store=store2, overwrite=True)

                full_array2 = root2.create_dataset(
                    name="0",
                    shape=(time_points, nr_lasers, Y_steps, camera2_effective_format_y, camera2_effective_format_x),
                    chunks=(1, 1, 1, camera2_effective_format_y, camera2_effective_format_x),
                    dtype = "uint16" if camera2_dynamic_range == 16 else "uint8",
                    compressor=Blosc()
                )

                # Loop to iterate over the Time positions
                for i in range(time_points):

                    # Loop to iterate over the Lasers
                    for j in range(nr_lasers):

                        # Set the correct parameters on both Cameras and start acquisition
                        # For just 1 Stack. For just 1 Laser
                        self.camera_parameters(camera2, camera2_dynamic_range, camera2_binning, camera2_format_x, camera2_format_y, Y_steps)

                        # Change the filters for both Cameras
                        filterwheel2.set_position(filters2[j])

                        # Loop to iterate over the Y positions
                        k = 0     # This is the index of the Y positions, and the number of acquired frames
                        while k < Y_steps:

                            if stop_event.is_set():
                                return [i, j, k]
                            
                            # Move the stage
                            pidevice.MOV('2', Ys[k])
                            pitools.waitontarget(pidevice, axes=['2'])

                            # Information emission and stop check
                            if stop_event.is_set():
                                return [i, j, k]
                            if channel_callback:
                                channel_callback(j+1, nr_lasers)
                            if timepoint_callback:
                                timepoint_callback(i+1, time_points)
                            #----------------

                            if k == 0:
                                # Turn ON the laser
                                if laser_powers_W[j] == 0:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")
                                else:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe ON")
                                    laserbox.write(f"SOURce{lasers[j]}:POWer:LEVel:IMMediate:AMPLitude %.5f" % laser_powers_W[j])
                                if self._interruptible_sleep(0.3, stop_event):    # wait 300 ms for the laser to turn ON
                                    return [i, j, k]
                                
                            # Wait for the previous frame to reach memory
                            while (camera2.get_frames_status()[0] < k):
                                if self._interruptible_sleep(0.001, stop_event):
                                    return [i, j, k]
                            
                            # Mark and acquire
                            self.mark_toptobottom(rtc5_board, scan_top, scan_bottom, mark_speed)

                            # Add a frame to the counter
                            k += 1

                            # information emission
                            if slice_callback:
                                slice_callback(k, Y_steps)

                        #print(camera2.get_frames_status())

                        # Wait for the very last frame
                        while (camera2.get_frames_status()[0] < Y_steps):
                            if self._interruptible_sleep(0.001, stop_event):
                                return [i, j, k]
                            
                        # After using this laser, turn it OFF
                        laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")

                        # Initialize frame counters for both cameras - 0 to miss the dummy frame
                        camera2_frame_counter = 0

                        # Define batch size
                        batch_size = 250

                        if Y_steps > batch_size:
                            # Loop to read frames in batches
                            for k_start in range(0, Y_steps, batch_size):

                                k_end = min(k_start + batch_size, Y_steps)
                                n_frames = k_end - k_start

                                # Calculate the range of frames to read
                                rng2 = (camera2_frame_counter, camera2_frame_counter + n_frames)

                                # Read frames using the calculated ranges
                                batch2 = camera2.read_multiple_images(rng=rng2)

                                # Update the full arrays with the new batches
                                full_array2[i, j, k_start:k_end, :, :] = batch2

                                # Update frame counters
                                camera2_frame_counter += n_frames

                        else:
                            full_array2[i,j,:,:,:] = camera2.read_multiple_images(rng=(0,Y_steps))

                        # Clear the Cameras for another Stack
                        camera2.stop_acquisition()
                        camera2.clear_acquisition()

                    # Stop the system for the Time Spacing
                    if i == time_points - 1:
                        time_spacing = 0
                    if self._interruptible_sleep(time_spacing, stop_event):
                        return [i, j, k]

                print(full_array2.shape)
            
        
#############################################################################################################################################

    def lY_stack_sametimepoints(self,
                Yis, Yfs, Y_spacings,
                Xs, Zs, Thetas,
                time_points, time_spacing, time_step_unit,
                filterwheel1, filterwheel2, laserbox, rtc5_board, pidevice, camera1, camera2, selected_cameras,
                lasers, laser_powers_W,
                filters1, filters2,
                camera1_format_x, camera1_format_y, camera1_binning, camera1_dynamic_range,
                camera2_format_x, camera2_format_y, camera2_binning, camera2_dynamic_range,
                scan_top, scan_bottom, mark_speed,
                save_dir,
                slice_callback=None, channel_callback=None, timepoint_callback=None, position_callback=None,
                stop_event=None):
        """Function that performs Y Stacks with the Lambda-Y order, doing all multi-positions in a single time point."""
        
        
        #.................................................................................................................
        # Setup the acquisition

        # Correct t points
        if time_points == 0:
            time_points = 1

        # Convert the time step into seconds:
        if time_step_unit == "seconds":
            pass
        elif time_step_unit == "minutes":
            time_spacing *= 60
        elif time_step_unit == "hours":
            time_spacing *= 60*60
        elif time_step_unit == "days":
            time_spacing *= 60*60*24

        nr_positions = len(Yis)


        # Loop to iterate over the Time positions
        for i in range(time_points):

            # Loop to iterate over the multi-positions
            for pos_idx in range(nr_positions):

                if position_callback:
                    position_callback(pos_idx+1, nr_positions)

                # Create the directory for this position
                acq_name = f"Position {pos_idx+1}"
                acq_dir = os.path.join(save_dir, acq_name)
                os.makedirs(acq_dir, exist_ok=True)

                # Get the positions from the parameters
                Y_spacing = Y_spacings[pos_idx]
                Yi = Yis[pos_idx]
                Yf = Yfs[pos_idx]
                X = Xs[pos_idx]
                Z = Zs[pos_idx]
                theta = Thetas[pos_idx]

                # Calculate the number of steps
                if Y_spacing == 0 or Yi == Yf:
                    Y_steps = 1
                else:
                    N_steps = int ( np.floor( np.round( abs(Yf - Yi) / Y_spacing) ) ) or 1
                    Y_steps = int(N_steps+1)

                print()
                print(f"N_frames: {Y_steps}")

                # Get the number of selected Lasers
                nr_lasers = len(lasers)

                # Construct the array of Ys
                if Y_spacing == 0 or Yi == Yf:
                    Ys = np.array([Yi, Yi], float)
                elif Yf > Yi:
                    Yf_real = Yi + N_steps * Y_spacing
                    Ys = np.linspace(Yi, Yf_real, Y_steps)
                elif Yi > Yf:
                    Yf_real = Yi - N_steps * Y_spacing
                    Ys = np.linspace(Yi, Yf_real, Y_steps)


                # Make sure theta is in [0, 360] degrees
                theta = theta % 360

                # Move to the correct X ('1'), Z ('3') and Theta ('4') position
                pidevice.MOV('1', X)
                pitools.waitontarget(pidevice, axes=['1'])
                pidevice.MOV('3', Z)
                pitools.waitontarget(pidevice, axes=['3'])
                pidevice.MOV('4', theta)
                pitools.waitontarget(pidevice, axes=['4'])

                #.................................................................................................................
                # Effectively start the acquisition

                # Selected Cameras:
                # 0 - Both
                # 1 - only Camera 1
                # 2 - only Camera 2

                # Both Cameras
                if selected_cameras == 0:

                    # Effective Format of the Images
                    camera1_effective_format_x = int(camera1_format_x / camera1_binning)
                    camera1_effective_format_y = int(camera1_format_y / camera1_binning)
                    camera2_effective_format_x = int(camera2_format_x / camera2_binning)
                    camera2_effective_format_y = int(camera2_format_y / camera2_binning)

                    if i == 0: # Only create the arrays in the first time

                        # Create the zarr storage for both Cameras
                        store_path1 = Path(acq_dir) / f"Position{pos_idx+1}_Camera1.ome.zarr"
                        store1 = DirectoryStore(str(store_path1))
                        root1 = group(store=store1, overwrite=True)

                        store_path2 = Path(acq_dir) / f"Position{pos_idx+1}_Camera2.ome.zarr"
                        store2 = DirectoryStore(str(store_path2))
                        root2 = group(store=store2, overwrite=True)

                        full_array1 = root1.create_dataset(
                            name="0",
                            shape=(time_points, nr_lasers, Y_steps, camera1_effective_format_y, camera1_effective_format_x),
                            chunks=(1, 1, 1, camera1_effective_format_y, camera1_effective_format_x),
                            dtype = "uint16" if camera1_dynamic_range == 16 else "uint8",
                            compressor=Blosc()
                        )
                        full_array2 = root2.create_dataset(
                            name="0",
                            shape=(time_points, nr_lasers, Y_steps, camera2_effective_format_y, camera2_effective_format_x),
                            chunks=(1, 1, 1, camera2_effective_format_y, camera2_effective_format_x),
                            dtype = "uint16" if camera2_dynamic_range == 16 else "uint8",
                            compressor=Blosc()
                        )

                    else:
                        # re-opens the same stores and grabs the dataset
                        store_path1 = Path(acq_dir) / f"Position{pos_idx+1}_Camera1.ome.zarr"
                        store_path2 = Path(acq_dir) / f"Position{pos_idx+1}_Camera2.ome.zarr"
                        
                        root1 = group(store=DirectoryStore(str(store_path1)), overwrite=False)
                        root2 = group(store=DirectoryStore(str(store_path2)), overwrite=False)

                        full_array1 = root1["0"]
                        full_array2 = root2["0"]

                    # Loop to iterate over the Lasers
                    for j in range(nr_lasers):

                        # Set the correct parameters on both Cameras and start acquisition
                        # For just 1 Stack. For just 1 Laser
                        self.camera_parameters(camera1, camera1_dynamic_range, camera1_binning, camera1_format_x, camera1_format_y, Y_steps)
                        self.camera_parameters(camera2, camera2_dynamic_range, camera2_binning, camera2_format_x, camera2_format_y, Y_steps)
                        
                        # Change the filters for both Cameras
                        filterwheel1.set_position(filters1[j])
                        filterwheel2.set_position(filters2[j])

                        # Loop to iterate over the Y positions
                        k = 0     # This is the index of the Y positions, and the number of acquired frames
                        while k < Y_steps:

                            # stop check
                            if stop_event and stop_event.is_set():
                                return [i, j, k]  # unwind immediately
                            #----------------

                            # Move the stage
                            pidevice.MOV('2', Ys[k])
                            pitools.waitontarget(pidevice, axes=['2'])

                            # Information emission and stop check
                            if stop_event.is_set():
                                return [i, j, k]
                            if channel_callback:
                                channel_callback(j+1, nr_lasers)
                            if timepoint_callback:
                                timepoint_callback(i+1, time_points)
                            #----------------

                            if k == 0:
                                # Turn ON the laser
                                if laser_powers_W[j] == 0:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")
                                else:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe ON")
                                    laserbox.write(f"SOURce{lasers[j]}:POWer:LEVel:IMMediate:AMPLitude %.5f" % laser_powers_W[j])
                                if self._interruptible_sleep(0.3, stop_event):    # wait 300 ms for the laser to turn ON
                                    return [i, j, k]
                                
                            # Wait for the previous frame to reach memory
                            while (camera1.get_frames_status()[0] < k) or (camera2.get_frames_status()[0] < k):
                                if self._interruptible_sleep(0.001, stop_event):
                                    return [i, j, k]
                            
                            # Mark and acquire
                            self.mark_toptobottom(rtc5_board, scan_top, scan_bottom, mark_speed)

                            # Add a frame to the counter
                            k += 1

                            # information emission
                            if slice_callback:
                                slice_callback(k, Y_steps)

                        # Wait for the last frames
                        while (camera1.get_frames_status()[0] < Y_steps) or (camera2.get_frames_status()[0] < Y_steps):
                            if self._interruptible_sleep(0.001, stop_event):
                                return [i, j, k]

                        # After using this laser, turn it OFF
                        laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")

                        # Initialize frame counters for both cameras
                        camera1_frame_counter = 0
                        camera2_frame_counter = 0

                        # Define batch size
                        batch_size = 100

                        if Y_steps > batch_size:

                            # Loop to read frames in batches
                            for k_start in range(0, Y_steps, batch_size):
                                k_end = min(k_start + batch_size, Y_steps)
                                n_frames = k_end - k_start

                                # Calculate the range of frames to read
                                rng1 = (camera1_frame_counter, camera1_frame_counter + n_frames)
                                rng2 = (camera2_frame_counter, camera2_frame_counter + n_frames)

                                # Read frames using the calculated ranges
                                batch1 = camera1.read_multiple_images(rng=rng1)
                                batch2 = camera2.read_multiple_images(rng=rng2)

                                # Update the full arrays with the new batches
                                full_array1[i, j, k_start:k_end, :, :] = batch1
                                full_array2[i, j, k_start:k_end, :, :] = batch2

                                # Update frame counters
                                camera1_frame_counter += n_frames
                                camera2_frame_counter += n_frames

                        else:

                            full_array1[i,j,:,:,:] = camera1.read_multiple_images(rng=(0,Y_steps))
                            full_array2[i,j,:,:,:] = camera2.read_multiple_images(rng=(0,Y_steps))

                        
                        # Clear the Cameras for another Stack
                        camera1.stop_acquisition()
                        camera1.clear_acquisition()
                        camera2.stop_acquisition()
                        camera2.clear_acquisition()

                    print(full_array1.shape, full_array2.shape)

                ##################################################################################
                # Only Camera 1
                if selected_cameras == 1:

                    # Effective Format of the Images
                    camera1_effective_format_x = int(camera1_format_x / camera1_binning)
                    camera1_effective_format_y = int(camera1_format_y / camera1_binning)

                    if i == 0: # Only create the arrays in the first time

                        # Create the zarr storage for both Cameras
                        store_path1 = Path(acq_dir) / f"Position{pos_idx+1}_Camera1.ome.zarr"
                        store1 = DirectoryStore(str(store_path1))
                        root1 = group(store=store1, overwrite=True)

                        full_array1 = root1.create_dataset(
                            name="0",
                            shape=(time_points, nr_lasers, Y_steps, camera1_effective_format_y, camera1_effective_format_x),
                            chunks=(1, 1, 1, camera1_effective_format_y, camera1_effective_format_x),
                            dtype = "uint16" if camera1_dynamic_range == 16 else "uint8",
                            compressor=Blosc()
                        )

                    else:
                        # re-opens the same stores and grabs the dataset
                        store_path1 = Path(acq_dir) / f"Position{pos_idx+1}_Camera1.ome.zarr"
                        root1 = group(store=DirectoryStore(str(store_path1)), overwrite=False)
                        full_array1 = root1["0"]

                    # Loop to iterate over the Lasers
                    for j in range(nr_lasers):

                        # Set the correct parameters on both Cameras and start acquisition
                        # For just 1 Stack. For just 1 Laser
                        self.camera_parameters(camera1, camera1_dynamic_range, camera1_binning, camera1_format_x, camera1_format_y, Y_steps)
                        
                        # Change the filters for both Cameras
                        filterwheel1.set_position(filters1[j])

                        # Loop to iterate over the Y positions
                        k = 0     # This is the index of the Y positions, and the number of acquired frames
                        while k < Y_steps:

                            # stop check
                            if stop_event and stop_event.is_set():
                                return [i, j, k]  # unwind immediately
                            #----------------

                            # Move the stage
                            pidevice.MOV('2', Ys[k])
                            pitools.waitontarget(pidevice, axes=['2'])

                            # Information emission and stop check
                            if stop_event.is_set():
                                return [i, j, k]
                            if channel_callback:
                                channel_callback(j+1, nr_lasers)
                            if timepoint_callback:
                                timepoint_callback(i+1, time_points)
                            #----------------

                            if k == 0:
                                # Turn ON the laser
                                if laser_powers_W[j] == 0:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")
                                else:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe ON")
                                    laserbox.write(f"SOURce{lasers[j]}:POWer:LEVel:IMMediate:AMPLitude %.5f" % laser_powers_W[j])
                                if self._interruptible_sleep(0.3, stop_event):    # wait 300 ms for the laser to turn ON
                                    return [i, j, k]
                                
                            # Wait for the previous frame to reach memory
                            while (camera1.get_frames_status()[0] < k):
                                if self._interruptible_sleep(0.001, stop_event):
                                    return [i, j, k]
                            
                            # Mark and acquire
                            self.mark_toptobottom(rtc5_board, scan_top, scan_bottom, mark_speed)

                            # Add a frame to the counter
                            k += 1

                            # information emission
                            if slice_callback:
                                slice_callback(k, Y_steps)

                        # Wait for the last frame
                        while (camera1.get_frames_status()[0] < Y_steps):
                            if self._interruptible_sleep(0.001, stop_event):
                                return [i, j, k]

                        # After using this laser, turn it OFF
                        laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")

                        # Initialize frame counters for both camera
                        camera1_frame_counter = 0

                        # Define batch size
                        batch_size = 100

                        if Y_steps > batch_size:

                            # Loop to read frames in batches
                            for k_start in range(0, Y_steps, batch_size):
                                k_end = min(k_start + batch_size, Y_steps)
                                n_frames = k_end - k_start

                                # Calculate the range of frames to read
                                rng1 = (camera1_frame_counter, camera1_frame_counter + n_frames)

                                # Read frames using the calculated ranges
                                batch1 = camera1.read_multiple_images(rng=rng1)

                                # Update the full arrays with the new batches
                                full_array1[i, j, k_start:k_end, :, :] = batch1

                                # Update frame counters
                                camera1_frame_counter += n_frames

                        else:

                            full_array1[i,j,:,:,:] = camera1.read_multiple_images(rng=(0,Y_steps))

                        
                        # Clear the Cameras for another Stack
                        camera1.stop_acquisition()
                        camera1.clear_acquisition()

                    print(full_array1.shape)

                #####################################################################################
                # Only Camera 2

                if selected_cameras == 2:

                    # Effective Format of the Images
                    camera2_effective_format_x = int(camera2_format_x / camera2_binning)
                    camera2_effective_format_y = int(camera2_format_y / camera2_binning)

                    if i == 0: # Only create the arrays in the first time

                        # Create the zarr storage for Camera 2
                        store_path2 = Path(acq_dir) / f"Position{pos_idx+1}_Camera2.ome.zarr"
                        store2 = DirectoryStore(str(store_path2))
                        root2 = group(store=store2, overwrite=True)

                        full_array2 = root2.create_dataset(
                            name="0",
                            shape=(time_points, nr_lasers, Y_steps, camera2_effective_format_y, camera2_effective_format_x),
                            chunks=(1, 1, 1, camera2_effective_format_y, camera2_effective_format_x),
                            dtype = "uint16" if camera2_dynamic_range == 16 else "uint8",
                            compressor=Blosc()
                        )

                    else:
                        # re-opens the same stores and grabs the dataset
                        store_path2 = Path(acq_dir) / f"Position{pos_idx+1}_Camera2.ome.zarr"
                        root2 = group(store=DirectoryStore(str(store_path2)), overwrite=False)
                        full_array2 = root2["0"]

                    # Loop to iterate over the Lasers
                    for j in range(nr_lasers):

                        # Set the correct parameters on both Cameras and start acquisition
                        # For just 1 Stack. For just 1 Laser
                        self.camera_parameters(camera2, camera2_dynamic_range, camera2_binning, camera2_format_x, camera2_format_y, Y_steps)
                        
                        # Change the filters for both Cameras
                        filterwheel2.set_position(filters2[j])

                        # Loop to iterate over the Y positions
                        k = 0     # This is the index of the Y positions, and the number of acquired frames
                        while k < Y_steps:

                            # stop check
                            if stop_event and stop_event.is_set():
                                return [i, j, k]  # unwind immediately
                            #----------------

                            # Move the stage
                            pidevice.MOV('2', Ys[k])
                            pitools.waitontarget(pidevice, axes=['2'])

                            # Information emission and stop check
                            if stop_event.is_set():
                                return [i, j, k]
                            if channel_callback:
                                channel_callback(j+1, nr_lasers)
                            if timepoint_callback:
                                timepoint_callback(i+1, time_points)
                            #----------------

                            if k == 0:
                                # Turn ON the laser
                                if laser_powers_W[j] == 0:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")
                                else:
                                    laserbox.write(f"SOURce{lasers[j]}:AM:STATe ON")
                                    laserbox.write(f"SOURce{lasers[j]}:POWer:LEVel:IMMediate:AMPLitude %.5f" % laser_powers_W[j])
                                if self._interruptible_sleep(0.3, stop_event):    # wait 300 ms for the laser to turn ON
                                    return [i, j, k]
                                
                            # Wait for the previous frame to reach memory
                            while (camera2.get_frames_status()[0] < k):
                                if self._interruptible_sleep(0.001, stop_event):
                                    return [i, j, k]
                            
                            # Mark and acquire
                            self.mark_toptobottom(rtc5_board, scan_top, scan_bottom, mark_speed)

                            # Add a frame to the counter
                            k += 1

                            # information emission
                            if slice_callback:
                                slice_callback(k, Y_steps)

                        # Wait for the last frame
                        while (camera2.get_frames_status()[0] < Y_steps):
                            if self._interruptible_sleep(0.001, stop_event):
                                return [i, j, k]

                        # After using this laser, turn it OFF
                        laserbox.write(f"SOURce{lasers[j]}:AM:STATe OFF")

                        # Initialize frame counters for both cameras
                        camera2_frame_counter = 0

                        # Define batch size
                        batch_size = 100

                        if Y_steps > batch_size:

                            # Loop to read frames in batches
                            for k_start in range(0, Y_steps, batch_size):
                                k_end = min(k_start + batch_size, Y_steps)
                                n_frames = k_end - k_start

                                # Calculate the range of frames to read
                                rng2 = (camera2_frame_counter, camera2_frame_counter + n_frames)

                                # Read frames using the calculated ranges
                                batch2 = camera2.read_multiple_images(rng=rng2)

                                # Update the full arrays with the new batches
                                full_array2[i, j, k_start:k_end, :, :] = batch2

                                # Update frame counters
                                camera2_frame_counter += n_frames

                        else:

                            full_array2[i,j,:,:,:] = camera2.read_multiple_images(rng=(0,Y_steps))

                        
                        # Clear the Cameras for another Stack
                        camera2.stop_acquisition()
                        camera2.clear_acquisition()

                        print(full_array2.shape)


            # Stop the system for the Time Spacing
            if i == time_points - 1:
                time_spacing = 0
            if self._interruptible_sleep(time_spacing, stop_event):
                return [i, j, k]


                    
        

    ######################################################################################################################
    # Then put here the functions and algorithm for the Z lambda acquisition

    ######################################################################################################################
    # Function for OME-Zarr embeded metadata

    def write_metadata(
        self,
        zarr_path: str,
        filter_list: list[int],
        dynamic_range: int,
        binning: int,
        *,
        t_spacing: float | None = None,
        t_spacing_unit: str | None = None,
        z_step: float | None = None,
        pixel_size_x: float | None = None,
        pixel_size_y: float | None = None,
    ) -> None:
        # ─── 1) Time spacing ────────────────────────────────────────────────
        if not t_spacing or t_spacing <= 0:
            t_spacing = 1.0
        if not t_spacing_unit:
            t_spacing_unit = "seconds"

        if t_spacing == 1:
            if t_spacing_unit == "seconds": t_spacing_unit = "second"
            elif t_spacing_unit == "minutes": t_spacing_unit = "minute"
            elif t_spacing_unit == "hours": t_spacing_unit = "hour"
            elif t_spacing_unit == "days": t_spacing_unit = "day"


        # ─── 2) Physical pixel sizes ────────────────────────────────────────
        psx = (pixel_size_x or 1.0) * binning
        psy = (pixel_size_y or 1.0) * binning
        psz = z_step or 1.0

        # ─── 3) Open the root & inspect level-0 ─────────────────────────────
        root = zarr.open_group(zarr_path, mode="r+")
        arr0 = root["0"]                     # shape = (T, C, Z, Y, X)
        T, C, Z, Y, X = arr0.shape
        dtype = arr0.dtype

        # # ─── 7) Build axes metadata ─────────────────────────────────────────
        axes = [
            {"name":"t","type":"time","unit":t_spacing_unit},
            {"name":"c","type":"channel"},
            {"name":"z","type":"space","unit":"µm"},
            {"name":"y","type":"space","unit":"µm"},
            {"name":"x","type":"space","unit":"µm"},
        ]

        # # ─── 8) Coordinate transforms for each level ─────────────────────────
        ct_list = []
        for lvl in (0,):# 1, 2):
            ct_list.append([{
                "type": "scale",
                "scale": [
                    t_spacing,             # time
                    1,                 # channel
                    psz,               # adjust Z so world‐scale stays isotropic
                    psy * (2**lvl),    # Y pixel size
                    psx * (2**lvl),    # X pixel size
                ]
            }])

        # ─── 9) Write only the multiscales block ────────────────────────────
        write_multiscales_metadata(
            group=root,
            datasets=[
                {"path": str(lvl), "coordinateTransformations": ct_list[lvl]}
                for lvl in (0,)#, 1, 2)
            ],
            fmt=FormatV04(),
            axes=axes,
            name="0",   # base level is the existing group “0”
        )

        # ───10) Attach OMERO metadata unchanged ──────────────────────────────
        FLUORO = ["DAPI","GFP","YFP","Alexa 568","Alexa 647","Other"]
        max_int = 2**dynamic_range - 1
        PROPS = {
            nm: {"color": props["color"], "window": {**props["window"], "max": max_int}}
            for nm, props in {
                "DAPI":      {"color":"0000FF","window":{"start":0,"end":int(max_int*0.2)}},
                "GFP":       {"color":"00FF00","window":{"start":0,"end":int(max_int*0.3)}},
                "YFP":       {"color":"FFFF00","window":{"start":0,"end":int(max_int*0.3)}},
                "Alexa 568": {"color":"FF00FF","window":{"start":0,"end":int(max_int*0.25)}},
                "Alexa 647": {"color":"FF0000","window":{"start":0,"end":int(max_int*0.25)}},
                "Other":     {"color":"FFFFFF","window":{"start":0,"end":int(max_int*0.25)}},
            }.items()
        }
        channels_meta = []
        for idx in filter_list:
            nm = FLUORO[idx] if idx < len(FLUORO) else "Other"
            p  = PROPS[nm]
            channels_meta.append({
                "label":  nm,
                "color":  p["color"],
                "window": {"min":0,"max":max_int, **p["window"]},
                "active": True
            })

        root.attrs["omero"] = {
            "id":       0,
            "name":     Path(zarr_path).name,
            "version":  "0.4",
            "channels": channels_meta,
            "rdefs":    {"model":"color","defaultT":0,"defaultZ":0},
        }

    ######################################################################################################################
    # Function for the settings report

    def write_txt_settings(self,
                Yi, Yf, Y_spacing,
                X, Z, Theta,
                time_points, time_spacing, time_step_unit,
                lasers, laser_powers_W,
                filters1, filters2,
                camera1_format_x, camera1_format_y, camera1_binning, camera1_dynamic_range,
                camera2_format_x, camera2_format_y, camera2_binning, camera2_dynamic_range,
                pixel_size_x, pixel_size_y,
                scan_top, scan_bottom, mark_speed,
                experiment_dir, exp_name) -> None:
        """
        Function that writes the metadata of the settings given to each of the devices in the time of acquisition.
        One of these files is written at each position
        """
        
        # Find the real final Y position
        if Y_spacing == 0 or Yi == Yf:
            Y_steps = 1
        else:
            N_steps = int ( np.floor( np.round( abs(Yf - Yi) / Y_spacing) ) ) or 1

        if Y_spacing == 0 or Yi == Yf:
            Yf = Yi
        elif Yf > Yi:
            Yf_real = Yi + N_steps * Y_spacing
            Yf = Yf_real
        elif Yi > Yf:
            Yf_real = Yi - N_steps * Y_spacing
            Yf = Yf_real
        
        N_steps = 1 if Y_spacing == 0 else ( int( np.floor( np.round( abs(Yf - Yi) / Y_spacing) ) ) + 1 ) or 1

        
        # Function to load the Filter Wheels data in dictionaries
        def load_filterwheels(json_path):
            with open(json_path, 'r') as f:
                data = json.load(f)

            wheels = {}
            for wheel_name, filters in data.items():
                mapping = {}
                for info in filters.values():
                    pos = info['position_on_filterwheel']
                    name = info.get('name', '').strip()
                    spectrum = info.get('spectrum', '').strip()
                    mapping[pos] = {
                        'name': name,
                        'spectrum': spectrum
                    }
                wheels[wheel_name] = mapping

            fw1 = wheels.get('Filterwheel_1', {})
            fw2 = wheels.get('Filterwheel_2', {})
            return fw1, fw2
        
        # Create a dictionary for the available according to their index in the Laser Box
        LASERS = {2: "640 nm", 3: "561 nm", 4: "488 nm", 5: "405 nm"}
        
        FILTERS1, FILTERS2 = load_filterwheels("Extra_Files//Filter_List.json")

        # Make sure the folder exists
        os.makedirs(experiment_dir, exist_ok=True)

        # Build the full path
        settings_file = f"{exp_name} Acquisition Settings.txt"
        file_path = os.path.join(experiment_dir, settings_file)

        # Write on the file
        with open(file_path, 'w', encoding='utf-8') as f:

            # Title
            f.write("# Experiment Settings:\n")
            f.write("\n")
            f.write(f"## {exp_name}\n")
            f.write("\n")
            # Time settings
            f.write(f"Acquired {time_points} times with a time-frame of {time_spacing} {time_step_unit}.\n")
            f.write("\n")

            f.write("-----------------------------------------------------------\n")
            f.write("\n")

            # Position settings
            f.write("### Positional Settings:\n")
            f.write(f"  X:  {X:.3f} μm\n")
            f.write(f"  Z:  {Z:.3f} μm\n")
            f.write(f"  θ:  {Theta:.3f} degrees\n")
            f.write("\n")
            f.write(f"  Initial Y:    {Yi:.3f} μm\n")
            f.write(f"  Final Y:      {Yf:.3f} μm\n")
            f.write(f"  Y spacing:    {Y_spacing:.3f} μm\n")
            f.write(f"  Nº of steps:  {N_steps}\n")
            f.write("\n")

            f.write("-----------------------------------------------------------\n")
            f.write("\n")

            # Camera 1
            if camera1_binning != 0 and camera1_dynamic_range != 0 and camera1_format_x != 0 and camera1_format_y != 0:
                f.write("### Camera 1 Settings:\n")
                f.write(f"  Format:         {camera1_format_x} x {camera1_format_y}\n")
                f.write(f"  Binning:        {camera1_binning} x {camera1_binning}\n")
                f.write(f"  Dynamic Range:  {camera1_dynamic_range} bits\n")
                f.write("\n")

            # Camera 2
            if camera2_binning != 0 and camera2_dynamic_range != 0 and camera2_format_x != 0 and camera2_format_y != 0:
                f.write("### Camera 2 Settings:\n")
                f.write(f"  Format:         {camera2_format_x} x {camera2_format_y}\n")
                f.write(f"  Binning:        {camera2_binning} x {camera2_binning}\n")
                f.write(f"  Dynamic Range:  {camera2_dynamic_range} bits\n")
                f.write("\n")

            f.write("-----------------------------------------------------------\n")
            f.write("\n")

            # Scanner
            f.write("### Scanner Settings:\n")
            f.write(f"  Speed:   {mark_speed}\n")
            f.write(f"  Top:     {scan_top}\n")
            f.write(f"  Bottom:  {scan_bottom}\n")
            f.write("\n")

            f.write("-----------------------------------------------------------\n")
            f.write("\n")

            # Laser
            f.write(f"### Laser Settings:\n")
            position = ["1st", "2nd", "3rd", "4th"]
            for laser_idx in range(len(lasers)):
                
                # Laser index
                f.write("\n")
                f.write(f"  #### {position[laser_idx]} laser: {LASERS.get(lasers[laser_idx])}\n")

                # Laser Power
                power_mW = laser_powers_W[laser_idx] * 1000
                print(power_mW)
                f.write(f"      Laser Power:        {power_mW:.0f}% ({power_mW:.0f} mW)\n")

                # Filter 1
                if len(filters1) > 0:
                    if camera1_binning != 0 and camera1_dynamic_range != 0 and camera1_format_x != 0 and camera1_format_y != 0:
                        filter = FILTERS1[filters1[laser_idx]]
                        name = filter['name']
                        spectrum = filter['spectrum']

                        if name == "No filter":
                            f.write(f"      Emission Filter 1:  {name}\n")
                        else:
                            f.write(f"      Emission Filter 1:  {name} ({spectrum})\n")

                # Filter 2
                if len(filters2) > 0:
                    if camera2_binning != 0 and camera2_dynamic_range != 0 and camera2_format_x != 0 and camera2_format_y != 0:
                        filter = FILTERS2[filters2[laser_idx]]
                        name = filter['name']
                        spectrum = filter['spectrum']

                        if name == "No filter":
                            f.write(f"      Emission Filter 2:  {name}\n")
                        else:
                            f.write(f"      Emission Filter 2:  {name} ({spectrum})\n")
        