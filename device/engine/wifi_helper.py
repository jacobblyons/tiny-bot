import wifi
import time


def scan(timeout_s=5):
    """Scan visible 2.4 GHz networks. Returns list of dicts sorted by RSSI desc."""
    nets = {}
    deadline = time.monotonic() + timeout_s
    for network in wifi.radio.start_scanning_networks():
        if time.monotonic() > deadline:
            break
        try:
            name = network.ssid
        except Exception:
            continue
        if not name:
            continue
        prev = nets.get(name)
        if prev is None or network.rssi > prev["rssi"]:
            nets[name] = {
                "ssid": name,
                "rssi": network.rssi,
                "secure": network.authmode and any(a for a in network.authmode),
            }
    wifi.radio.stop_scanning_networks()
    return sorted(nets.values(), key=lambda n: n["rssi"], reverse=True)


def is_connected():
    return wifi.radio.ipv4_address is not None


def connect(ssid, password, timeout_s=15):
    if is_connected():
        try:
            current = wifi.radio.ap_info.ssid if wifi.radio.ap_info else None
        except Exception:
            current = None
        if current == ssid:
            return True, "connected"
        wifi.radio.stop_station()
        time.sleep(0.2)
    try:
        wifi.radio.connect(ssid=ssid, password=password, timeout=timeout_s)
        return True, "connected"
    except ConnectionError as e:
        return False, str(e)
    except Exception as e:
        return False, "{}: {}".format(type(e).__name__, e)


def info():
    if not is_connected():
        return None
    return {
        "ssid": wifi.radio.ap_info.ssid if wifi.radio.ap_info else "",
        "ip": str(wifi.radio.ipv4_address),
        "rssi": wifi.radio.ap_info.rssi if wifi.radio.ap_info else 0,
    }


def disconnect():
    if is_connected():
        wifi.radio.stop_station()
