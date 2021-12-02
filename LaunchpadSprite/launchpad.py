import mido
import re
import threading
import queue
import pickle
import uuid
import copy
import pygame
import os
import time
from . import fonts
from . import ddr
from . import config


###------------ helper functions ------------###
def open_output():
    output_names = mido.get_output_names()
    for name in output_names:
        if re.match(r"launchpad.*midi", name.lower()):
            break
    else:
        name = output_names[1]
    return mido.open_output(name)

def open_input():
    input_names = mido.get_input_names()
    for name in input_names:
        if re.match(r"launchpad.*midi", name.lower()):
            break
    else:
        name = input_names[0]
    return mido.open_input(name)

def set_programmer_mode(output):
    mode = 1
    out_msg = mido.Message('sysex', data = [0, 32, 41, 2, 14, 14, mode])
    output.send(out_msg)
    output.close()

def build_padmap(start=81, stop=1, step=-10, cols=8):
    """
    Maps pad index (0-64) => Launchpad Developer Mode default midi notes
    """
    padmap = {}
    i = 0
    for start in range(start, stop, step):
        for offset in range(cols):
            padmap[i] = (start + offset)
            i += 1
    return padmap
###------------  end helper functions ------------###

# todo: build synthesizer w/gui ...use numpy
# todo: build multiport system to sync emulator
#    and physical midi controllers.

class SysexMarquee(fonts.Marquee):
    SHADES = [4,5,6,7,0]
    def print_frame(self, frame):
        frame = [self.SHADES[i] for i in frame]
        self.painter.send_sysex(Page(frame))

class State:
    QUICK_SLOTS = [19,29,39,49,59,69,79,89]
    CONTROL_KEYS = list(range(101,109))
    CTRL = {'marquee':101, 'ddr': 102, 'ddr_auto': 103, 'load':106,
            'save':107, 'palette':108} 
    def __init__(self, painter):
        self.painter = painter      # shortcut to controller objects (painter/sampler)
        self.sampler = painter.sampler
        self.new_state(State_Canvas)
    def new_state(self, state):
        self.__class__ = state
    def is_pad_press(self, msg):
        return msg.type == 'note_on' and msg.velocity != 0
    def is_cc_press(self, msg):
        return msg.is_cc() and msg.value != 0
    def action(self, msg):
        raise NotImplementedError()

class State_LoadPending(State):
    def action(self, msg):
        if not msg.is_cc() or msg.control not in self.QUICK_SLOTS:
            return
        if msg.control not in self.painter.gallery.pages:
            self.painter.gallery.pages[msg.control] = Page([0]*64)
        self.painter.load_canvas(id=msg.control)    
        self.new_state(State_Canvas)

class State_SavePending(State):
    def action(self, msg):
        if not msg.is_cc() or msg.control not in self.QUICK_SLOTS:
            return
        self.painter.save_canvas(id=msg.control)    
        self.new_state(State_Canvas)

class State_Palette(State):
    #PAGE = 1
    def action(self, msg):
        if self.is_cc_press(msg):
            if msg.control == State.CTRL['palette']:
                self.to_palette_alt()
        elif self.is_pad_press(msg):
            self.to_canvas()
    def to_palette_alt(self):
        self.painter.switch_to_palette(1)     
        self.new_state(State_PaletteAlt)
    def to_canvas(self):
        self.painter.select_color()
        self.painter.switch_to_canvas()
        self.new_state(State_Canvas)

class State_PaletteAlt(State):
    def action(self, msg):
        if self.is_cc_press(msg):
            if msg.control == State.CTRL['palette']:
                self.to_palette()
        elif self.is_pad_press(msg):
            self.to_canvas()
    def to_palette(self):
        self.painter.switch_to_palette(0)
        self.new_state(State_Palette)
    def to_canvas(self):
        self.painter.select_color()
        self.painter.switch_to_canvas()
        self.new_state(State_Canvas)

