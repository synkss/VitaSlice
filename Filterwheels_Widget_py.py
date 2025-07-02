# Imports from libraries
import microscope
from microscope.controllers.zaber import _ZaberFilterWheel, _ZaberConnection

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QPalette, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform, QIntValidator, QIcon)
from PySide6.QtWidgets import (QApplication, QFrame, QLabel, QMainWindow,
    QPushButton, QSizePolicy, QSlider, QStatusBar,
    QTextEdit, QWidget, QLineEdit, QMenu, QVBoxLayout, QButtonGroup, QHBoxLayout, QVBoxLayout)
from PySide6.QtCore import Slot
import sys
import json
from pathlib import Path

# Imports from my code
from Extra_Files.ToolTip_Manager import CustomToolTipManager
from Extra_Files.Stylesheet_List import StyleSheets
from Extra_Files.Custom_Line_Edit import CustomLineEdit

#####################################################################

from PySide6.QtCore import QThread, Signal, QObject

class FilterwheelWorker(QThread):
    filterwheel_changed = Signal(int, int)  # Signal to update UI after moving (wheel_number, position)

    def __init__(self, filterwheel_1, filterwheel_2):
        """
        Handles filter wheel movement in a separate thread.
        """
        super().__init__()
        self.filterwheel_1 = filterwheel_1
        self.filterwheel_2 = filterwheel_2
        self.wheel_number = None
        self.position = None
        self._stop = False

    def run(self):
        if self.wheel_number == 1 and self.filterwheel_1 is not None:
            self.filterwheel_1.set_position(self.position)
            current_pos = self.filterwheel_1.get_position()
        elif self.wheel_number == 2 and self.filterwheel_2 is not None:
            self.filterwheel_2.set_position(self.position)
            current_pos = self.filterwheel_2.get_position()
        else:
            return

        self.filterwheel_changed.emit(self.wheel_number, current_pos)


    def change_filter(self, wheel_number, position):
        """ Stores request and starts the worker thread on demand. """
        self.wheel_number = wheel_number
        self.position = position
        if not self.isRunning():
            self.start()  # Only start the thread when needed

    def stop(self):
        """ Stops the worker thread. """
        self._stop = True
        self.quit()
        self.wait()

#####################################################################

