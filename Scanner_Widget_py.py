# Imports from libraries
from PySide6.QtCore import Qt, QMetaObject, QTimer, QRect, QThread
from PySide6.QtGui import QIntValidator, QColor, QDoubleValidator
from PySide6.QtWidgets import (QApplication, QLabel, QLineEdit, QMainWindow,
    QPushButton, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGraphicsDropShadowEffect, QSlider, QCheckBox)
from PySide6.QtCore import Slot
from superqt import QRangeSlider
import sys

import ctypes
import os
import csv
from datetime import datetime
import numpy as np
import time
from pathlib import Path

import sys
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from PySide6.QtCore import QThread, Signal, Slot, QObject

from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from PySide6.QtCore import QThread, Signal, Slot, QObject, QTimer

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtCore import QThread, Signal, QObject, QTimer

# Imports from files
from Extra_Files.ToolTip_Manager import CustomToolTipManager
from Extra_Files.Scanner_Stylesheet import StyleSheets
from Extra_Files.Custom_Line_Edit import CustomLineEdit



class BeamWorker(QThread):
    beam_moved = Signal(int)  # Signal emitted when beam movement is complete
    finished = Signal()  # Signal emitted when the thread should stop

    def __init__(self, rtc5_board, ui):
        super().__init__()
        self.rtc5_board = rtc5_board
        self.ui = ui
        self._stop = False

    def move_beam(self, pos):
        """ Moves the beam to the specified position. """
        self.stop()  # Ensure no interference from the lightsheet process
        self.ui.move_beam_to(pos)
        self.beam_moved.emit(pos)

    def run(self):
        self._stop = False
        first_loop = True

        while not self._stop:
            Xtop = int(self.ui.lineedit_2.text())
            Xbottom = int(self.ui.lineedit_3.text())
            speed = float(self.ui.lineedit_1.text())

            if first_loop:
                self.ui.jump_top(Xtop)
                first_loop = False
            else:
                self.ui.mark_toptobottom(Xtop, Xbottom, speed)

        #loop that checks if the Scanner is marking, and only then emits the signal
        status = ctypes.c_uint()
        position = ctypes.c_int()
        while True:
            self.rtc5_board.get_status(ctypes.byref(status), ctypes.byref(position))
            busy         = bool(status.value & 0x00000001)  # BUSY bit
            internalBusy = bool(status.value & 0x00008000)  # INTERNAL-BUSY bit
            if not (busy or internalBusy):
                break
            time.sleep(0.001)

        self.finished.emit()

    def stop(self):
        """ Stops the marking process immediately. """
        self._stop = True


