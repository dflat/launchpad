import mido
from PIL import Image
import time
import random
import math
import colorsys
import os

ROOT_DIR = 'LaunchpadSprite'
SPRITESHEET = os.path.join(ROOT_DIR, 'sprites.png')

def load_sheet(path=SPRITESHEET):
    return Image.open(path)

def build_padmap(start=81, stop=1, step=-10, cols=8):
    padmap = []
    for start in range(start, stop, step):
        for offset in range(cols):
            padmap.append(start + offset)
    return padmap

rev_padmap = {x:i for i,x in enumerate(build_padmap())} 

def get_xy(i, rows=8, cols=8):
    x = i % cols
    y = i // cols 
    return (x,y)

def get_selected_pad_xy(msg):
    index = rev_padmap.get(msg.note)
    return get_xy(index)

def get_wave(t):
    colors = []
    for i in range(8):
        for j in range(8):
            v, u = get_selected_pad_xy()
            t = t/(60*8) # pulse speed
            x = j
            y = i
            s = math.cos(t)
            q = .2 + .05*s #radius swell
            z = ((x - u)**2 + (y - v)**2)**(q)
            z = rescale(z,mn=0,mx=(98)**(q),a=0,b=1)
            hue,lum,sat = 30/360, 1-z, .6 + .05*s
            r,g,b = colorsys.hls_to_rgb(hue,lum,sat)
            colors.append([x*255.0 for x in [r,g,b]])
    return colors

MIDI_OUT = mido.get_output_names()[1] # launchpad midi port
PORT = mido.open_output(MIDI_OUT)
SPRITES = load_sheet()
sprite_rows = 10
sprite_cols = 10
PADMAP = build_padmap()

def rescale(x, mn=0, mx=255, a=0, b=127):
    r = a + ((x - mn)*(b - a)) / (mx - mn)
    return int(r)

def get_wave():
    colors = []
    for i in range(8):
        for j in range(8):
            t = ui.t/10
            x = j/7
            y = i/7
            z = math.cos(x + t) * math.sin(y + t)
            z = rescale(z, mn=-1,mx=1,a=0,b=255)
            colors.append([z,100,100])
    return colors

def slideshow(delay=5):
    while True:
        x = random.randint(0, sprite_cols - 1)
        y = random.randint(0, sprite_rows - 1)
        display_sprite(x,y,SPRITES,PORT)
        time.sleep(delay)

def display_sprite(x, y, im=SPRITES, port=PORT):
    print(x,y)
    assert(x < sprite_cols and y < sprite_rows)
    pixels = get_sprite_pixels(im, x, y)
    msg = build_sysex_rgb(pixels, PADMAP)
    #print(msg.hex())
    port.send(msg)

def get_sprite(im, x, y, size=48, pad=24, ext='png', save=True):
   # left, upper, right, lower 
   left = x*(size + pad)
   upper = y*(size + pad)
   right = left + size
   lower = upper + size
   box = [int(i) for i in (left,upper,right,lower)]
   cropped = im.crop(box)
   if save:
       cropped.save(f's{x}_{y}.{ext}') 
   return cropped

def get_sprite_pixels(im, x, y):
    im = get_sprite(im,x,y,save=False)
    im8x8 = im.resize((8,8), Image.BOX)
    return list(im8x8.getdata())

def build_sysex_rgb(pixels, padmap, smallbytes=True):
    """ 
    Remaps pixels to 0-127 and builds up a sysex msg for an image
    """
    assert(len(pixels) == 64)
    bytes = [0, 32, 41, 2, 14, 3] #sysex RGB preamble
    type = 3 # RGB
    for i in range(64):
        spec = [type, padmap[i], *map(rescale, pixels[i])] 
        bytes.extend(spec)
    return mido.Message('sysex', data=bytes) 

def build_rgb(pixels): # incomplete WIP
    assert(len(pixels) == 64)
    for i in range(64):
        pixels[i] 