class Filterwheels_Widget(QWidget):



    def __init__(self, filter_data, device1, device2, parent=None):
        super().__init__(parent)

        # Button sizes:
        self.button_size = 45
        self.filter_icon_size = QSize(37, 37)

        # Load the JSON's file data
        self.filter_data = filter_data

        # Accept the filterwheels arguments
        self.filterwheel_1 = device1
        self.filterwheel_2 = device2

        # Initialize on the first position
        self.filterwheel_1.set_position(5)
        self.filterwheel_2.set_position(5)

        # Set up the workers
        self.worker_1 = FilterwheelWorker(self.filterwheel_1, None)
        self.worker_2 = FilterwheelWorker(None, self.filterwheel_2)

        self.worker_1.filterwheel_changed.connect(self.on_filterwheel_changed)
        self.worker_2.filterwheel_changed.connect(self.on_filterwheel_changed)


        self.setupUi()

    
    ######################################################################

    def change_filterwheel_1(self, n):
        """
        Change the position in Filterwheel 1
        """
        self.worker_1.change_filter(1, n)

    def change_filterwheel_2(self, n):
        """
        Change the position in Filterwheel 2
        """
        self.worker_2.change_filter(2, n)

    def on_filterwheel_changed(self, wheel_number, position):
        """
        Callback function when a filter wheel has changed positions.
        """
        print(f"Filterwheel {wheel_number} moved to position {position}")

    def closeEvent(self, event):
        """ Ensure worker stops when closing the application. """
        self.worker.stop()
        event.accept()

    def shutdown(self):
        print("filterwheels shutdown")

        if self.worker_1.isRunning():
            self.worker_1.quit()
            self.worker_1.wait()

        if self.worker_2.isRunning():
            self.worker_2.quit()
            self.worker_2.wait()

    def fwheel1_clicked(self, checked=False):
        """Function that upon a click in a checked button, returns the filter to Empty in Filterwheel 1"""
        btns = self.widget2_buttongroup.buttons()
        btn  = self.sender()

        # if the user clicked the already‐checked button...
        if btn is self._prev_btn_w1:
            last = btns[-1]            # the 6th (last) button in the group
            last.setChecked(True)      # move the check there
            self._prev_btn_w1 = last

            # Change the filter
            self.change_filterwheel_1(5)
            

        else:
            # normal click on a different button
            self._prev_btn_w1 = btn

    def fwheel2_clicked(self, checked=False):
        """Function that upon a click in a checked button, returns the filter to Empty in Filterwheel 2"""
        btns = self.widget4_buttongroup.buttons()
        btn  = self.sender()

        # if the user clicked the already‐checked button...
        if btn is self._prev_btn_w2:
            last = btns[-1]            # the 6th (last) button in the group
            last.setChecked(True)      # move the check there
            self._prev_btn_w2 = last

            # Change the filter
            self.change_filterwheel_2(5)
        else:
            # normal click on a different button
            self._prev_btn_w2 = btn

    @Slot()
    def restore_filters_after_ystack(self):
        """Function that re-applies the filters to the positions they were before the Y-Stack started"""

        # Filter Wheel 1
        button_1 = self.widget2_buttongroup.checkedButton()
        buttons_1 = self.widget2_buttongroup.buttons()
        position_1 = buttons_1.index(button_1)
        self.change_filterwheel_1(position_1)

        # Filter Wheel 2
        button_2 = self.widget4_buttongroup.checkedButton()
        buttons_2 = self.widget4_buttongroup.buttons()
        position_2 = buttons_2.index(button_2)
        self.change_filterwheel_2(position_2)



    ######################################################################

    def setupUi(self):

        # Initialize the tooltip manager
        self.tooltip_manager = CustomToolTipManager(self)

        # Create main window
        self.setWindowTitle(u"Filterwheels Control")

        # Defining the central widget
        main_layout = QVBoxLayout(self)

        #____________________________________________________________

        # 1st Widget (Label)

        self.label_1 = QLabel("Filter Wheel 1")
        self.label_1.setStyleSheet("font-size: 10.5pt; font-weight: bold;")
        self.label_1.setContentsMargins(0, 0, 0, 0)

        #____________________________________________________________

        # 2nd Widget (Buttons)

        widget2 = QWidget()
        widget2_layout = QHBoxLayout(widget2)
        widget2_layout.setContentsMargins( 0, 0, 0, 0)
        widget2_layout.setAlignment(Qt.AlignLeft)

            # Create a button group for widget2
        self.widget2_buttongroup = QButtonGroup()
        self.widget2_buttongroup.setExclusive(True)

            # Create an index for the buttons
        filterwheel1_index = 0
        for filter_key, filter_item in self.filter_data["Filterwheel_1"].items():

                # Create the button and style it
            button = QPushButton()
            self.widget2_buttongroup.addButton(button)
            button.setCheckable(True)

            icon_path = f"icons//{filter_item.get('icon_file')}"
            button.setIcon(QIcon(icon_path))
            button.setFixedSize(self.button_size, self.button_size)
            button.setIconSize(self.filter_icon_size)
            self.tooltip_manager.attach_tooltip(button, f"{filter_item.get('tooltip')}")
            widget2_layout.addWidget(button)

                # Connect the button to the function
            button.clicked.connect(lambda checked, n=filterwheel1_index: self.change_filterwheel_1(n))

            if filter_key == "empty":
                button.setChecked(True)

            filterwheel1_index += 1     # Add 1 to iterate to the next index

        # Define the "previous button" for the Filter Wheel 1
        self._prev_btn_w1 = self.widget2_buttongroup.checkedButton()
        # wire up a single slot for all of them:
        for btn in self.widget2_buttongroup.buttons():
            btn.clicked.connect(self.fwheel1_clicked)

        #____________________________________________________________

        # 3rd Widget (Label)

        self.label_2 = QLabel("Filter Wheel 2")
        self.label_2.setStyleSheet("font-size: 10.5pt; font-weight: bold;")
        self.label_2.setContentsMargins(0, 0, 0, 0)

        #____________________________________________________________

        # 4th Widget (Buttons)

        widget4 = QWidget()
        widget4_layout = QHBoxLayout(widget4)
        widget4_layout.setContentsMargins(0, 0, 0, 0)
        widget4_layout.setAlignment(Qt.AlignLeft)
        

            # Create a button group for widget2
        self.widget4_buttongroup = QButtonGroup()
        self.widget4_buttongroup.setExclusive(True)

            # Create an index for the buttons
        filterwheel2_index = 0
        for filter_key, filter_item in self.filter_data["Filterwheel_2"].items():

                # Create the button and style it
            button = QPushButton()
            self.widget4_buttongroup.addButton(button)
            button.setCheckable(True)

            icon_path = f"icons//{filter_item.get('icon_file')}"
            button.setIcon(QIcon(icon_path))
            button.setFixedSize(self.button_size, self.button_size)
            button.setIconSize(self.filter_icon_size)
            self.tooltip_manager.attach_tooltip(button, f"{filter_item.get('tooltip')}")
            widget4_layout.addWidget(button)

                # Connect the button to the function
            button.clicked.connect(lambda checked, n=filterwheel2_index: self.change_filterwheel_2(n))

            if filter_key == "empty":
                button.setChecked(True)

            filterwheel2_index += 1     # Add 1 to iterate to the next index

        # Define the "previous button" for the Filter Wheel 2
        self._prev_btn_w2 = self.widget4_buttongroup.checkedButton()
        for btn in self.widget4_buttongroup.buttons():
            btn.clicked.connect(self.fwheel2_clicked)

        #____________________________________________________________

        # Add widgets to main layout
        main_layout.addWidget(self.label_1)
        main_layout.addWidget(widget2)
        main_layout.addWidget(self.label_2)
        main_layout.addWidget(widget4)

        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#222222"))  # Dark background
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.setStyleSheet("""

            QLabel, QGroupBox {
                color: white;
            }
            QPushButton {
                background-color: #2E2E2E;
                color: white;
                border: 2px solid #555;
                border-radius: 12px;
                padding: 0px 16px;
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

