#!/usr/bin/env python3
import time
import math
import smbus
import board
import busio
import adafruit_ssd1306
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# 1. HARDWARE BUS INITIALIZATION
# ==========================================
i2c = busio.I2C(board.SCL, board.SDA)
bus = smbus.SMBus(1)
font = ImageFont.load_default()

COMPASS_ADDR = 0x0C

# Hard-Iron Offsets & North Declination Alignment
OFFSET_X = 224.5
OFFSET_Y = 245.5
SCALE_X = 1.0
SCALE_Y = 1.81
DECLINATION_OFFSET = -154.0

# ==========================================
# 2. DUAL OLED DISPLAYS ONLY (0x3C & 0x3D)
# ==========================================
time.sleep(0.05)
oled_left = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3C)
time.sleep(0.05)
oled_right = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)

smoothed_heading = 0.0

# ==========================================
# 3. TELEMETRY & SENSOR HELPERS
# ==========================================
def init_compass():
    try:
        # Reset control register
        bus.write_byte_data(COMPASS_ADDR, 0x0A, 0x00)
        time.sleep(0.02)
        bus.write_byte_data(COMPASS_ADDR, 0x0A, 0x01)
        time.sleep(0.02)
    except Exception:
        pass

def read_heading():
    global smoothed_heading
    try:
        # Trigger single-shot measurement
        bus.write_byte_data(COMPASS_ADDR, 0x0A, 0x01)
        time.sleep(0.025)

        # Read 9 bytes starting at register 0x01 (reading through 0x09 clears latch)
        d = bus.read_i2c_block_data(COMPASS_ADDR, 0x01, 9)
        raw_x = d[0] | (d[1] << 8)
        raw_y = d[2] | (d[3] << 8)

        if raw_x > 32767:
            raw_x -= 65536
        if raw_y > 32767:
            raw_y -= 65536

        # Filter out noisy empty or saturated frames
        if abs(raw_x) > 30000 or abs(raw_y) > 30000 or (raw_x == 0 and raw_y == 0):
            return smoothed_heading

        # Apply hard-iron offset and soft-iron scale correction
        cal_x = (raw_x - OFFSET_X) * SCALE_X
        cal_y = (raw_y - OFFSET_Y) * SCALE_Y

        raw_deg = math.degrees(math.atan2(cal_y, cal_x))
        if raw_deg < 0:
            raw_deg += 360

        # Apply directional alignment
        raw_deg = (raw_deg + DECLINATION_OFFSET) % 360

        # Circular EMA smoothing (0.35 factor)
        diff = (raw_deg - smoothed_heading + 180) % 360 - 180
        smoothed_heading = (smoothed_heading + 0.35 * diff) % 360
        return smoothed_heading

    except Exception:
        return smoothed_heading

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return f"{float(f.read()) / 1000.0:.1f}C"
    except Exception:
        return "N/A"

def get_cardinal(deg):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((deg + 22.5) / 45.0) % 8]

# ==========================================
# 4. MAIN TELEMETRY LOOP
# ==========================================
init_compass()
print("[*] Dual-OLED HUD Daemon Online (Locked to 0x0C).")

try:
    while True:
        heading = read_heading()
        cardinal = get_cardinal(heading)
        temp = get_cpu_temp()

        # Terminal debug line
        print(f"Heading: {heading:05.1f}° {cardinal} | CPU: {temp}   ", end="\r")

        # --- Left OLED (0x3C): System Status ---
        img_l = Image.new("1", (128, 64), 0)
        draw_l = ImageDraw.Draw(img_l)
        draw_l.rectangle((0, 0, 127, 63), outline=255, fill=0)
        draw_l.text((8, 6),  "HELLJUMPER HUD", font=font, fill=255)
        draw_l.line((8, 18, 120, 18), fill=255)
        draw_l.text((8, 22), "IP: 192.168.0.113", font=font, fill=255)
        draw_l.text((8, 36), f"CPU TEMP: {temp}", font=font, fill=255)
        draw_l.text((8, 50), "RTSP: 8554 (LIVE)", font=font, fill=255)

        # --- Right OLED (0x3D): Bearing & Compass Tape ---
        img_r = Image.new("1", (128, 64), 0)
        draw_r = ImageDraw.Draw(img_r)
        draw_r.rectangle((0, 0, 127, 63), outline=255, fill=0)
        draw_r.text((8, 6),  f"BEARING: {heading:05.1f}*", font=font, fill=255)
        draw_r.line((8, 18, 120, 18), fill=255)
        draw_r.text((8, 24), f"HEADING: {cardinal} [0x0C]", font=font, fill=255)

        draw_r.rectangle((10, 42, 117, 54), outline=255, fill=0)
        tick_x = 14 + int((heading / 360.0) * 98)
        draw_r.line((tick_x, 42, tick_x, 54), fill=255, width=2)

        # Update displays with brief stagger to prevent I2C bus collision
        try:
            oled_left.image(img_l)
            oled_left.show()
        except Exception:
            pass

        time.sleep(0.01)

        try:
            oled_right.image(img_r)
            oled_right.show()
        except Exception:
            pass

        time.sleep(0.04)

except KeyboardInterrupt:
    print("\n[+] Telemetry daemon terminated.")