class Scanner_Widget(QWidget):
    #-------------------------------------------------------------------------------------
    # Initialization

    def __init__(self, device, parent=None):
        super().__init__(parent)

        self._update_in_progress = False
        self.lightsheet_running = False

        # Global Variables
        self.z_top = 3000
        self.z_bottom = -3500
        self.range_top = 5500
        self.range_bottom = -6000
        self.lightsheet_speed = 100
        self.center_beam_position = 0

        self.rtc5_board = device

        # Go to the reference
        self.rtc5_board.goto_xy(ctypes.c_int(self.center_beam_position), ctypes.c_int(0))

        self.worker = BeamWorker(self.rtc5_board, self)

        # send the position into the real mover
        #self.worker.beam_moved.connect(self.move_beam_to)
        self.worker.finished.connect(self.on_lightsheet_stopped)

        self.setupUi()


    def closeEvent(self, event):
        """Code to run before closing the application"""
        # Check if the thread and worker are running
        self.shutdown()
        if hasattr(self, 'thread') and self.thread.isRunning():
            if hasattr(self, 'loop'):
                self.loop.stop()  # Signal the worker to stop
            self.thread.quit()    # Ask the thread to exit
            self.thread.wait()    # Wait for the thread to finish
        event.accept()  # Accept the close event

    def shutdown(self):
        print("scanner shutdown")

    #-------------------------------------------------------------------------------------
    # Behaviour Functions

    def check_lineedit0_input(self):
        "Create the glow effect on lineedit_0 if its input is missing"
        print("signal emitted")
        if not self.lineedit_0.text():
            self.glow = QGraphicsDropShadowEffect(self.lineedit_0)
            self.glow.setColor(QColor("red"))
            self.glow.setBlurRadius(20)
            self.glow.setOffset(0)
            self.lineedit_0.setGraphicsEffect(self.glow)
        else:
            self.lineedit_0.setGraphicsEffect(None)

    def check_button2_input(self, checked):
        "Create a glow effect on the line edits if the input is missing"
        #if checked:
        if not self.lineedit_1.text():
            # Create the self.glow effect
            self.glow = QGraphicsDropShadowEffect(self.lineedit_1)
            self.glow.setColor(QColor("red"))
            self.glow.setBlurRadius(20)
            self.glow.setOffset(0)
            self.lineedit_1.setGraphicsEffect(self.glow)
            self.pushbutton_2.setChecked(False)
        else:
            self.lineedit_1.setGraphicsEffect(None)

        if not self.lineedit_2.text():
            # Create the self.glow effect
            self.glow = QGraphicsDropShadowEffect(self.lineedit_2)
            self.glow.setColor(QColor("red"))
            self.glow.setBlurRadius(20)
            self.glow.setOffset(0)
            self.lineedit_2.setGraphicsEffect(self.glow)
            self.pushbutton_2.setChecked(False)
        else:
            self.lineedit_2.setGraphicsEffect(None)

        if not self.lineedit_3.text():
                # Create the self.glow effect
            self.glow = QGraphicsDropShadowEffect(self.lineedit_3)
            self.glow.setColor(QColor("red"))
            self.glow.setBlurRadius(20)
            self.glow.setOffset(0)
            self.lineedit_3.setGraphicsEffect(self.glow)
            self.pushbutton_2.setChecked(False)
        else:
            self.lineedit_3.setGraphicsEffect(None)

            
    def lineedit_behaviour(self):
        if (self.lineedit_2.text() == str(self.z_top)) and (self.lineedit_3.text() == str(self.z_bottom)):
            self.pushbutton_1.setChecked(True)
        else:
            self.pushbutton_1.setChecked(False)
        self.doubleslider.setValue((int(float(self.lineedit_3.text())), int(float(self.lineedit_2.text()))))

    def button1_behaviour(self):
        self.pushbutton_1.setChecked(True)
        self.lineedit_2.setText(str(self.z_top))
        self.lineedit_3.setText(str(self.z_bottom))
        self.doubleslider.setValue((self.z_bottom, self.z_top))
        self.lineedit_2.repaint()
        self.lineedit_3.repaint()

    def slider_behaviour(self):
        bottom, top = self.doubleslider.sliderPosition()
        self.lineedit_2.setText(str(int(top)))
        self.lineedit_3.setText(str(int(bottom)))
        if (self.lineedit_2.text() == str(self.z_top)) and (self.lineedit_3.text() == str(self.z_bottom)):
            self.pushbutton_1.setChecked(True)
        else:
            self.pushbutton_1.setChecked(False)

    def move_beam_slider_behaviour(self):
        self.move_beam_slider.setEnabled(True)
        self.move_beam_to(self.move_beam_slider.value())
        self.lineedit_0.setText(str(self.move_beam_slider.value()))


    def lineedit0_behaviour(self):
        self.move_beam_slider.setValue(int(self.lineedit_0.text()))


    def button2_behaviour(self):
        if self.pushbutton_2.isChecked():  # Only clear if the button is still checked
            self.lineedit_1.setEnabled(False)
            self.move_beam_slider.setEnabled(False)
            self.lineedit_0.setEnabled(False)
            self.pushbutton_2.setText("Stop\nLightsheet")
        
        else:
            self.lineedit_1.setEnabled(True)
            self.move_beam_slider.setEnabled(True)
            self.lineedit_0.setEnabled(True)
            self.pushbutton_2.setText("Make\nLightsheet")


    def checkbox_scanner_select(self):
        """returns the scanner's parameters for the Y-Stack Acquisition"""
        y_top    = int(self.lineedit_2.text())
        y_bottom = int(self.lineedit_3.text())
        speed    = float(self.lineedit_1.text())

        if self.checkbox.isChecked():
            return {
                'scan_top':    y_top,
                'scan_bottom': y_bottom,
                'mark_speed':  speed,
            }
        else:
            # return the same keys, just with None (or some safe default)
            return {
                'scan_top':    None,
                'scan_bottom': None,
                'mark_speed':  None,
            }

    
    #-------------------------------------------------------------------------------------
    # Slots

    @Slot()
    def center_beam_after_ystack(self):
        """Function that moves the mirror to the center after the end of the Y-Stack"""
        
        # Move the mirror
        self.move_beam_to(self.center_beam_position)

        # Set the GUI parameters
        self.move_beam_slider.setValue(self.center_beam_position)
        self.lineedit_0.setText(str(self.center_beam_position))

    @Slot()
    def on_lightsheet_stopped(self):
        """Only once the worker thread has fully exited do we
           read lineedit_0 and move the beam there."""
        pos = int(self.lineedit_0.text())
        self.move_beam_to(pos)
        self.move_beam_slider.setValue(pos)



    #-------------------------------------------------------------------------------------
    # Functions for the Scanner

    def move_beam_to(self, pos):
        "Function to move the beam to a specific X position"
        Xpos = pos
        Ypos = 0
        self.rtc5_board.goto_xy(ctypes.c_int(Xpos), ctypes.c_int(Ypos))


    def jump_top(self, Xtop):
        self.rtc5_board.set_start_list(1)
        self.rtc5_board.set_jump_speed(ctypes.c_double(800000))
        self.rtc5_board.jump_abs(ctypes.c_int(Xtop), ctypes.c_int(0))
        self.rtc5_board.set_end_of_list()
        self.rtc5_board.execute_list(1)


    def mark_toptobottom(self, Xtop, Xbottom, speed):
        """
        Function to form a lightsheet
        It jumps to Xtop, marks from Xtop to Xbottom.
        It's supposed to use in a loop
        """
        Xi = Xtop
        Yi = 0
        Xf = Xbottom
        Yf = 0

        self.rtc5_board.set_start_list(1)

        self.rtc5_board.set_jump_speed(ctypes.c_double(800000))
        self.rtc5_board.set_mark_speed(ctypes.c_double(speed))

        self.rtc5_board.jump_abs(ctypes.c_int(Xi), ctypes.c_int(Yi))
        self.rtc5_board.mark_abs(ctypes.c_int(Xf), ctypes.c_int(Yf))

        self.rtc5_board.set_end_of_list()

        self.rtc5_board.execute_list(1)


    def lightsheet_thread(self, checked):
        if checked:
            self.thread = QThread()
            self.loop = lightsheet_loop()
            self.loop.moveToThread(self.thread)
            
            self.thread.started.connect(self.loop.start_loop)
            self.loop.finished.connect(self.thread.quit)
            self.loop.finished.connect(self.loop.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            self.loop.update.connect(self.handle_update)
            
            self.thread.start()
            print("Lightsheet thread started.")
        else:
            if self.loop:
                self.loop.stop()
                # Let the thread finish naturally instead of blocking with wait().
                self.thread.quit()
                print("Lightsheet thread stopping...")


    def handle_update(self):
        # If an update is already in progress, ignore this one
        if self._update_in_progress:
            return
        self._update_in_progress = True
        QTimer.singleShot(0, self.process_update)

    def process_update(self):
        # Call the board function
        self.rtc5_board.mark_toptobottom(
            int(self.lineedit_2.text()),
            int(self.lineedit_3.text()),
            float(self.lineedit_1.text())
        )
        # Allow new updates once processing is done
        self._update_in_progress = False


    def move_beam(self):
        """ Stops lightsheet marking before moving the beam. """
        if self.lightsheet_running:
            self.toggle_lightsheet(False)  # Ensure lightsheet stops first
        new_position = int(self.lineedit_0.text())
        self.worker.move_beam(new_position)

    def on_beam_moved(self):
        """ Callback when beam movement is done. """
        print("Beam moved successfully!")


    def toggle_lightsheet(self, checked):
        """ Starts or stops the lightsheet marking process. """
        if checked:
            self.lightsheet_running = True
            if not self.worker.isRunning():
                self.worker.start()
        else:
            self.lightsheet_running = False
            self.worker.stop()

    def lightsheet_stop(self):
        """Stops the Lightsheet and makes the UI go to the preset"""

        self.toggle_lightsheet(False)
        self.pushbutton_2.setChecked(False)
        self.pushbutton_2.setText("Make\nLightsheet")
        self.lineedit_0.setEnabled(True)
        self.lineedit_1.setEnabled(True)
        self.move_beam_slider.setEnabled(True)



    #-------------------------------------------------------------------------------------
    # UI

    def setupUi(self):
        # Initialize the tooltip manager
        self.tooltip_manager = CustomToolTipManager(self)

        self.setWindowTitle("Scanner Control")
        
        center_widget = QWidget(self)
        center_layout = QHBoxLayout(center_widget)
        
        # Left Widget (Slider)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        self.doubleslider = QRangeSlider(Qt.Vertical)
        self.doubleslider.setRange(self.range_bottom, self.range_top)
        self.doubleslider.setValue((self.z_bottom, self.z_top))
        self.doubleslider.setFixedSize(25, 150)
        self.doubleslider.valueChanged.connect(self.slider_behaviour)
        self.doubleslider.setGeometry(QRect(10, 10, 30, 160))

        self.doubleslider.setObjectName("mySlider")
        left_layout.addWidget(self.doubleslider)


        # Move Beam Slider
        self.move_beam_slider = QSlider()
        self.move_beam_slider.setMinimum(self.range_bottom)
        self.move_beam_slider.setMaximum(self.range_top)
        self.move_beam_slider.setValue(self.center_beam_position)
        self.move_beam_slider.setFixedSize(25, 150)
        self.move_beam_slider.valueChanged.connect(self.move_beam_slider_behaviour)


        
        # Middle Widget (Labels and LineEdits with Grid Layout)
        middle_widget = QWidget()
        middle_layout = QGridLayout(middle_widget)

        self.label_0 = QLabel("Move Beam:")

        self.lineedit_0 = CustomLineEdit()
        self.lineedit_0.setFixedWidth(50)
        self.lineedit_0.setValidator(QIntValidator())
        self.lineedit_0.editingFinished.connect(self.lineedit0_behaviour)
        self.lineedit_0.editingFinished.connect(self.move_beam)
        self.lineedit_0.setText(f"{self.center_beam_position}")
        self.tooltip_manager.attach_tooltip(self.lineedit_0, "<html>Moves the beam to a specific<br>coordinate in <i>Z</i>.</html>")
        self.lineedit_0.setStyleSheet("""
            QLineEdit {
                background-color: #333333;  /* Fix background */
                color: white;  /* Ensure white text */
                border: 1px solid #555555;  /* Darker border */
                padding: 4px;  /* Ensure spacing inside */
                border-radius: 3px;  /* Smooth rounded corners */
                selection-background-color: #0078d7;  /* Fix text selection */
            }

            QLineEdit:focus {
                border: 1px solid #888888;  /* Highlight when focused */
                background-color: #444444;  /* Slightly lighter when active */
            }

            QLineEdit:disabled {
                background-color: #222222;  /* Darker background to show it's disabled */
                color: #777777;  /* Dimmed text color */
                border: 1px solid #444444;  /* Less prominent border */
            }

            /* Force disable native styles that Qt might be using */
            QLineEdit, QLineEdit:focus, QLineEdit:disabled {
                outline: none;
            }
        """)

        self.label_1 = QLabel("Lightsheet\nSpeed:")
        self.lineedit_1 = CustomLineEdit()
        self.lineedit_1.setFixedWidth(50)
        self.lineedit_1.setText(str(self.lightsheet_speed))
        validator = QIntValidator(2, 2**31 - 1, self)
        self.lineedit_1.setValidator(validator)
        self.lineedit_1.setValidator(validator)
        self.tooltip_manager.attach_tooltip(self.lineedit_1, "Sets the speed at which the mirror\nthat forms the Lightsheet moves.") 
        self.lineedit_1.setStyleSheet("""
            QLineEdit {
                background-color: #333333;  /* Fix background */
                color: white;  /* Ensure white text */
                border: 1px solid #555555;  /* Darker border */
                padding: 4px;  /* Ensure spacing inside */
                border-radius: 3px;  /* Smooth rounded corners */
                selection-background-color: #0078d7;  /* Fix text selection */
            }

            QLineEdit:focus {
                border: 1px solid #888888;  /* Highlight when focused */
                background-color: #444444;  /* Slightly lighter when active */
            }

            QLineEdit:disabled {
                background-color: #222222;  /* Darker background to show it's disabled */
                color: #777777;  /* Dimmed text color */
                border: 1px solid #444444;  /* Less prominent border */
            }

            /* Force disable native styles that Qt might be using */
            QLineEdit, QLineEdit:focus, QLineEdit:disabled {
                outline: none;
            }
        """)        

        self.label_2 = QLabel("Top <i>Z</i>:")
        self.label_2.setTextFormat(Qt.TextFormat.RichText)
        self.lineedit_2 = CustomLineEdit(f"{self.z_top}")
        self.lineedit_2.setFixedWidth(50)
        self.lineedit_2.setValidator(QIntValidator())
        self.lineedit_2.editingFinished.connect(self.lineedit_behaviour)
        self.lineedit_2.setStyleSheet("""
            QLineEdit {
                background-color: #333333;  /* Fix background */
                color: white;  /* Ensure white text */
                border: 1px solid #555555;  /* Darker border */
                padding: 4px;  /* Ensure spacing inside */
                border-radius: 3px;  /* Smooth rounded corners */
                selection-background-color: #0078d7;  /* Fix text selection */
            }

            QLineEdit:focus {
                border: 1px solid #888888;  /* Highlight when focused */
                background-color: #444444;  /* Slightly lighter when active */
            }

            QLineEdit:disabled {
                background-color: #222222;  /* Darker background to show it's disabled */
                color: #777777;  /* Dimmed text color */
                border: 1px solid #444444;  /* Less prominent border */
            }

            /* Force disable native styles that Qt might be using */
            QLineEdit, QLineEdit:focus, QLineEdit:disabled {
                outline: none;
            }
        """)
        
        self.label_3 = QLabel("Bottom <i>Z</i>:")
        self.label_3.setTextFormat(Qt.TextFormat.RichText)
        self.lineedit_3 = CustomLineEdit(f"{self.z_bottom}")
        self.lineedit_3.setFixedWidth(50)
        self.lineedit_3.setValidator(QIntValidator())
        self.lineedit_3.editingFinished.connect(self.lineedit_behaviour)
        self.lineedit_3.setStyleSheet("""
            QLineEdit {
                background-color: #333333;  /* Fix background */
                color: white;  /* Ensure white text */
                border: 1px solid #555555;  /* Darker border */
                padding: 4px;  /* Ensure spacing inside */
                border-radius: 3px;  /* Smooth rounded corners */
                selection-background-color: #0078d7;  /* Fix text selection */
            }

            QLineEdit:focus {
                border: 1px solid #888888;  /* Highlight when focused */
                background-color: #444444;  /* Slightly lighter when active */
            }

            QLineEdit:disabled {
                background-color: #222222;  /* Darker background to show it's disabled */
                color: #777777;  /* Dimmed text color */
                border: 1px solid #444444;  /* Less prominent border */
            }

            /* Force disable native styles that Qt might be using */
            QLineEdit, QLineEdit:focus, QLineEdit:disabled {
                outline: none;
            }
        """)
        
        middle_layout.addWidget(self.label_0, 0, 0)
        middle_layout.addWidget(self.lineedit_0, 0, 1)
        middle_layout.addWidget(self.label_1, 1, 0)
        middle_layout.addWidget(self.lineedit_1, 1, 1)
        middle_layout.addWidget(self.label_2, 2, 0)
        middle_layout.addWidget(self.lineedit_2, 2, 1)
        middle_layout.addWidget(self.label_3, 3, 0)
        middle_layout.addWidget(self.lineedit_3, 3, 1)
            # Add a margin to the right for the glowing effect
        middle_layout.setContentsMargins(0, 0, 9, 0)  # left, top, right, bottom

        
        # Right Widget (Buttons)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        self.pushbutton_1 = QPushButton("Current FOV")
        self.pushbutton_1.setCheckable(True)
        self.pushbutton_1.setChecked(True)
        self.pushbutton_1.clicked.connect(self.button1_behaviour)
        self.pushbutton_1.setFixedSize(100, 65)  # Set a fixed size (width, height)
        self.pushbutton_1.setStyleSheet("""
                QPushButton {
                    background-color: #2E2E2E;
                    color: white;
                    border: 2px solid #555;
                    border-radius: 12px;
                    padding: 2px 6px;
                    font-size: 12px;
                    outline: none;
                }

                QPushButton:hover {
                    background-color: #3C3C3C;
                    border: 2px solid #777;
                }

                QPushButton:pressed {
                    background-color: #1E1E1E;
                    border: 2px solid #999;
                }

                QPushButton:disabled {
                    background-color: #5E5E5E;
                    border: 2px solid #777;
                    color: #B0B0B0;
                }

                QPushButton:checked {
                    background-color: #4CAF50; /* Green highlight */
                    border: 2px solid #80E27E;
                    color: black;
                    font-weight: bold;
                }

                QPushButton:checked:hover {
                    background-color: #45A049;
                    border: 2px solid #76D275;
                }

                QPushButton:checked:pressed {
                    background-color: #388E3C;
                    border: 2px solid #60C460;
                }

                QPushButton:checked:disabled {
                    background-color: #7CBF7C;  /* Muted green */
                    border: 2px solid #A5D6A7;
                    font-weight: bold;
                    color: black;
                }
        """)

        
        self.pushbutton_2 = QPushButton("Make\nLightsheet")
        self.pushbutton_2.setCheckable(True)
        self.pushbutton_2.toggled.connect(self.check_button2_input)
        self.pushbutton_2.clicked.connect(self.button2_behaviour)
        self.pushbutton_2.toggled.connect(self.toggle_lightsheet)
        self.pushbutton_2.setFixedSize(100, 65)
        self.pushbutton_2.setStyleSheet("""
                QPushButton {
                    background-color: #2E2E2E;
                    color: white;
                    border: 2px solid #555;
                    border-radius: 12px;
                    padding: 2px 6px;
                    font-size: 12px;
                    outline: none;
                }

                QPushButton:hover {
                    background-color: #3C3C3C;
                    border: 2px solid #777;
                }

                QPushButton:pressed {
                    background-color: #1E1E1E;
                    border: 2px solid #999;
                }

                QPushButton:disabled {
                    background-color: #5E5E5E;
                    border: 2px solid #777;
                    color: #B0B0B0;
                }

                QPushButton:checked {
                    background-color: #4CAF50; /* Green highlight */
                    border: 2px solid #80E27E;
                    color: black;
                    font-weight: bold;
                }

                QPushButton:checked:hover {
                    background-color: #45A049;
                    border: 2px solid #76D275;
                }

                QPushButton:checked:pressed {
                    background-color: #388E3C;
                    border: 2px solid #60C460;
                }

                QPushButton:checked:disabled {
                    background-color: #7CBF7C;  /* Muted green */
                    border: 2px solid #A5D6A7;
                    font-weight: bold;
                    color: black;
                }
        """)

        self.setStyleSheet("""
            QWidget {
                background-color: #222222;  /* Dark background */
            }
                       
            QLabel, QGroupBox {
                color: white;  /* White text for labels */
            }
                       
            /* Override for the custom slider */
            QRangeSlider#mySlider {
                background-color: transparent; /* or specify the desired color for your slider */
            }

        """)
        
        right_layout.addWidget(self.pushbutton_1)
        right_layout.addWidget(self.pushbutton_2)


        
        # Add widgets to main layout
        center_layout.addWidget(left_widget)
        center_layout.addWidget(self.move_beam_slider)
        center_layout.addWidget(middle_widget)
        center_layout.addWidget(right_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)

        # Add the checkbox

        main_layout = QVBoxLayout()
        # checkbox_widget = QWidget(self)
        # checkbox_widget_layout = QHBoxLayout(checkbox_widget)

        self.checkbox = QCheckBox(" Select scanner's settings")
        self.checkbox.toggled.connect(self.checkbox_scanner_select)
        #self.tooltip_manager.attach_tooltip(self.checkbox, "Select these scanner's settings\nfor acquisition")
        script_path = Path(__file__).resolve()
        icon_path   = script_path.parent / "icons" / "check.png"
        self.checkbox.setStyleSheet(f"""
            QCheckBox {{
                spacing: 2px;
                color: white;
                font-size: 12px;
            }}

            QCheckBox::indicator {{
                width: 13px;
                height: 13px;
                border: 2px solid #555;
                border-radius: 4px;
                background-color: #2E2E2E;
            }}

            QCheckBox::indicator:hover {{
                background-color: #3C3C3C;
                border: 2px solid #777;
            }}

            QCheckBox::indicator:pressed {{
                background-color: #1E1E1E;
                border: 2px solid #999;
            }}

            QCheckBox::indicator:checked {{
                background-color: #4CAF50;
                border: 2px solid #80E27E;
                image: url("{icon_path.as_posix()}");
            }}

            QCheckBox::indicator:checked:hover {{
                background-color: #45A049;
                border: 2px solid #76D275;
            }}

            QCheckBox::indicator:checked:pressed {{
                background-color: #388E3C;
                border: 2px solid #60C460;
            }}

            QCheckBox:disabled {{
                color: #B0B0B0;
            }}

            QCheckBox::indicator:disabled {{
                background-color: #5E5E5E;
                border: 2px solid #777;
            }}
        """)


        main_layout.addWidget(self.checkbox, alignment=Qt.AlignLeft)
        main_layout.addWidget(center_widget)        
        self.setLayout(main_layout)