class State_DDR(State):
    def action(self, msg):
        if self.is_pad_press(msg):
            pad_index = self.painter.rev_padmap[msg.note] 
            self.sampler.play_note(pad_index)
        elif self.is_cc_press(msg):
            if msg.control in self.CONTROL_KEYS:
                if msg.control == State.CTRL['ddr']:
                    self.to_canvas()

    def to_canvas(self):
        self.painter.play_track.stop_listening()
        self.painter.switch_to_canvas() # todo: set up a thread remote for ddr feed
        self.new_state(State_Canvas)

class State_Canvas(State):
    rule = {State.CTRL['save']: ('State_SavePending', 'no_action'),
            State.CTRL['load']: ('State_LoadPending', 'no_action'),
            State.CTRL['palette']: ('State_Palette', 'to_palette'),
            State.CTRL['marquee']: ('State_Canvas', 'marquee'),
            State.CTRL['ddr']: ('State_DDR', 'to_ddr'), # TODO: fix state
            State.CTRL['ddr_auto']: ('State_DDR', 'to_ddr_auto'), # TODO: fix state
            }
    def action(self, msg):
        if self.is_pad_press(msg):
            self.painter.paint()
        elif self.is_cc_press(msg):
            if msg.control in self.CONTROL_KEYS:
                newstate, transition = self.rule.get(msg.control,
                                                ('State_Canvas', 'no_action'))
                transition_func = getattr(self, transition)
                transition_func()
                self.new_state(eval(newstate))
    def to_palette(self):
        self.painter.switch_to_palette(0)
    def marquee(self):
        self.painter.scroll_text('See you in hell?', fps=20)
    def to_ddr(self):
        self.painter.play_ddr_minigame('mario_theme.mid', rate=1, autoplay=False)
    def to_ddr_auto(self):
        self.painter.play_ddr_minigame('mario_theme.mid', rate=1, autoplay=True)
    def no_action(self):
        pass


class Page:
    def __init__(self,colors, quick_id = None):
        self.colors = colors
        self.id = uuid.uuid1()
        self.quick_id = quick_id

    def edit(self, index, color):
        self.colors[index] = color

class Gallery:
    DATA_FILEPATH = 'gallery_items.txt'
    def __init__(self):
        try:
            with open(self.DATA_FILEPATH, 'rb') as f:
                pages = pickle.load(f) 
        except FileNotFoundError:
            pages = {}
        self.pages = pages

    def save(self, page):
        self.pages[page.id] = page
        with open(self.DATA_FILEPATH, 'wb') as f: 
            pickle.dump(self.pages, f)

    def load(self, page_id):
        return self.pages[page_id]


PADMAP = build_padmap()
REV_PADMAP = {v:k for k,v  in PADMAP.items()}

class Sampler:
    PAD_TO_MIDI = { } # pad_index -> midi_note
    MIDI_TO_SAMPLE = { } # midi note -> audio file
    SAMPLE_ROOT = os.path.join(config.PROJECT_ROOT, 'assets/samples')

    def __init__(self, sample_dir):
        pygame.mixer.init()
        pygame.mixer.set_num_channels(32)
        self.load_samples(sample_dir)
        self.input_q = queue.Queue()

    def _load_backing_track(self, fname='mario.mp3'):
        pygame.mixer.music.load(os.path.join(config.PROJECT_ROOT,
                                'assets', 'music', fname))

    def load_samples(self, sample_dir):
        paths = os.scandir(os.path.join(self.SAMPLE_ROOT, sample_dir))
        self.MISS_SOUND = pygame.mixer.Sound(os.path.join(self.SAMPLE_ROOT, 'boo.wav'))
        for path in paths:
            note = int(path.name.split('.')[0])
            sound = pygame.mixer.Sound(path.path)
            self.MIDI_TO_SAMPLE[note] = sound
        self.remap(list(range(64)))  # todo: maybe do a better mapping here

    def play_backing_track(self):
        pygame.mixer.music.play()

    def stop_backing_track(self):
        pygame.mixer.music.fadeout(500)

    def play_midi_note(self, note):
        sound = self.MIDI_TO_SAMPLE.get(note, self.MISS_SOUND)
        if sound:
            sound.play()

    def play_note(self, pad_index):
        t = time.time()
        self.input_q.put({'type':'hit', 'pad_index': pad_index,
                            'time': t})
        #note = self.PAD_TO_MIDI[pad_index]
        #sound = self.MIDI_TO_SAMPLE.get(note, self.MISS_SOUND)
        #if sound:
        #    sound.play()

    def remap(self, notes):
        for i in range(len(notes)):
            self.PAD_TO_MIDI[i] = notes[i] 

