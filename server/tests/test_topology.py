"""拓扑模块单元测试：设备类型推断、厂商识别、IP/MAC 格式校验"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from modules.topology import infer_device_type, infer_vendor
from modules.topology import TopologyDiscoverer


# ── infer_device_type ──────────────────────────────────────────

class TestInferDeviceType:
    def test_router_cisco_ios(self):
        assert infer_device_type("Cisco IOS Software, C2960 Software") == "router"

    def test_router_mikrotik(self):
        assert infer_device_type("MikroTik RouterOS 6.47") == "router"

    def test_router_bgp_mention(self):
        assert infer_device_type("Linux with BGP routing daemon") == "router"

    def test_switch_catalyst(self):
        assert infer_device_type("Cisco Catalyst 2960-X Series") == "switch"

    def test_switch_procurve(self):
        assert infer_device_type("HP ProCurve J9773A") == "switch"

    def test_switch_icos(self):
        assert infer_device_type("ICOS managed switch v2.0") == "switch"

    def test_firewall_fortinet(self):
        assert infer_device_type("FortiGate-60E v6.2") == "firewall"

    def test_firewall_pfsense(self):
        assert infer_device_type("pfSense 2.5.0-RELEASE (amd64)") == "firewall"

    def test_firewall_sonicwall(self):
        assert infer_device_type("SonicWall TZ400") == "firewall"

    def test_access_point_unifi(self):
        assert infer_device_type("UniFi AP-AC-Pro") == "access_point"

    def test_access_point_cisco_airo(self):
        assert infer_device_type("Cisco Aironet 2800 Series") == "access_point"

    def test_camera_hikvision(self):
        assert infer_device_type("Hikvision DS-2CD2T47G2-L") == "camera"

    def test_camera_dahua(self):
        assert infer_device_type("Dahua IPC-HDW2231R-ZS") == "camera"

    def test_server_windows(self):
        assert infer_device_type("Windows Server 2019 Standard") == "server"

    def test_server_vmware(self):
        assert infer_device_type("VMware ESXi 7.0.3") == "server"

    def test_server_linux(self):
        assert infer_device_type("Linux debian 5.10.0") == "server"

    def test_unknown(self):
        assert infer_device_type("Generic embedded device") == "unknown"

    def test_empty_string(self):
        assert infer_device_type("") == "unknown"

    def test_sys_name_used(self):
        """sys_name 参数应参与匹配"""
        assert infer_device_type("", sys_name="RouterOS") == "router"

    def test_sys_name_fallback(self):
        assert infer_device_type("", sys_name="UniFi AP") == "access_point"


# ── infer_vendor ───────────────────────────────────────────────

class TestInferVendor:
    def test_cisco(self):
        assert infer_vendor("Cisco IOS XE") == "Cisco"

    def test_huawei(self):
        assert infer_vendor("Huawei VRP 8.1") == "Huawei"

    def test_hp_procurve(self):
        assert infer_vendor("HP ProCurve J9773A") == "HP"

    def test_hp_short(self):
        assert infer_vendor("hp 2920") == "HP"

    def test_arista(self):
        assert infer_vendor("Arista DCS-7050SX") == "Arista"

    def test_juniper(self):
        assert infer_vendor("Juniper MX480") == "Juniper"

    def test_mikrotik(self):
        assert infer_vendor("MikroTik RouterBOARD 750") == "MikroTik"

    def test_tplink(self):
        assert infer_vendor("TP-Link TL-SG1024D") == "TP-Link"

    def test_tplink_spaced(self):
        assert infer_vendor("TP Link Archer C7") == "TP-Link"

    def test_hikvision(self):
        assert infer_vendor("Hikvision DS-7616NI") == "Hikvision"

    def test_dahua(self):
        assert infer_vendor("Dahua NVR4104") == "Dahua"

    def test_fortinet(self):
        assert infer_vendor("Fortinet FortiGate-100D") == "Fortinet"

    def test_ubiquiti(self):
        assert infer_vendor("Ubiquiti EdgeRouter X") == "Ubiquiti"

    def test_unifi(self):
        assert infer_vendor("UniFi Switch 24 POE") == "Ubiquiti"

    def test_unknown(self):
        assert infer_vendor("Some random device") == "Unknown"

    def test_empty_string(self):
        assert infer_vendor("") == "Unknown"


# ── _looks_like_ip / _looks_like_mac ──────────────────────────

class TestLooksLike:
    def setup_method(self):
        self.d = TopologyDiscoverer()

    # looks_like_ip
    def test_ip_valid_private(self):
        assert self.d._looks_like_ip("10.0.0.1") is True

    def test_ip_valid_public(self):
        assert self.d._looks_like_ip("8.8.8.8") is True

    def test_ip_invalid_high_octet(self):
        assert self.d._looks_like_ip("256.1.2.3") is False

    def test_ip_invalid_format(self):
        assert self.d._looks_like_ip("abc.def") is False

    def test_ip_empty(self):
        assert self.d._looks_like_ip("") is False

    def test_ip_too_few_parts(self):
        assert self.d._looks_like_ip("10.0.1") is False

    def test_ip_non_numeric(self):
        assert self.d._looks_like_ip("10.0.a.1") is False

    # looks_like_mac
    def test_mac_colon_separated(self):
        assert self.d._looks_like_mac("aa:bb:cc:dd:ee:ff") is True

    def test_mac_hyphen_separated(self):
        assert self.d._looks_like_mac("AA-BB-CC-DD-EE-FF") is True

    def test_mac_dot_separated(self):
        assert self.d._looks_like_mac("aabb.ccdd.eeff") is True

    def test_mac_too_short(self):
        assert self.d._looks_like_mac("aa:bb:cc") is False

    def test_mac_empty(self):
        assert self.d._looks_like_mac("") is False

    def test_mac_invalid_chars(self):
        assert self.d._looks_like_mac("zz:yy:xx:ww:vv:uu") is False
