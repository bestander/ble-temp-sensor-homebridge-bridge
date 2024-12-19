import network
import socket
import time
import json
from machine import Pin
import bluetooth
from micropython import const
from config import *  # Import settings from config.py

# Add LED setup
led = Pin("LED", Pin.OUT)  # Built-in LED on Pico W

# BLE Scanner setup
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)

# Ruuvi tag settings
RUUVI_DATA_FORMAT = 5  # Ruuvi uses data format 5

# HTTP server settings
HTTP_PORT = 8000

# Add LED blink function
def blink_led():
    led.toggle()

class BLEScanner:
    def __init__(self):
        print("Initializing BLE Scanner...")
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self.ble_irq)
        self.latest_data = None
        self.data_received = False  # Add flag for new data
        print("BLE Scanner initialized and active")
        
    def ble_irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            addr = ':'.join(['%02x' % i for i in addr])
            if addr.lower() == RUUVI_MAC.lower():
                print(f"Found Ruuvi tag! Raw data: {adv_data.hex()}")
                self.parse_ruuvi_data(adv_data)
        elif event == _IRQ_SCAN_DONE:
            print("Scan complete")
                
    def parse_ruuvi_data(self, data):
        print(f"Parsing data: {data.hex()}")
        try:
            # Looking for Ruuvi manufacturer data
            i = 0
            while i < len(data):
                length = data[i]
                if i + 1 < len(data):
                    type_id = data[i + 1]
                    if type_id == 0xFF:  # Manufacturer Specific Data
                        mfg_data = data[i + 2:i + length + 1]
                        if mfg_data[0:2] == b'\x99\x04':  # Ruuvi manufacturer ID
                            print("Found Ruuvi manufacturer data")
                            if mfg_data[2] == RUUVI_DATA_FORMAT:
                                print("Found data format 5")
                                # Format 5 parsing
                                temp = int.from_bytes(mfg_data[3:5], 'big') * 0.005
                                # Convert to signed value if necessary
                                if temp > 32767:
                                    temp -= 65536
                                humidity = int.from_bytes(mfg_data[5:7], 'big') * 0.0025
                                pressure = int.from_bytes(mfg_data[7:9], 'big') + 50000
                                
                                self.latest_data = {
                                    'temperature': temp,
                                    'humidity': humidity,
                                    'pressure': pressure / 100
                                }
                                print(f"Parsed data: {self.latest_data}")
                                self.data_received = True  # Set flag when new data received
                                return
                i += length + 1
            print("No Ruuvi data found in packet")
        except Exception as e:
            print(f"Error parsing data: {e}")
    
    def start_scan(self):
        print("Starting BLE scan...")
        self.ble.gap_scan(10000, 30000, 30000)

def connect_wifi():
    print("Connecting to WiFi...")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    
    # Wait for connection
    max_wait = 10
    while max_wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1
        print('Waiting for connection...')
        time.sleep(1)
    
    if wlan.status() != 3:
        raise RuntimeError('Network connection failed')
    else:
        print('Connected')
        status = wlan.ifconfig()
        print('IP:', status[0])
        return status[0]

def start_webserver(ip, scanner):
    print("Starting web server...")
    addr = socket.getaddrinfo(ip, HTTP_PORT)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        s.bind(addr)
        s.listen(1)
        print(f'Listening on http://{ip}:{HTTP_PORT}')
        
        last_blink = time.ticks_ms()
        blink_interval = 1000  # Start with 1 second interval
        while True:
            try:
                # Adjust blink interval based on data state
                current_time = time.ticks_ms()
                if scanner.data_received:
                    blink_interval = 500  # Blink every 0.5 seconds when data received
                else:
                    blink_interval = 1000  # Normal 1 second blink

                if time.ticks_diff(current_time, last_blink) >= blink_interval:
                    blink_led()
                    last_blink = current_time

                # Check for socket data with timeout
                s.settimeout(0.1)  # 100ms timeout
                try:
                    cl, addr = s.accept()
                    print('Client connected from', addr)
                    request = cl.recv(1024).decode()
                    print(f"Received request: {request}")
                    
                    print("Starting new BLE scan")
                    scanner.start_scan()
                    time.sleep(1)  # Give some time for scanning
                    
                    if scanner.latest_data:
                        print(f"Sending data: {scanner.latest_data}")
                    else:
                        print("No data available from Ruuvi tag")
                    
                    response = {
                        'temperature': scanner.latest_data['temperature'] if scanner.latest_data else None,
                        'humidity': scanner.latest_data['humidity'] if scanner.latest_data else None,
                        'pressure': scanner.latest_data['pressure'] if scanner.latest_data else None
                    }
                    
                    response_json = json.dumps(response)
                    response_str = f'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(response_json)}\r\nAccess-Control-Allow-Origin: *\r\n\r\n{response_json}'
                    
                    print(f"Sending response: {response_str}")
                    cl.send(response_str.encode())
                    cl.close()
                    scanner.data_received = False  # Reset flag after handling request
                except OSError as e:
                    if e.args[0] == 11:  # EAGAIN error (timeout)
                        continue
                    raise e
                    
            except Exception as e:
                print('Error in connection handler:', e)
                try:
                    cl.close()
                except:
                    pass
    finally:
        s.close()
        print("Server socket closed")

def main():
    print("Starting main program...")
    try:
        scanner = BLEScanner()
        ip = connect_wifi()
        start_webserver(ip, scanner)
    except KeyboardInterrupt:
        print("Program terminated by user")
    except Exception as e:
        print(f"Error in main: {e}")
        raise e

if __name__ == '__main__':
    print("Program starting...")
    main()