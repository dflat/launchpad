import sys
import time
import os
import colorsys
import math
import pygame
from pygame.locals import *
import numpy as np
import random
import pygame_menu
from LaunchpadSprite.spritesheet import get_sprite_pixels, SPRITES
from LaunchpadSprite import launchpad
import mido
import queue
import pickle 
import LaunchpadSprite.config as config

program_inbox = queue.Queue()
device_inbox = queue.Queue()


class VirtualOutport(mido.ports.BaseOutput):
    def __init__(self, *args, outbox=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.outbox = outbox
    def _send(self, msg):
        self.outbox.put(msg) 

class VirtualInport(mido.ports.BaseInput):
    def __init__(self, *args, inbox=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.inbox = inbox
    def _receive(self, block=True):
        try:
            return self.inbox.get(block=block) 
        except queue.Empty:
            return None

class VirtualPainter(launchpad.Painter):
    def _init_connections(self):
        self.outport = VirtualOutport(outbox=device_inbox)
        self.port = VirtualInport(inbox=program_inbox)

        #cls.outport = VirtualOutport(outbox=program_inbox)
        #cls.inport = VirtualInport(inbox=device_inbox)

class MultiPainter(launchpad.Painter):
    def __del__(self):
        for port in self.outports+self.inports:
            port.close()

    def _send_msg(self, msg):
        #self.outport_virtual.send(msg)
        for port in self.outports:
            port.send(msg)

    def receive(self):
        msg = self.inport_physical.receive(block=False)
        if not msg:
            msg = self.inport_virtual.receive(block=False)
        time.sleep(0.001)
        return msg

    def _init_connections(self):
        launchpad.set_programmer_mode(launchpad.open_output())
        self.outport_virtual = VirtualOutport(outbox=device_inbox)
        self.outport_physical = launchpad.open_output() 
        self.inport_virtual = VirtualInport(inbox=program_inbox)
        self.inport_physical = launchpad.open_input()
        self.inports = [self.inport_virtual, self.inport_physical]
        self.outports = [self.outport_virtual, self.outport_physical]
#        self.outport = mido.ports.MultiPort([outport_virtual, outport_physical])
#        self.port = mido.ports.MultiPort([inport_virtual, inport_physical])

#globals
boxes = []
ROWS = 8
COLS = 8
PAD = 20
GAP = 1
WHITE = (255,)*3
GREY = (110,)*3
RED = (255,0,0)
COLOR_BG = (70, 60, 80)
COLOR_PAD = (50,50,50)#(200,200,200)
COLOR_PAD_HOVER = GREY
COLOR_PAD_CLICKED = (255,220,140)
W, H = (840//1,840//1)

class UI:
    def __init__(self):
        self.clicked = False
        self.dragging = False
        self.t = 0
        self.frame = 0
    def update(self, dt):
        self.clicked = False
        self.t += dt
        self.frame += 1
ui = UI()

def rescale(x, mn=-1, mx=1, a=0, b=255):
    return a + ((x - mn)*(b - a))/(mx-mn)

def random_rgb():
    return tuple(random.randint(0,255) for i in range(3))

def load_color_palette():
    path = os.path.join(config.PROJECT_ROOT, 'palette_colors.pickle')
    with open(path, 'rb') as f:
        return pickle.load(f)

class Box(pygame.sprite.Sprite):
    color_palette = load_color_palette()
    current_color = GREY
    msg = None
    REFRESH_RATE = 4 #frames
    selected_x = 0
    selected_y = 0
    group = []
    ROWS = 8
    COLS = 8
    hovered = None
    mp = [[0 for j in range(COLS)] for i in range(ROWS)]
    bap = [1,1]
    saved_map = None
    PAD = 5
    GRID_SIZE = 640
    MARGIN = (W - GRID_SIZE + PAD)//2
    GRID_W = GRID_SIZE #- MARGIN*2
    GRID_H = GRID_SIZE #- MARGIN*2
    BOX_W = int((GRID_W - PAD*(COLS -1) ) / (COLS))
    BOX_H = BOX_W
    #tri = pygame.Surface((BOX_W, BOX_H), pygame.SRCALPHA)
    #pygame.draw.polygon(tri, (244,155,155), [(0,0),(10,0),(0,10)])

    def __init__(self, pos, index, scale_h=1, padXY=None, note=None):
        self.group.append(self)
        self.image = pygame.Surface((self.BOX_W, scale_h*self.BOX_H), pygame.SRCALPHA)
        #self._draw_poly()
        self.index = index
        self.rect = self.image.get_rect()
        self.rect.x = pos[0]
        self.rect.y = pos[1]
        self._color0 = COLOR_PAD
        self._color = self._color0
        self.painted = False
        self.painted_color = None
        self.image.fill(self.color)
        self.pos = pos
        self.pos0 = pos.copy()
        self.padXY = padXY
        self.t = 0
        self.note = note

    def _draw_poly(self):
        self.mask = pygame.mask.from_surface(self.image)

    @classmethod
    def update_pads(cls):
        for i in range(8):
            for j in range(8):
                box = cls.mp[i][j]
                
    @classmethod
    def display_image(cls, x, y):
        pixels = get_sprite_pixels(SPRITES, x, y)
        cls.load_page(pixels)
    
    @classmethod
    def random_image(cls):
        colors = [(random.randint(0,255), random.randint(0,255), random.randint(0,255))
                    for i in range(64)]
        cls.load_page(colors)

    @classmethod
    def load_page(cls, values):
        for i in range(cls.ROWS):
            for j in range(cls.COLS):
                box = Box.mp[i][j]
                box.painted = True
                box.painted_color = values[i*cls.COLS + j]

    @classmethod
    def build_map(cls):
        for i in range(ROWS):
            for j in range(COLS):
                y = cls.MARGIN + i*(cls.BOX_W + cls.PAD)
                x = cls.MARGIN + j*(cls.BOX_H + cls.PAD)
                note = launchpad.PADMAP[i*ROWS + j]
                box = Box(np.array([x,y]), index=(j,i), 
                        padXY = np.array([j,i]), note=note)
                cls.mp[i][j] = box

    @classmethod
    def set_color(cls, note, color):
        index = launchpad.REV_PADMAP[note]
        color = cls.color_palette[color]
#        color = cls.color_palette[index] #TODO testing this delete...
        row, col = divmod(index,ROWS)
        Box.mp[row][col].painted_color = color
        cls.current_color = color

    @classmethod
    def parse_sysex(cls, msg):
        colors = msg.data[6:][2::3]
        colors = [cls.color_palette[i] for i in colors]
        cls.load_page(colors)

    @classmethod
    def save_map(cls):
        cls.saved_map = cls.mp

    @classmethod
    def load_map(cls, mp=None):
        cls.mp = cls.saved_map

    @property
    def color(self):
        return self._color
    @color.setter
    def color(self, val):
        self._color = val
        self.image.fill(self._color)

    @classmethod
    def _init_ports(cls):
        """ Emulated launchpad ports """
        cls.outport = VirtualOutport(outbox=program_inbox)
        cls.inport = VirtualInport(inbox=device_inbox)

    def is_hovering(self):
        mouse = pygame.mouse.get_pos()
        if self.rect.collidepoint(mouse):
            return True
        else:
            return False
        
    def crosshair(self):
        j,i = self.index
        for x, y in [(0,0), (-1,0), (1,0), (0,-1), (0,1)]:
            u = max(0, min(7, i+x))
            v = max(0, min(7, j+y))
            box = Box.mp[u][v]
            box.color = COLOR_PAD_HOVER
    
    def small_crosshair(self):
        j,i = self.index
        #Box.mp[i][j].color = Box.current_color
        hovered_box = Box.mp[i][j]
        hovered_box.color = tuple(min(255,int(i*1.2)) for i in hovered_box.color)

    def hover(self):
        Box.hovered = self
        x, y = self.padXY
        Box.selected_x = x
        Box.selected_y = y
        #Box.color = (0,0,0)

    def click(self):
        x, y = self.padXY
        Box.selected_x = x
        Box.selected_y = y
        self.send_msg()

    def drag(self):
        self.send_msg()

    def send_msg(self):
        msg = mido.Message('note_on', note=self.note)
        self.outport.send(msg)

    @classmethod
    def receive_msg(cls):
        cls.msg = cls.inport.receive(block=False)

    @classmethod
    def ping_device(cls):
        msg = mido.Message('note_off', note=100)
        cls.outport.send(msg)

    def apply_color(self):
        if self.painted:
            self.color = self.painted_color
        else:
            self.color = self._color0

    def toggle_color(self):
        if self.painted:
            self.color = self._color0
            self.painted = False
        else:
            self.painted = True
            #self.painted_color = COLOR_PAD_CLICKED

    def update(self, dt):
        self.apply_color()
        if self.is_hovering():
            #self.color = COLOR_PAD_HOVER
            self.hover()
            if ui.clicked:
                self.click()
            if ui.dragging:
                pass
                #self.drag()
        self.t += dt

    @classmethod
    def animate(cls):
        if ui.frame % cls.REFRESH_RATE == 0: 
            cls.get_wave()

    @classmethod
    def get_wave(cls):
        colors = []
        t = ui.t/(60*8) # pulse speed
        s = math.cos(t)
        q = .2 + .05*s  # radius swell
        pos_x = cls.selected_x
        pos_y = cls.selected_y
        for y in range(8):
            for x in range(8):
                z = ((x - pos_x)**2 + (y - pos_y)**2)**(q)
                z = rescale(z,mn=0,mx=(98)**(q),a=0,b=1)
                hue,lum,sat = 30/360, 1-z, .6 + .05*s
                r,g,b = colorsys.hls_to_rgb(hue,lum,sat)
                colors.append([x*255.0 for x in [r,g,b]])
        cls.load_page(colors)

    def draw(self, screen):
        screen.blit(self.image, self.pos)

class CCBox(Box):
    ACTIONS = { 101: 'scroll_text', 102: 'save', 103: 'clear', 104: 'palette',
                105: 'load'}
    LABELS = {101: 'scroll', 106: 'load', 107:'save', 108:'colors'}

    def __init__(self, *args, cc=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc = cc
        self.hover_color = (200,200,200)
        self.font_color = (0,0,0)
        self._make_label()

    def _make_label(self):
        text = CCBox.LABELS.get(self.cc, 'none')
        self.label = game.font.render(text, 1, self.font_color)
        w, h  = self.label.get_width(), self.label.get_height()
        xoffset = (self.image.get_width() - w) // 2
        yoffset = (self.image.get_height() - h) // 2
        self.label_offset = (xoffset, yoffset)
        
        
    @classmethod
    def build_cc(cls):
        cls.CONTROLS = []
        cls.SUB_CONTROLS = []
        cls.QUICK_ACCESS = []
        cls.LEFT_PANEL = []
        cls.TOP_PANEL = []
        for j in range(COLS):
            # build bottom control row
            y = cls.MARGIN + cls.GRID_SIZE + cls.PAD
            x = cls.MARGIN + j*(cls.BOX_H + cls.PAD)
            box = CCBox(np.array([x,y]), cc=101+j, index=(8,j),
                        scale_h=0.5, padXY=np.array([8,j]))
            cls.CONTROLS.append(box)
            # build sub-control row
            y += cls.BOX_H//2 + cls.PAD
            box = CCBox(np.array([x,y]), cc=1+j, index=(9,j),
                        scale_h=0.5, padXY=np.array([9,j]))
            cls.SUB_CONTROLS.append(box)
            # build top panel
            y = cls.MARGIN - cls.PAD*2 - cls.BOX_H
            box = CCBox(np.array([x,y]), cc=91+j, index=(-1,j),
                        padXY=np.array([-1,j]))
            cls.TOP_PANEL.append(box)

        for i in range(ROWS):
            # build quick access column
            y = cls.MARGIN + i*(cls.BOX_H + cls.PAD)
            x = cls.MARGIN + cls.GRID_SIZE + cls.PAD
            box = CCBox(np.array([x,y]), cc=89-10*i, index=(i,8),
                        padXY=np.array([i,8]))
            cls.QUICK_ACCESS.append(box)
            # build left panel column
            x = cls.MARGIN - cls.BOX_W - cls.PAD*2
            box = CCBox(np.array([x,y]), cc=80-10*i, index=(i,-1),
                        padXY=np.array([i,-1]))
            cls.LEFT_PANEL.append(box)

    def send_msg(self):
        msg = mido.Message('control_change', control=self.cc, value=64)
        self.outport.send(msg)

    def hover(self):
        self.color = self.hover_color
        self.image.blit(self.label, self.label_offset)

    def click(self):
        self.send_msg()
        #self.run_action()

    def drag(self):
        pass

    def scroll_text(self):
        # dont do this here, or any actions, instead use the state machine
        # and input processing pipeline in launchpad.py... TODO
        game.painter.scroll_text("see you in hell?", fps=20)

    def save(self):
        Box.save_map()

    def load(self):
        Box.load_map()

    def clear(self):
        #Box.load_page([WHITE for i in range(64)])
        Box.random_image()

    def run_action(self):
        try:
            action = getattr(self, CCBox.ACTIONS.get(self.cc, ''))
        except AttributeError:
            action = None #lambda obj: None
        if action:
            action()
        else:
            im_id = self.cc - 100
            self.__class__.display_image(im_id, im_id)

def update(dt):
    ui.update(dt)

    for event in pygame.event.get():
        if event.type == QUIT:
          pygame.quit() # Opposite of pygame.init
          game.painter.stop()
          Box.ping_device()
          print('bye.')
          sys.exit() # Not including this line crashes the script on Windows. Possibly
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            #ui.clicked = True
            ui.dragging = True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            ui.clicked = True
            ui.dragging = False

    #Box.animate() 

    Box.receive_msg()
    msg = Box.msg
    if msg:
        if msg.type == 'note_on':
            Box.set_color(msg.note, msg.velocity)
        elif msg.type == 'sysex':
            Box.parse_sysex(msg)

    for box in Box.group:
        box.update(dt)

    if Box.hovered and True:
        Box.hovered.small_crosshair()

    if ui.clicked:
        pass

def draw(screen):
  """
  Draw things to the window. Called once per frame.
  """
  screen.fill(COLOR_BG) # Fill the screen with black.
  
  #Box.group.draw() 
  
  for box in Box.group:
      box.draw(screen)
  pygame.display.flip()
 
class Game:
    def __init__(self, w, h):
        pygame.init()
        pygame.display.set_caption("Launchpad Pro Emulator")
        pygame.mouse.set_cursor(*pygame.cursors.broken_x)
        self.font = pygame.font.SysFont(pygame.font.get_default_font(), 24)
        self.w = w
        self.h = h
        self.fps = 60.0
        self.fps_clock = pygame.time.Clock()
        self.screen = pygame.display.set_mode((w,h))
        self.painter = MultiPainter() 

    def run(self):
        dt = 1/self.fps # dt is the time since last frame.
        Box._init_ports()
        Box.build_map()
        CCBox.build_cc()
        while True:
            update(dt) 
            draw(self.screen)
            dt = self.fps_clock.tick(self.fps)

game = Game(W, H)
game.run()

