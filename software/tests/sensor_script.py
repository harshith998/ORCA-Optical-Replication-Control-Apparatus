import requests
import time
import json
from datetime import datetime

BASE_URL = "https://nitrogen-fixation-light-intensity.vercel.app/"

SENSOR_READ_INTERVAL = 5  # Send sensor data every 5 seconds for real-time updates
LED_CHECK_INTERVAL = 2    # Check for LED control changes every 2 seconds

class RaspberryPiController:
    def __init__(self, base_url):
        self.base_url = base_url
        self.last_led_settings = None
        
    def read_sensor_data(self):
    
        # TODO: Replace with actual sensor reading code
        actual_intensity = sensor_reading_code()
        
        return {
            "actual_intensity": actual_intensity,
            "expected_intensity": 1000.0,  # calculated expected value
            "temperature": 22.5,           # from temperature sensor (can we use GPS module for this??)
            "humidity": 45.0,              # from humidity sensor (can we use GPS module for this??)
            "latitude": 37.7749,           # from GPS module
            "longitude": -122.4194         # from GPS module
        }
    
    def send_sensor_reading(self, data):
        """Send light sensor reading to the web app"""
        url = f"{self.base_url}/api/sensor"
        
        try:
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()
            result = response.json()
            print(f"✓ [{datetime.now().strftime('%H:%M:%S')}] Sensor data sent: {data['actual_intensity']:.2f} lux")
            return result
        except requests.exceptions.RequestException as e:
            print(f"✗ [{datetime.now().strftime('%H:%M:%S')}] Error sending sensor data: {e}")
            return None
    
    def get_led_settings(self):
        """Fetch current LED control settings from the web app"""
        url = f"{self.base_url}/api/led/status"
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            result = response.json()
            return result.get('status')
        except requests.exceptions.RequestException as e:
            print(f"✗ [{datetime.now().strftime('%H:%M:%S')}] Error fetching LED settings: {e}")
            return None
    
    def apply_led_settings(self, settings):

        if not settings:
            return
        
        # Check if settings have changed
        if self.last_led_settings == settings:
            return  # No changes, skip
        
        print(f"\n{'='*60}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] NEW LED SETTINGS RECEIVED")
        print(f"{'='*60}")
        print(f"  Power:       {'ON' if settings.get('led_status') else 'OFF'}")
        print(f"  Mode:        {settings.get('control_mode', 'N/A').upper()}")
        
        if settings.get('control_mode') == 'manual':
            print(f"  Brightness:  {settings.get('brightness_level', 0)}%")
            print(f"  Color Temp:  {settings.get('color_temperature', 0)}K")
            
            # TODO: SEND DATA TO LED CONTROL MODULE??? (replace name later)
            led_controller_code.set_power(settings['led_status'])
            led_controller_code.set_brightness(settings['brightness_level'])
            led_controller_code.set_color_temperature(settings['color_temperature'])
            
        elif settings.get('control_mode') == 'auto':
            print(f"  Data Source: {settings.get('data_source', 'N/A')}")
            # In auto mode, the Pi should adjust LEDs based on sensor/GPS data
        
        print(f"{'='*60}\n")
        
        self.last_led_settings = settings
    
    def run(self):
        print("="*60)
        print("Raspberry Pi IoT Controller Started")
        print("="*60)
        print(f"Base URL: {self.base_url}")
        print(f"Sensor interval: {SENSOR_READ_INTERVAL}s")
        print(f"LED check interval: {LED_CHECK_INTERVAL}s")
        print("="*60)
        print("\nPress Ctrl+C to stop\n")
        
        last_sensor_time = 0
        last_led_check_time = 0
        
        try:
            while True:
                current_time = time.time()
                
                # Send sensor data at specified interval
                if current_time - last_sensor_time >= SENSOR_READ_INTERVAL:
                    sensor_data = self.read_sensor_data()
                    self.send_sensor_reading(sensor_data)
                    last_sensor_time = current_time
                
                # Check for LED control changes at specified interval
                if current_time - last_led_check_time >= LED_CHECK_INTERVAL:
                    led_settings = self.get_led_settings()
                    if led_settings:
                        self.apply_led_settings(led_settings)
                    last_led_check_time = current_time
                
                # Small sleep to prevent CPU overuse
                time.sleep(0.5)
                
        except KeyboardInterrupt:
            print("\n\nShutting down gracefully...")
            print("Raspberry Pi IoT Controller stopped.")

if __name__ == "__main__":
    # Initialize controller with your web app URL
    controller = RaspberryPiController(BASE_URL)
    
    # Start the main loop
    controller.run()


def led_controller_code():
    pass

def sensor_reading_code():
    pass