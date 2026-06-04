# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'Radar_UDP.ui'
##
## Created by: Qt User Interface Compiler version 6.10.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLineEdit,
    QMainWindow, QMenuBar, QProgressBar, QPushButton,
    QRadioButton, QSizePolicy, QSpacerItem, QStatusBar,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1022, 822)
        MainWindow.setLayoutDirection(Qt.LeftToRight)
        MainWindow.setAutoFillBackground(True)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.centralwidget.setLayoutDirection(Qt.LeftToRight)
        self.gridLayout = QGridLayout(self.centralwidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.line_3 = QFrame(self.centralwidget)
        self.line_3.setObjectName(u"line_3")
        self.line_3.setFrameShape(QFrame.Shape.VLine)
        self.line_3.setFrameShadow(QFrame.Shadow.Sunken)

        self.gridLayout.addWidget(self.line_3, 2, 1, 1, 1)

        self.tabWidget_Message = QTabWidget(self.centralwidget)
        self.tabWidget_Message.setObjectName(u"tabWidget_Message")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(12)
        sizePolicy.setVerticalStretch(3)
        sizePolicy.setHeightForWidth(self.tabWidget_Message.sizePolicy().hasHeightForWidth())
        self.tabWidget_Message.setSizePolicy(sizePolicy)
        font = QFont()
        font.setFamilies([u"Times New Roman"])
        font.setBold(True)
        self.tabWidget_Message.setFont(font)
        self.tab_log = QWidget()
        self.tab_log.setObjectName(u"tab_log")
        self.horizontalLayout = QHBoxLayout(self.tab_log)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.textEdit_log = QTextEdit(self.tab_log)
        self.textEdit_log.setObjectName(u"textEdit_log")

        self.horizontalLayout.addWidget(self.textEdit_log)

        self.tabWidget_Message.addTab(self.tab_log, "")
        self.tab_Distance = QWidget()
        self.tab_Distance.setObjectName(u"tab_Distance")
        self.horizontalLayout_2 = QHBoxLayout(self.tab_Distance)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.tableWidget_distance = QTableWidget(self.tab_Distance)
        self.tableWidget_distance.setObjectName(u"tableWidget_distance")

        self.horizontalLayout_2.addWidget(self.tableWidget_distance)

        self.tabWidget_Message.addTab(self.tab_Distance, "")
        self.tab_XYZpoint = QWidget()
        self.tab_XYZpoint.setObjectName(u"tab_XYZpoint")
        self.horizontalLayout_19 = QHBoxLayout(self.tab_XYZpoint)
        self.horizontalLayout_19.setObjectName(u"horizontalLayout_19")
        self.tableWidget_point = QTableWidget(self.tab_XYZpoint)
        self.tableWidget_point.setObjectName(u"tableWidget_point")

        self.horizontalLayout_19.addWidget(self.tableWidget_point)

        self.tabWidget_Message.addTab(self.tab_XYZpoint, "")

        self.gridLayout.addWidget(self.tabWidget_Message, 2, 0, 1, 1)

        self.groupBox_Config = QGroupBox(self.centralwidget)
        self.groupBox_Config.setObjectName(u"groupBox_Config")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(2)
        sizePolicy1.setVerticalStretch(5)
        sizePolicy1.setHeightForWidth(self.groupBox_Config.sizePolicy().hasHeightForWidth())
        self.groupBox_Config.setSizePolicy(sizePolicy1)
        self.groupBox_Config.setFont(font)
        self.verticalLayout = QVBoxLayout(self.groupBox_Config)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.groupBox_UDP = QGroupBox(self.groupBox_Config)
        self.groupBox_UDP.setObjectName(u"groupBox_UDP")
        self.verticalLayout_2 = QVBoxLayout(self.groupBox_UDP)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.pushButton_Connect = QPushButton(self.groupBox_UDP)
        self.pushButton_Connect.setObjectName(u"pushButton_Connect")

        self.horizontalLayout_3.addWidget(self.pushButton_Connect)

        self.pushButton_Disconnect = QPushButton(self.groupBox_UDP)
        self.pushButton_Disconnect.setObjectName(u"pushButton_Disconnect")

        self.horizontalLayout_3.addWidget(self.pushButton_Disconnect)


        self.verticalLayout_2.addLayout(self.horizontalLayout_3)

        self.horizontalLayout_14 = QHBoxLayout()
        self.horizontalLayout_14.setObjectName(u"horizontalLayout_14")
        self.pushButton_Video_open = QPushButton(self.groupBox_UDP)
        self.pushButton_Video_open.setObjectName(u"pushButton_Video_open")

        self.horizontalLayout_14.addWidget(self.pushButton_Video_open)

        self.pushButton_video_close = QPushButton(self.groupBox_UDP)
        self.pushButton_video_close.setObjectName(u"pushButton_video_close")

        self.horizontalLayout_14.addWidget(self.pushButton_video_close)


        self.verticalLayout_2.addLayout(self.horizontalLayout_14)

        self.horizontalLayout_5 = QHBoxLayout()
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_5.addItem(self.horizontalSpacer)

        self.checkBox_IsSave = QCheckBox(self.groupBox_UDP)
        self.checkBox_IsSave.setObjectName(u"checkBox_IsSave")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.checkBox_IsSave.sizePolicy().hasHeightForWidth())
        self.checkBox_IsSave.setSizePolicy(sizePolicy2)
        self.checkBox_IsSave.setLayoutDirection(Qt.RightToLeft)

        self.horizontalLayout_5.addWidget(self.checkBox_IsSave)

        self.checkBox_HammingWindow = QCheckBox(self.groupBox_UDP)
        self.checkBox_HammingWindow.setObjectName(u"checkBox_HammingWindow")
        sizePolicy2.setHeightForWidth(self.checkBox_HammingWindow.sizePolicy().hasHeightForWidth())
        self.checkBox_HammingWindow.setSizePolicy(sizePolicy2)
        self.checkBox_HammingWindow.setLayoutDirection(Qt.RightToLeft)

        self.horizontalLayout_5.addWidget(self.checkBox_HammingWindow)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_5.addItem(self.horizontalSpacer_2)


        self.verticalLayout_2.addLayout(self.horizontalLayout_5)


        self.verticalLayout.addWidget(self.groupBox_UDP)

        self.line_8 = QFrame(self.groupBox_Config)
        self.line_8.setObjectName(u"line_8")
        self.line_8.setFrameShape(QFrame.Shape.HLine)
        self.line_8.setFrameShadow(QFrame.Shadow.Sunken)

        self.verticalLayout.addWidget(self.line_8)

        self.groupBox_calibration = QGroupBox(self.groupBox_Config)
        self.groupBox_calibration.setObjectName(u"groupBox_calibration")
        self.verticalLayout_5 = QVBoxLayout(self.groupBox_calibration)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.horizontalLayout_10 = QHBoxLayout()
        self.horizontalLayout_10.setObjectName(u"horizontalLayout_10")
        self.horizontalSpacer_13 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_10.addItem(self.horizontalSpacer_13)

        self.checkBox_CalibrationMode = QCheckBox(self.groupBox_calibration)
        self.checkBox_CalibrationMode.setObjectName(u"checkBox_CalibrationMode")
        sizePolicy2.setHeightForWidth(self.checkBox_CalibrationMode.sizePolicy().hasHeightForWidth())
        self.checkBox_CalibrationMode.setSizePolicy(sizePolicy2)
        self.checkBox_CalibrationMode.setLayoutDirection(Qt.RightToLeft)

        self.horizontalLayout_10.addWidget(self.checkBox_CalibrationMode)

        self.horizontalSpacer_14 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_10.addItem(self.horizontalSpacer_14)


        self.verticalLayout_5.addLayout(self.horizontalLayout_10)

        self.horizontalLayout_9 = QHBoxLayout()
        self.horizontalLayout_9.setObjectName(u"horizontalLayout_9")
        self.horizontalSpacer_11 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_9.addItem(self.horizontalSpacer_11)

        self.checkBox_channel_calibration = QCheckBox(self.groupBox_calibration)
        self.checkBox_channel_calibration.setObjectName(u"checkBox_channel_calibration")
        self.checkBox_channel_calibration.setLayoutDirection(Qt.RightToLeft)

        self.horizontalLayout_9.addWidget(self.checkBox_channel_calibration)

        self.horizontalSpacer_12 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_9.addItem(self.horizontalSpacer_12)


        self.verticalLayout_5.addLayout(self.horizontalLayout_9)

        self.horizontalLayout_17 = QHBoxLayout()
        self.horizontalLayout_17.setObjectName(u"horizontalLayout_17")
        self.radioButton_FFT = QRadioButton(self.groupBox_calibration)
        self.radioButton_FFT.setObjectName(u"radioButton_FFT")

        self.horizontalLayout_17.addWidget(self.radioButton_FFT)

        self.radioButton_LS = QRadioButton(self.groupBox_calibration)
        self.radioButton_LS.setObjectName(u"radioButton_LS")

        self.horizontalLayout_17.addWidget(self.radioButton_LS)

        self.radioButton_WLS = QRadioButton(self.groupBox_calibration)
        self.radioButton_WLS.setObjectName(u"radioButton_WLS")

        self.horizontalLayout_17.addWidget(self.radioButton_WLS)


        self.verticalLayout_5.addLayout(self.horizontalLayout_17)

        self.horizontalLayout_11 = QHBoxLayout()
        self.horizontalLayout_11.setObjectName(u"horizontalLayout_11")
        self.pushButton_LoadMode = QPushButton(self.groupBox_calibration)
        self.pushButton_LoadMode.setObjectName(u"pushButton_LoadMode")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy3.setHorizontalStretch(5)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.pushButton_LoadMode.sizePolicy().hasHeightForWidth())
        self.pushButton_LoadMode.setSizePolicy(sizePolicy3)

        self.horizontalLayout_11.addWidget(self.pushButton_LoadMode)

        self.lineEdit_ModeName = QLineEdit(self.groupBox_calibration)
        self.lineEdit_ModeName.setObjectName(u"lineEdit_ModeName")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy4.setHorizontalStretch(5)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.lineEdit_ModeName.sizePolicy().hasHeightForWidth())
        self.lineEdit_ModeName.setSizePolicy(sizePolicy4)

        self.horizontalLayout_11.addWidget(self.lineEdit_ModeName)


        self.verticalLayout_5.addLayout(self.horizontalLayout_11)

        self.horizontalLayout_18 = QHBoxLayout()
        self.horizontalLayout_18.setObjectName(u"horizontalLayout_18")
        self.horizontalSpacer_3 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_18.addItem(self.horizontalSpacer_3)

        self.checkBox_addnoise = QCheckBox(self.groupBox_calibration)
        self.checkBox_addnoise.setObjectName(u"checkBox_addnoise")
        self.checkBox_addnoise.setLayoutDirection(Qt.RightToLeft)

        self.horizontalLayout_18.addWidget(self.checkBox_addnoise)

        self.checkBox_align_iq = QCheckBox(self.groupBox_calibration)
        self.checkBox_align_iq.setObjectName(u"checkBox_align_iq")
        self.checkBox_align_iq.setLayoutDirection(Qt.RightToLeft)

        self.horizontalLayout_18.addWidget(self.checkBox_align_iq)

        self.horizontalSpacer_4 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_18.addItem(self.horizontalSpacer_4)


        self.verticalLayout_5.addLayout(self.horizontalLayout_18)


        self.verticalLayout.addWidget(self.groupBox_calibration)

        self.line_6 = QFrame(self.groupBox_Config)
        self.line_6.setObjectName(u"line_6")
        self.line_6.setFrameShape(QFrame.Shape.HLine)
        self.line_6.setFrameShadow(QFrame.Shadow.Sunken)

        self.verticalLayout.addWidget(self.line_6)

        self.groupBox_File = QGroupBox(self.groupBox_Config)
        self.groupBox_File.setObjectName(u"groupBox_File")
        self.verticalLayout_3 = QVBoxLayout(self.groupBox_File)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.pushButton_ReadFile = QPushButton(self.groupBox_File)
        self.pushButton_ReadFile.setObjectName(u"pushButton_ReadFile")
        sizePolicy4.setHeightForWidth(self.pushButton_ReadFile.sizePolicy().hasHeightForWidth())
        self.pushButton_ReadFile.setSizePolicy(sizePolicy4)

        self.horizontalLayout_4.addWidget(self.pushButton_ReadFile)


        self.verticalLayout_3.addLayout(self.horizontalLayout_4)

        self.horizontalLayout_6 = QHBoxLayout()
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.pushButton_Play = QPushButton(self.groupBox_File)
        self.pushButton_Play.setObjectName(u"pushButton_Play")
        sizePolicy4.setHeightForWidth(self.pushButton_Play.sizePolicy().hasHeightForWidth())
        self.pushButton_Play.setSizePolicy(sizePolicy4)

        self.horizontalLayout_6.addWidget(self.pushButton_Play)

        self.pushButton_Next = QPushButton(self.groupBox_File)
        self.pushButton_Next.setObjectName(u"pushButton_Next")
        sizePolicy4.setHeightForWidth(self.pushButton_Next.sizePolicy().hasHeightForWidth())
        self.pushButton_Next.setSizePolicy(sizePolicy4)

        self.horizontalLayout_6.addWidget(self.pushButton_Next)


        self.verticalLayout_3.addLayout(self.horizontalLayout_6)

        self.horizontalLayout_15 = QHBoxLayout()
        self.horizontalLayout_15.setObjectName(u"horizontalLayout_15")
        self.pushButton_CloseFile = QPushButton(self.groupBox_File)
        self.pushButton_CloseFile.setObjectName(u"pushButton_CloseFile")

        self.horizontalLayout_15.addWidget(self.pushButton_CloseFile)

        self.pushButton_SaveTable = QPushButton(self.groupBox_File)
        self.pushButton_SaveTable.setObjectName(u"pushButton_SaveTable")

        self.horizontalLayout_15.addWidget(self.pushButton_SaveTable)


        self.verticalLayout_3.addLayout(self.horizontalLayout_15)

        self.verticalLayout_7 = QVBoxLayout()
        self.verticalLayout_7.setObjectName(u"verticalLayout_7")
        self.progressBar_file = QProgressBar(self.groupBox_File)
        self.progressBar_file.setObjectName(u"progressBar_file")
        self.progressBar_file.setValue(0)

        self.verticalLayout_7.addWidget(self.progressBar_file)


        self.verticalLayout_3.addLayout(self.verticalLayout_7)


        self.verticalLayout.addWidget(self.groupBox_File)

        self.groupBox_motor = QGroupBox(self.groupBox_Config)
        self.groupBox_motor.setObjectName(u"groupBox_motor")
        font1 = QFont()
        font1.setFamilies([u"Times New Roman"])
        font1.setPointSize(9)
        font1.setBold(True)
        self.groupBox_motor.setFont(font1)
        self.verticalLayout_4 = QVBoxLayout(self.groupBox_motor)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.horizontalLayout_16 = QHBoxLayout()
        self.horizontalLayout_16.setObjectName(u"horizontalLayout_16")
        self.pushButton_MotorConnect = QPushButton(self.groupBox_motor)
        self.pushButton_MotorConnect.setObjectName(u"pushButton_MotorConnect")

        self.horizontalLayout_16.addWidget(self.pushButton_MotorConnect)

        self.pushButton_MotorDisconnect = QPushButton(self.groupBox_motor)
        self.pushButton_MotorDisconnect.setObjectName(u"pushButton_MotorDisconnect")

        self.horizontalLayout_16.addWidget(self.pushButton_MotorDisconnect)


        self.verticalLayout_4.addLayout(self.horizontalLayout_16)

        self.pushButton_2 = QPushButton(self.groupBox_motor)
        self.pushButton_2.setObjectName(u"pushButton_2")

        self.verticalLayout_4.addWidget(self.pushButton_2)

        self.horizontalLayout_12 = QHBoxLayout()
        self.horizontalLayout_12.setObjectName(u"horizontalLayout_12")
        self.lineEdit_MoveAngel = QLineEdit(self.groupBox_motor)
        self.lineEdit_MoveAngel.setObjectName(u"lineEdit_MoveAngel")
        sizePolicy4.setHeightForWidth(self.lineEdit_MoveAngel.sizePolicy().hasHeightForWidth())
        self.lineEdit_MoveAngel.setSizePolicy(sizePolicy4)

        self.horizontalLayout_12.addWidget(self.lineEdit_MoveAngel)

        self.pushButton_MoveAngel = QPushButton(self.groupBox_motor)
        self.pushButton_MoveAngel.setObjectName(u"pushButton_MoveAngel")
        sizePolicy4.setHeightForWidth(self.pushButton_MoveAngel.sizePolicy().hasHeightForWidth())
        self.pushButton_MoveAngel.setSizePolicy(sizePolicy4)

        self.horizontalLayout_12.addWidget(self.pushButton_MoveAngel)


        self.verticalLayout_4.addLayout(self.horizontalLayout_12)


        self.verticalLayout.addWidget(self.groupBox_motor)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout.addItem(self.verticalSpacer)


        self.gridLayout.addWidget(self.groupBox_Config, 0, 2, 1, 1)

        self.line = QFrame(self.centralwidget)
        self.line.setObjectName(u"line")
        self.line.setFrameShape(QFrame.Shape.HLine)
        self.line.setFrameShadow(QFrame.Shadow.Sunken)

        self.gridLayout.addWidget(self.line, 1, 0, 1, 1)

        self.line_2 = QFrame(self.centralwidget)
        self.line_2.setObjectName(u"line_2")
        self.line_2.setFrameShape(QFrame.Shape.HLine)
        self.line_2.setFrameShadow(QFrame.Shadow.Sunken)

        self.gridLayout.addWidget(self.line_2, 1, 2, 1, 1)

        self.tabWidget_Display = QTabWidget(self.centralwidget)
        self.tabWidget_Display.setObjectName(u"tabWidget_Display")
        sizePolicy5 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy5.setHorizontalStretch(12)
        sizePolicy5.setVerticalStretch(10)
        sizePolicy5.setHeightForWidth(self.tabWidget_Display.sizePolicy().hasHeightForWidth())
        self.tabWidget_Display.setSizePolicy(sizePolicy5)
        self.tabWidget_Display.setFont(font)
        self.tab_Placeholder = QWidget()
        self.tab_Placeholder.setObjectName(u"tab_Placeholder")
        self.tabWidget_Display.addTab(self.tab_Placeholder, "")
        self.tab_ADC = QWidget()
        self.tab_ADC.setObjectName(u"tab_ADC")
        self.gridLayout_2 = QGridLayout(self.tab_ADC)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.widget_tx0rx1 = QWidget(self.tab_ADC)
        self.widget_tx0rx1.setObjectName(u"widget_tx0rx1")
        sizePolicy6 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy6.setHorizontalStretch(0)
        sizePolicy6.setVerticalStretch(0)
        sizePolicy6.setHeightForWidth(self.widget_tx0rx1.sizePolicy().hasHeightForWidth())
        self.widget_tx0rx1.setSizePolicy(sizePolicy6)

        self.gridLayout_2.addWidget(self.widget_tx0rx1, 0, 1, 1, 1)

        self.widget_tx1rx0 = QWidget(self.tab_ADC)
        self.widget_tx1rx0.setObjectName(u"widget_tx1rx0")
        sizePolicy6.setHeightForWidth(self.widget_tx1rx0.sizePolicy().hasHeightForWidth())
        self.widget_tx1rx0.setSizePolicy(sizePolicy6)

        self.gridLayout_2.addWidget(self.widget_tx1rx0, 1, 0, 1, 1)

        self.widget_tx1rx1 = QWidget(self.tab_ADC)
        self.widget_tx1rx1.setObjectName(u"widget_tx1rx1")
        sizePolicy6.setHeightForWidth(self.widget_tx1rx1.sizePolicy().hasHeightForWidth())
        self.widget_tx1rx1.setSizePolicy(sizePolicy6)

        self.gridLayout_2.addWidget(self.widget_tx1rx1, 1, 1, 1, 1)

        self.widget_tx0rx0 = QWidget(self.tab_ADC)
        self.widget_tx0rx0.setObjectName(u"widget_tx0rx0")
        sizePolicy6.setHeightForWidth(self.widget_tx0rx0.sizePolicy().hasHeightForWidth())
        self.widget_tx0rx0.setSizePolicy(sizePolicy6)

        self.gridLayout_2.addWidget(self.widget_tx0rx0, 0, 0, 1, 1)

        self.tabWidget_Display.addTab(self.tab_ADC, "")
        self.tab_ConstellationDiagram = QWidget()
        self.tab_ConstellationDiagram.setObjectName(u"tab_ConstellationDiagram")
        self.gridLayout_6 = QGridLayout(self.tab_ConstellationDiagram)
        self.gridLayout_6.setObjectName(u"gridLayout_6")
        self.widget_CDtx0rx0 = QWidget(self.tab_ConstellationDiagram)
        self.widget_CDtx0rx0.setObjectName(u"widget_CDtx0rx0")

        self.gridLayout_6.addWidget(self.widget_CDtx0rx0, 0, 0, 1, 1)

        self.widget_CDtx0rx1 = QWidget(self.tab_ConstellationDiagram)
        self.widget_CDtx0rx1.setObjectName(u"widget_CDtx0rx1")

        self.gridLayout_6.addWidget(self.widget_CDtx0rx1, 0, 1, 1, 1)

        self.widget_CDtx1rx0 = QWidget(self.tab_ConstellationDiagram)
        self.widget_CDtx1rx0.setObjectName(u"widget_CDtx1rx0")

        self.gridLayout_6.addWidget(self.widget_CDtx1rx0, 1, 0, 1, 1)

        self.widget_CDtx1rx1 = QWidget(self.tab_ConstellationDiagram)
        self.widget_CDtx1rx1.setObjectName(u"widget_CDtx1rx1")

        self.gridLayout_6.addWidget(self.widget_CDtx1rx1, 1, 1, 1, 1)

        self.tabWidget_Display.addTab(self.tab_ConstellationDiagram, "")
        self.tab_DirectWave = QWidget()
        self.tab_DirectWave.setObjectName(u"tab_DirectWave")
        self.gridLayout_5 = QGridLayout(self.tab_DirectWave)
        self.gridLayout_5.setObjectName(u"gridLayout_5")
        self.widget_DWtx0rx0 = QWidget(self.tab_DirectWave)
        self.widget_DWtx0rx0.setObjectName(u"widget_DWtx0rx0")

        self.gridLayout_5.addWidget(self.widget_DWtx0rx0, 0, 0, 1, 1)

        self.widget_DWtx0rx1 = QWidget(self.tab_DirectWave)
        self.widget_DWtx0rx1.setObjectName(u"widget_DWtx0rx1")

        self.gridLayout_5.addWidget(self.widget_DWtx0rx1, 0, 1, 1, 1)

        self.widget_DWtx1rx0 = QWidget(self.tab_DirectWave)
        self.widget_DWtx1rx0.setObjectName(u"widget_DWtx1rx0")

        self.gridLayout_5.addWidget(self.widget_DWtx1rx0, 1, 0, 1, 1)

        self.widget_DWtx1rx1 = QWidget(self.tab_DirectWave)
        self.widget_DWtx1rx1.setObjectName(u"widget_DWtx1rx1")

        self.gridLayout_5.addWidget(self.widget_DWtx1rx1, 1, 1, 1, 1)

        self.tabWidget_Display.addTab(self.tab_DirectWave, "")
        self.tab__AmpPhase = QWidget()
        self.tab__AmpPhase.setObjectName(u"tab__AmpPhase")
        self.gridLayout_7 = QGridLayout(self.tab__AmpPhase)
        self.gridLayout_7.setObjectName(u"gridLayout_7")
        self.widget_APtx0rx0 = QWidget(self.tab__AmpPhase)
        self.widget_APtx0rx0.setObjectName(u"widget_APtx0rx0")

        self.gridLayout_7.addWidget(self.widget_APtx0rx0, 0, 0, 1, 1)

        self.widget_APtx0rx1 = QWidget(self.tab__AmpPhase)
        self.widget_APtx0rx1.setObjectName(u"widget_APtx0rx1")

        self.gridLayout_7.addWidget(self.widget_APtx0rx1, 0, 1, 1, 1)

        self.widget_APtx1rx0 = QWidget(self.tab__AmpPhase)
        self.widget_APtx1rx0.setObjectName(u"widget_APtx1rx0")

        self.gridLayout_7.addWidget(self.widget_APtx1rx0, 1, 0, 1, 1)

        self.widget_APtx1rx1 = QWidget(self.tab__AmpPhase)
        self.widget_APtx1rx1.setObjectName(u"widget_APtx1rx1")

        self.gridLayout_7.addWidget(self.widget_APtx1rx1, 1, 1, 1, 1)

        self.tabWidget_Display.addTab(self.tab__AmpPhase, "")
        self.tab_1DFFT = QWidget()
        self.tab_1DFFT.setObjectName(u"tab_1DFFT")
        self.tab_1DFFT.setMinimumSize(QSize(0, 0))
        self.gridLayout_3 = QGridLayout(self.tab_1DFFT)
        self.gridLayout_3.setObjectName(u"gridLayout_3")
        self.widget_1DFFTtx0rx0 = QWidget(self.tab_1DFFT)
        self.widget_1DFFTtx0rx0.setObjectName(u"widget_1DFFTtx0rx0")

        self.gridLayout_3.addWidget(self.widget_1DFFTtx0rx0, 0, 0, 1, 1)

        self.widget_1DFFTtx0rx1 = QWidget(self.tab_1DFFT)
        self.widget_1DFFTtx0rx1.setObjectName(u"widget_1DFFTtx0rx1")

        self.gridLayout_3.addWidget(self.widget_1DFFTtx0rx1, 0, 1, 1, 1)

        self.widget_1DFFTtx1rx0 = QWidget(self.tab_1DFFT)
        self.widget_1DFFTtx1rx0.setObjectName(u"widget_1DFFTtx1rx0")

        self.gridLayout_3.addWidget(self.widget_1DFFTtx1rx0, 1, 0, 1, 1)

        self.widget_1DFFTtx1rx1 = QWidget(self.tab_1DFFT)
        self.widget_1DFFTtx1rx1.setObjectName(u"widget_1DFFTtx1rx1")

        self.gridLayout_3.addWidget(self.widget_1DFFTtx1rx1, 1, 1, 1, 1)

        self.tabWidget_Display.addTab(self.tab_1DFFT, "")
        self.tab_Frequency = QWidget()
        self.tab_Frequency.setObjectName(u"tab_Frequency")
        self.horizontalLayout_13 = QHBoxLayout(self.tab_Frequency)
        self.horizontalLayout_13.setObjectName(u"horizontalLayout_13")
        self.widget_frequency = QWidget(self.tab_Frequency)
        self.widget_frequency.setObjectName(u"widget_frequency")

        self.horizontalLayout_13.addWidget(self.widget_frequency)

        self.tabWidget_Display.addTab(self.tab_Frequency, "")
        self.tab_2DFFT = QWidget()
        self.tab_2DFFT.setObjectName(u"tab_2DFFT")
        self.gridLayout_4 = QGridLayout(self.tab_2DFFT)
        self.gridLayout_4.setObjectName(u"gridLayout_4")
        self.widget_2DFFTtx0rx0 = QWidget(self.tab_2DFFT)
        self.widget_2DFFTtx0rx0.setObjectName(u"widget_2DFFTtx0rx0")

        self.gridLayout_4.addWidget(self.widget_2DFFTtx0rx0, 0, 0, 1, 1)

        self.widget_2DFFTtx0rx1 = QWidget(self.tab_2DFFT)
        self.widget_2DFFTtx0rx1.setObjectName(u"widget_2DFFTtx0rx1")

        self.gridLayout_4.addWidget(self.widget_2DFFTtx0rx1, 0, 1, 1, 1)

        self.widget_2DFFTtx1rx0 = QWidget(self.tab_2DFFT)
        self.widget_2DFFTtx1rx0.setObjectName(u"widget_2DFFTtx1rx0")

        self.gridLayout_4.addWidget(self.widget_2DFFTtx1rx0, 1, 0, 1, 1)

        self.widget_2DFFTtx1rx1 = QWidget(self.tab_2DFFT)
        self.widget_2DFFTtx1rx1.setObjectName(u"widget_2DFFTtx1rx1")

        self.gridLayout_4.addWidget(self.widget_2DFFTtx1rx1, 1, 1, 1, 1)

        self.tabWidget_Display.addTab(self.tab_2DFFT, "")
        self.tab_MUSICspectrum = QWidget()
        self.tab_MUSICspectrum.setObjectName(u"tab_MUSICspectrum")
        self.horizontalLayout_8 = QHBoxLayout(self.tab_MUSICspectrum)
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.widget_MUSICspectrum = QWidget(self.tab_MUSICspectrum)
        self.widget_MUSICspectrum.setObjectName(u"widget_MUSICspectrum")

        self.horizontalLayout_8.addWidget(self.widget_MUSICspectrum)

        self.tabWidget_Display.addTab(self.tab_MUSICspectrum, "")
        self.tab_MUSIC2dSpectrum = QWidget()
        self.tab_MUSIC2dSpectrum.setObjectName(u"tab_MUSIC2dSpectrum")
        self.horizontalLayout_7 = QHBoxLayout(self.tab_MUSIC2dSpectrum)
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.widget_MUSIC2dSpectrum = QWidget(self.tab_MUSIC2dSpectrum)
        self.widget_MUSIC2dSpectrum.setObjectName(u"widget_MUSIC2dSpectrum")

        self.horizontalLayout_7.addWidget(self.widget_MUSIC2dSpectrum)

        self.tabWidget_Display.addTab(self.tab_MUSIC2dSpectrum, "")
        self.tab_PoitCloud = QWidget()
        self.tab_PoitCloud.setObjectName(u"tab_PoitCloud")
        self.verticalLayout_6 = QVBoxLayout(self.tab_PoitCloud)
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.widget_PointCloud = QWidget(self.tab_PoitCloud)
        self.widget_PointCloud.setObjectName(u"widget_PointCloud")

        self.verticalLayout_6.addWidget(self.widget_PointCloud)

        self.tabWidget_Display.addTab(self.tab_PoitCloud, "")
        self.tab_Video = QWidget()
        self.tab_Video.setObjectName(u"tab_Video")
        self.verticalLayout_8 = QVBoxLayout(self.tab_Video)
        self.verticalLayout_8.setObjectName(u"verticalLayout_8")
        self.widget_video = QWidget(self.tab_Video)
        self.widget_video.setObjectName(u"widget_video")

        self.verticalLayout_8.addWidget(self.widget_video)

        self.tabWidget_Display.addTab(self.tab_Video, "")

        self.gridLayout.addWidget(self.tabWidget_Display, 0, 0, 1, 1)

        self.line_4 = QFrame(self.centralwidget)
        self.line_4.setObjectName(u"line_4")
        self.line_4.setFrameShape(QFrame.Shape.VLine)
        self.line_4.setFrameShadow(QFrame.Shadow.Sunken)

        self.gridLayout.addWidget(self.line_4, 0, 1, 1, 1)

        self.widget_extra = QWidget(self.centralwidget)
        self.widget_extra.setObjectName(u"widget_extra")

        self.gridLayout.addWidget(self.widget_extra, 2, 2, 1, 1)

        MainWindow.setCentralWidget(self.centralwidget)
        self.tabWidget_Message.raise_()
        self.tabWidget_Display.raise_()
        self.line_3.raise_()
        self.line.raise_()
        self.line_4.raise_()
        self.line_2.raise_()
        self.groupBox_Config.raise_()
        self.widget_extra.raise_()
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1022, 22))
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)
        self.pushButton_Connect.clicked.connect(MainWindow.UDP_connect)
        self.pushButton_ReadFile.clicked.connect(MainWindow.ReadFile)
        self.pushButton_Next.clicked.connect(MainWindow.ShowNextFrame)
        self.pushButton_CloseFile.clicked.connect(MainWindow.CloseFile)
        self.pushButton_SaveTable.clicked.connect(MainWindow.SaveTable)
        self.pushButton_LoadMode.clicked.connect(MainWindow.LoadCalibratioMode)
        self.pushButton_MotorConnect.clicked.connect(MainWindow.MotorConnect)
        self.pushButton_MotorDisconnect.clicked.connect(MainWindow.MotorDisconnect)
        self.pushButton_MoveAngel.clicked.connect(MainWindow.AngelMove)
        self.pushButton_Play.clicked.connect(MainWindow.PlayMatfile)
        self.pushButton_2.clicked.connect(MainWindow.circleTest)
        self.pushButton_Disconnect.clicked.connect(MainWindow.UDP_disconnect)
        self.pushButton_Video_open.clicked.connect(MainWindow.VideoOpen)
        self.pushButton_video_close.clicked.connect(MainWindow.VideoClose)

        self.tabWidget_Message.setCurrentIndex(0)
        self.tabWidget_Display.setCurrentIndex(11)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.tabWidget_Message.setTabText(self.tabWidget_Message.indexOf(self.tab_log), QCoreApplication.translate("MainWindow", u"LogMessage", None))
        self.tabWidget_Message.setTabText(self.tabWidget_Message.indexOf(self.tab_Distance), QCoreApplication.translate("MainWindow", u"Distance ", None))
        self.tabWidget_Message.setTabText(self.tabWidget_Message.indexOf(self.tab_XYZpoint), QCoreApplication.translate("MainWindow", u"Point / Angle", None))
        self.groupBox_Config.setTitle(QCoreApplication.translate("MainWindow", u"Setting", None))
        self.groupBox_UDP.setTitle(QCoreApplication.translate("MainWindow", u"DataString", None))
        self.pushButton_Connect.setText(QCoreApplication.translate("MainWindow", u"Connect", None))
        self.pushButton_Disconnect.setText(QCoreApplication.translate("MainWindow", u"Disconnect", None))
        self.pushButton_Video_open.setText(QCoreApplication.translate("MainWindow", u"Video Open", None))
        self.pushButton_video_close.setText(QCoreApplication.translate("MainWindow", u"Video Close", None))
        self.checkBox_IsSave.setText(QCoreApplication.translate("MainWindow", u"SaveMat", None))
        self.checkBox_HammingWindow.setText(QCoreApplication.translate("MainWindow", u"Hamming", None))
        self.groupBox_calibration.setTitle(QCoreApplication.translate("MainWindow", u"Calibration", None))
        self.checkBox_CalibrationMode.setText(QCoreApplication.translate("MainWindow", u"Calibration Mode\u200c", None))
        self.checkBox_channel_calibration.setText(QCoreApplication.translate("MainWindow", u"Apply Calibration", None))
        self.radioButton_FFT.setText(QCoreApplication.translate("MainWindow", u"FFT", None))
        self.radioButton_LS.setText(QCoreApplication.translate("MainWindow", u"LS", None))
        self.radioButton_WLS.setText(QCoreApplication.translate("MainWindow", u"WLS", None))
        self.pushButton_LoadMode.setText(QCoreApplication.translate("MainWindow", u"Load Model", None))
        self.checkBox_addnoise.setText(QCoreApplication.translate("MainWindow", u"Add Noise", None))
        self.checkBox_align_iq.setText(QCoreApplication.translate("MainWindow", u"Align IQ", None))
        self.groupBox_File.setTitle(QCoreApplication.translate("MainWindow", u"File", None))
        self.pushButton_ReadFile.setText(QCoreApplication.translate("MainWindow", u"Read File", None))
        self.pushButton_Play.setText(QCoreApplication.translate("MainWindow", u"Play", None))
        self.pushButton_Next.setText(QCoreApplication.translate("MainWindow", u"Next", None))
        self.pushButton_CloseFile.setText(QCoreApplication.translate("MainWindow", u"Close Init", None))
        self.pushButton_SaveTable.setText(QCoreApplication.translate("MainWindow", u"Save Table", None))
        self.groupBox_motor.setTitle(QCoreApplication.translate("MainWindow", u"Motor Control", None))
        self.pushButton_MotorConnect.setText(QCoreApplication.translate("MainWindow", u"Motor Init", None))
        self.pushButton_MotorDisconnect.setText(QCoreApplication.translate("MainWindow", u"Motor Stop", None))
        self.pushButton_2.setText(QCoreApplication.translate("MainWindow", u"Circle Test", None))
        self.pushButton_MoveAngel.setText(QCoreApplication.translate("MainWindow", u"Move", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_Placeholder), QCoreApplication.translate("MainWindow", u"Placeholder", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_ADC), QCoreApplication.translate("MainWindow", u"ADC", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_ConstellationDiagram), QCoreApplication.translate("MainWindow", u"StarChart", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_DirectWave), QCoreApplication.translate("MainWindow", u"Direct wave", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab__AmpPhase), QCoreApplication.translate("MainWindow", u"Amp/Phase", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_1DFFT), QCoreApplication.translate("MainWindow", u"1DFFT", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_Frequency), QCoreApplication.translate("MainWindow", u"Frequency", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_2DFFT), QCoreApplication.translate("MainWindow", u"2DFFT", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_MUSICspectrum), QCoreApplication.translate("MainWindow", u"Spectrum", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_MUSIC2dSpectrum), QCoreApplication.translate("MainWindow", u"2DSpectrum", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_PoitCloud), QCoreApplication.translate("MainWindow", u"Point Cloud", None))
        self.tabWidget_Display.setTabText(self.tabWidget_Display.indexOf(self.tab_Video), QCoreApplication.translate("MainWindow", u"Video", None))
    # retranslateUi

