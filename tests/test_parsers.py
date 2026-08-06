"""Parser tests against HTML captured from real devices: firmware V100.9.4
(well-formed) and V1.6 (malformed closing tags like `</td align="center">`)."""

import exporter

PORT_SETTINGS_V100 = """
<table border="1">
  <tr>
    <th rowspan="2" width="90">Port</th>
    <th rowspan="2" width="90">State</th>
    <th colspan="2">Speed/Duplex</th>
    <th colspan="2">Flow Control</th>
  </tr>
  <tr>
    <th width="90">Config</th>
    <th width="90">Actual</th>
    <th width="90">Config</th>
    <th width="90">Actual</th>
  </tr>
  <tr>
    <td>Port 1</td>
    <td>Enable</td>
    <td>Auto</td>
    <td>2500Full</td>
    <td>Off</td>
    <td>Off</td>
  </tr>
  <tr>
    <td>Port 6</td>
    <td>Enable</td>
    <td>Auto</td>
    <td>Link Down</td>
    <td>Off</td>
    <td>Off</td>
  </tr>
</table>
"""

PORT_STATS_V100 = """
<table>
  <tr>
    <th style="width:80px;">Port</th>
    <th style="width:80px;">State</th>
    <th style="width:80px;">Link Status</th>
    <th style="width:100px;">TxGoodPkt</th>
    <th style="width:100px;">TxBadPkt</th>
    <th style="width:100px;">RxGoodPkt</th>
    <th style="width:100px;">RxBadPkt</th>
  </tr>
  <tr>
    <td>Port 1</td>
    <td>Enable</td>
    <td>Link Up</td>
    <td>4209323696</td>
    <td>0</td>
    <td>4196169487</td>
    <td>0</td>
  </tr>
</table>
"""

PORT_STATS_V16 = """
<table border="1">
  <tr>
    <th width="80">Port</th>
    <th width="90">State</th>
    <th>Link Status</th>
    <th>TxGoodPkt</th>
    <th>TxBadPkt</th>
    <th>RxGoodPkt</th>
    <th>RxBadPkt</th>
  </tr>
  <tr>
    <td align="center">Port 1</td>
    <td align="center">Enable</td>
    <td align="center">Link Up</td>
    <td align="center">680749884</td>
    <td align="center">31</td>
    <td align="center">3111773920</td>
    <td align="center">31</td>
  </tr>
</table>
"""

INFO_V16 = """
<table>
  <tr>
    <th width="150">Device Model</th>
    <td align="left" style="width:250px;">KP-9000-6XHML-X2</td align="center">
  </tr>
  <tr>
    <th>MAC Address</th>
    <td align="left" style="width:250px;">78:D8:00:31:B8:6F</td align="center">
  </tr>
  <tr>
    <th>Firmware Version</th>
    <td align="left" style="width:250px;">V1.6</td align="center">
  </tr>
</table>
"""


def test_port_settings_v100():
    ports = exporter.parse_port_settings(PORT_SETTINGS_V100)
    assert ports["Port 1"] == {"state": "Enable", "actual_speed": "2500Full", "flow": "Off"}
    assert ports["Port 6"]["actual_speed"] == "Link Down"
    assert exporter.SPEED_MBPS.get(ports["Port 6"]["actual_speed"], 0) == 0


def test_port_stats_v100():
    ports = exporter.parse_port_stats(PORT_STATS_V100)
    assert ports["Port 1"]["link"] == "Link Up"
    assert ports["Port 1"]["tx_good"] == 4209323696
    assert ports["Port 1"]["rx_good"] == 4196169487


def test_port_stats_v16_malformed_cells():
    ports = exporter.parse_port_stats(PORT_STATS_V16)
    assert ports["Port 1"]["tx_bad"] == 31
    assert ports["Port 1"]["rx_good"] == 3111773920


def test_info_v16_malformed_closing_tags():
    info = exporter.parse_info(INFO_V16)
    assert info["device_model"] == "KP-9000-6XHML-X2"
    assert info["mac_address"] == "78:D8:00:31:B8:6F"
    assert info["firmware_version"] == "V1.6"


def test_render_exposition_format():
    s = exporter.Sample()
    s.add("kp9000_up", "gauge", "Switch web UI scrape succeeded", {"switch": "192.168.0.3"}, 1)
    out = s.render()
    assert "# TYPE kp9000_up gauge" in out
    assert 'kp9000_up{switch="192.168.0.3"} 1' in out