class Painter:
    gallery = Gallery()
    def __init__(self):
        self._init_connections()
        self.padmap = PADMAP
        self.rev_padmap = REV_PADMAP
        self.msg = None
        self.listen_remote = threading.Event()
        self.current_color = 69
        self.current_page = Page([0]*64)
        self.canvas = Page([0]*64)
        self.palettes = [Page([i for i in range(64)]),
                        Page([i for i in range(64,128)])]
        self.sampler = Sampler('dumb')
        self.state = State(self)
        self.run()

    def _init_connections(self):
        set_programmer_mode(open_output())
        self.outport = open_output()
        self.port = open_input()
        
    def __del__(self):
        self.outport.close()
        self.port.close()

    def stop(self):
        self.listen_remote.set()

    def _send_msg(self, msg):
        self.outport.send(msg)

    def send_note(self, msg):
        self._send_msg(msg)

    def scroll_text(self, text, fps=20):
        callback = self.switch_to_canvas
        text = SysexMarquee(message=text, painter=self)
        t = threading.Thread(target=text.animate, args=(fps, callback))
        t.start()

    def as_page(self, colors):
        return Page(colors)

    def remap_sampler(self, notes):
        self.sampler.remap(notes)


    def play_ddr_minigame(self, midi_file_path, rate=1, autoplay=False):
        self.play_track = ddr.PlayTrack(midi_file_path, painter=self)
        t = threading.Thread(target=self.play_track.animate, args=(rate, autoplay))
        t.start()
        print('playing ddr minigame...')
        
    def send_sysex(self, page, mode = 0):
        """ 
        builds and sends a sysex msg for a page
        """
        assert(len(page.colors) == 64)
        bytes = [0, 32, 41, 2, 14, 3] #sysex RGB preamble
        for i in range(64):
            spec = [mode, self.padmap[i], page.colors[i]]
            bytes.extend(spec)
        self._send_msg(mido.Message('sysex', data=bytes))

    def fill_page(self, color):
        self.canvas = Page([color for i in range(64)])
        self.switch_to_canvas()

    def clear_page(self):
        self.fill_page(color = 0)

    def switch_to_palette(self, index):
        self.current_page = self.palettes[index]
        self.switch_to_current_page()

    def switch_to_canvas(self):
        self.current_page = self.canvas
        self.switch_to_current_page()

    def switch_to_current_page(self):
        self.send_sysex(self.current_page)

    def paint(self):
        pad_index = self.rev_padmap[self.msg.note]
        self.canvas.edit(pad_index, self.current_color)
        out_msg = mido.Message('note_on', note=self.msg.note,
                                velocity=self.current_color)
        self.send_note(out_msg)

    def select_color(self):
        pad_index = self.rev_padmap[self.msg.note]
        self.current_color = self.current_page.colors[pad_index]

    def save_canvas(self, id):
        page = copy.deepcopy(self.canvas)
        page.id = id
        self.gallery.save(page)

    def load_canvas(self, id):
        self.canvas = copy.deepcopy(self.gallery.load(page_id=id))
        self.current_page = self.canvas
        self.switch_to_current_page()

    def receive(self):
        return self.port.receive()

    def listen(self):
        while not self.listen_remote.is_set():
            self.msg = self.receive()
            if not self.msg:
                continue
            if self.msg.type == 'clock':
                continue
            self.state.action(self.msg)
        print('painter stopped listening.')
        self.listen_remote.clear()

    def run(self):
        listener = threading.Thread(target = self.listen, args = ())
        listener.start()
        self.switch_to_current_page()
        self.scroll_text(text='Welcome!', fps=25)

