import digitalio
import board
import subprocess
from PIL import Image, ImageDraw, ImageFont
from adafruit_rgb_display import ssd1351  
# tutorial:  https://learn.adafruit.com/adafruit-1-5-color-oled-breakout-board?view=all#ssd1351-based-displays-3042759-21

# Configuration for CS and DC pins (these are PiTFT defaults):
cs_pin = digitalio.DigitalInOut(board.CE0)
dc_pin = digitalio.DigitalInOut(board.D25)
reset_pin = digitalio.DigitalInOut(board.D24)
BAUDRATE = 16000000
spi = board.SPI()
disp = ssd1351.SSD1351(spi, rotation=0, cs=cs_pin,
     dc=dc_pin, rst=reset_pin, baudrate=BAUDRATE)

width  = disp.width 
height = disp.height

# Draw a black filled box to clear the image.
image = Image.new("RGB", (width, height))
# Get drawing object to draw on image.
draw = ImageDraw.Draw(image)
draw.rectangle((0, 0, width, height), outline=0, fill=(0, 0, 0))
disp.image(image)

def clearDisplay():
    width  = disp.width 
    height = disp.height

    # Draw a black filled box to clear the image.
    image = Image.new("RGB", (width, height))
    # Get drawing object to draw on image.
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, height), outline=0, fill=(0, 0, 0))
    disp.image(image)

def displayOLED(origImage, elapsedTime=0,powerButton=0, leftT=0, rightT=0, clearScreen=False,):
    # Create blank image for drawing.
    # Make sure to create image with mode 'RGB' for full color.
    width  = disp.width 
    height = disp.height
    

    if clearScreen:
        clearDisplay()

    # Scale the image to the smaller screen dimension
    image = Image.fromarray(origImage)
    
    image_ratio = image.width / image.height
    screen_ratio = width / height
    scaled_width = width
    scaled_height = image.height * width // image.width
    image = image.resize((scaled_width, scaled_height), Image.BICUBIC)
    
    # Crop and center the image
    x = scaled_width // 2 - width // 2
    y = 0 # Put the image at the top 
    image = image.crop((x, y, x + width, y + height))

    # Extra text overlays
    draw = ImageDraw.Draw(image)
    
    # CPU temp
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 12)
    cmd = "cat /sys/class/thermal/thermal_zone0/temp |  awk \'{printf \"%.1f C\", $(NF-0) / 1000}\'" # pylint: disable=line-too-long
    Temp = subprocess.check_output(cmd, shell=True).decode("utf-8")
    #draw.text((0, 111), Temp, font=font, fill="#000000", stroke_width=3, stroke_fill="#000000")  # Stroke around the text
    draw.text((0, 114), Temp, font=font, fill="#FFFFFF")
    
    # loop time
    elapsedTime = "{:.0f}ms".format(elapsedTime*1000)
    font2 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 12)
    #draw.text((80, 111), elapsedTime, font=font2, fill="#000000", stroke_width=3, stroke_fill="#000000")
    draw.text((80, 114), elapsedTime, font=font2, fill="#FFFFFF")
    
    # T-pose detected
    if leftT:
        draw.text((0, 98), "T-Pose!", font=font2, fill="#FFFFFF")
    if rightT:
        draw.text((70, 98), "T-Pose!", font=font2, fill="#FFFFFF")
        
    # Center line box
    draw.rectangle((63,0,65,25),fill=(55,55,255))
    
    # Red box if holding power button
    if(powerButton > 1):
        font3 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 15)
        draw.rectangle((0, 0, width, powerButton*12), fill=(255, 0, 0))
        draw.text((5, 20), "Shutting down", font=font3, fill="#000000")
        draw.text((20, 40), "in {:.1f}".format((10-powerButton)/2), font=font3, fill="#000000")
    
    # Display image.
    disp.image(image)