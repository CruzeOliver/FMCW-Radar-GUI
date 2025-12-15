import ctypes
from ctypes import (
    c_bool, c_uint, c_void_p, c_ulong, POINTER, c_ubyte, byref
)
import os
from typing import Optional
import math

# 类型别名
BOOL = c_bool
ULONG = c_ulong
PUCHAR = POINTER(c_ubyte)

class MotorController:
    """
    基于 CH375DLL.dll 的电机控制器
    完全复现 C++ 逻辑：
    - 初始化握手（40字节包）
    - 发送控制指令（35字节包）
    - 读取当前位置（25字节包）
    - 支持角度控制、停止、回零
    """

    INIT_PACKET_SIZE = 40
    CONTROL_PACKET_SIZE = 35
    STATUS_PACKET_SIZE = 25

    def __init__(self, dll_path: Optional[str] = None):
        if dll_path is None:
            # 默认查找同目录下的 DLL
            dll_path = os.path.join(os.path.dirname(__file__), "CH375DLL64.dll")

        if not os.path.exists(dll_path):
            raise FileNotFoundError(f"CH375 DLL 文件未找到: {dll_path}")

        try:
            self._dll = ctypes.WinDLL(dll_path)
        except OSError as e:
            raise RuntimeError(f"加载 DLL 失败，请确认是 64 位 Python 和 64 位 DLL 匹配: {e}")

        self._base_steps = 0
        self._total_angle = 0.0
        self._is_initialized = False

        self._define_functions()

    def _define_functions(self):
        """定义 CH375DLL 函数原型"""
        # HANDLE CH375OpenDevice(ULONG Index);
        self._CH375OpenDevice = self._dll.CH375OpenDevice
        self._CH375OpenDevice.argtypes = [c_uint]
        self._CH375OpenDevice.restype = c_void_p

        # BOOL CH375SetTimeout(ULONG Index, ULONG WriteTimeout, ULONG ReadTimeout);
        self._CH375SetTimeout = self._dll.CH375SetTimeout
        self._CH375SetTimeout.argtypes = [c_uint, c_ulong, c_ulong]
        self._CH375SetTimeout.restype = c_bool

        # BOOL CH375WriteData(ULONG Index, PVOID pBuffer, PULONG pLength);
        self._CH375WriteData = self._dll.CH375WriteData
        self._CH375WriteData.argtypes = [c_uint, c_void_p, POINTER(c_ulong)]
        self._CH375WriteData.restype = c_bool

        # BOOL CH375ReadData(ULONG Index, PVOID pBuffer, PULONG pLength);
        self._CH375ReadData = self._dll.CH375ReadData
        self._CH375ReadData.argtypes = [c_uint, c_void_p, POINTER(c_ulong)]
        self._CH375ReadData.restype = c_bool

    def usb_initialize(self) -> bool:
        """打开设备并设置超时"""
        handle = self._CH375OpenDevice(0)
        if not handle or handle == -1:
            print("[ERROR] USB device open failed.")
            return False

        if not self._CH375SetTimeout(0, 5000, 1000):
            print("[ERROR] Set USB timeout failed.")
            return False

        print("[INFO] USB initialized successfully.")
        return True

    def _angle_to_steps(self, angle: float) -> int:
        """将角度转换为步数"""
        steps_per_rev = 200.0 * 16 * 414024 / 36620.12
        return int(abs(angle) / 360.0 * steps_per_rev)

    def motor_initialize(self) -> bool:
        """
        发送初始化包，获取初始步数。
        [FIX] 移除 _is_initialized 检查，此函数必须每次都执行 Write/Read
        以清空缓冲区，为下一次 Write(Move) 做准备。
        """
        # if self._is_initialized:  <-- 删除这一行
        #     return True           <-- 删除这一行

        # 构造 40 字节初始化包 (您已修复)
        init_data = [0] * (self.INIT_PACKET_SIZE - 6)
        init_data.extend([0x55, 0x04, 0xD9, 0x04, 0xD9, 0x01])
        init_packet = (c_ubyte * self.INIT_PACKET_SIZE)(*init_data)

        length = ULONG(self.INIT_PACKET_SIZE)
        success = self._CH375WriteData(0, init_packet, byref(length))

        if not success or length.value != self.INIT_PACKET_SIZE:
            print("[ERROR] Write init packet failed.")
            self._is_initialized = False # 确保状态正确
            return False

        # 读取返回状态包（25字节）
        recv_buf = (c_ubyte * self.STATUS_PACKET_SIZE)()
        recv_len = ULONG(self.STATUS_PACKET_SIZE)
        success = self._CH375ReadData(0, recv_buf, byref(recv_len))

        if not success or recv_len.value < 16:
            print("[ERROR] Read init response failed.")
            self._is_initialized = False # 确保状态正确
            return False

        # 解析 base_steps（字节12-15）
        self._base_steps = (
            (recv_buf[12] << 24) |
            (recv_buf[13] << 16) |
            (recv_buf[14] << 8) |
            recv_buf[15]
        )
        self._is_initialized = True
        # 注意：这里我们不再打印 "Motor initialized"，因为它会刷屏
        # print(f"[INFO] Motor initialized. Base steps: {self._base_steps}")
        return True

    def motor_start(self, angle: float) -> bool:
        """启动电机运动指定角度"""
        if math.isclose(angle, 0.0, abs_tol=1e-5):
            return True

        if not self._is_initialized or not self.motor_initialize():
            return False

        # 构造 35 字节控制包
        packet = (c_ubyte * self.CONTROL_PACKET_SIZE)(0)

        # 字节0：控制字
        direction_bit = 0b00000111 if angle > 0 else 0b00000110
        packet[0] = 0b11100000 | direction_bit

        # 速度参数
        speed = 100000 // 500  # 200
        speed_half = speed // 2

        packet[3] = (speed >> 8) & 0xFF
        packet[4] = speed & 0xFF
        packet[5] = 0x02
        packet[6] = 0xD0
        packet[7] = (speed_half >> 8) & 0xFF
        packet[8] = speed_half & 0xFF

        # 步数（4字节，大端）
        steps = self._angle_to_steps(angle)
        packet[9]  = (steps >> 24) & 0xFF
        packet[10] = (steps >> 16) & 0xFF
        packet[11] = (steps >> 8) & 0xFF
        packet[12] = steps & 0xFF

        # 控制标志
        packet[33] = 0x01
        packet[34] = 0xAA

        length = ULONG(self.CONTROL_PACKET_SIZE)
        success = self._CH375WriteData(0, packet, byref(length))

        if not success:
            print("[ERROR] Write control packet failed.")
            return False

        self._total_angle += angle
        print(f"[INFO] Motor started. Angle: {angle:.2f}°, Total: {self._total_angle:.2f}°")
        return True

    def motor_stop(self) -> bool:
        """停止所有电机"""
        packet = (c_ubyte * self.CONTROL_PACKET_SIZE)(0)
        STOP_BYTE = 0xBE  # 10111110

        packet[0] = STOP_BYTE  # 电机1
        packet[1] = STOP_BYTE  # 电机2
        packet[2] = STOP_BYTE  # 电机3

        packet[33] = 0x01  # 总使能保持为1
        packet[34] = 0xAA  # 标志位

        length = ULONG(self.CONTROL_PACKET_SIZE)
        success = self._CH375WriteData(0, packet, byref(length))

        if not success or length.value != self.CONTROL_PACKET_SIZE:
            print(f"[ERROR] Motor stop failed. Result: {success}, Length: {length.value}")
            return False

        print("[INFO] All motors stopped successfully")
        return True

    def motor_reset(self) -> bool:
        """回到原点（反向走累计角度）"""
        if math.isclose(self._total_angle, 0.0, abs_tol=1e-5):
            print("[INFO] Already at origin. No reset needed.")
            return True

        if not self.motor_start(-self._total_angle):
            print("[ERROR] Failed to reset angle.")
            return False

        self._total_angle = 0.0
        print("[INFO] Motor reset to origin.")
        return True

    def motor_get_current_angle(self) -> float:
        """读取当前角度（相对初始位置）"""
        if not self._is_initialized:
            print("[WARN] Not initialized. Returning cumulative angle.")
            return self._total_angle

        recv_buf = (c_ubyte * self.STATUS_PACKET_SIZE)()
        recv_len = ULONG(self.STATUS_PACKET_SIZE)
        success = self._CH375ReadData(0, recv_buf, byref(recv_len))

        if not success or recv_len.value < 16:
            print("[ERROR] Read current position failed.")
            return float('nan')

        # 解析当前步数（字节12-15）
        current_steps = (
            (recv_buf[12] << 24) |
            (recv_buf[13] << 16) |
            (recv_buf[14] << 8) |
            recv_buf[15]
        )

        # 计算相对步数
        relative_steps = current_steps - self._base_steps

        # 转换为角度
        steps_per_rev = 200.0 * 16 * 414024 / 36620.12
        angle = relative_steps * 360.0 / steps_per_rev

        return angle