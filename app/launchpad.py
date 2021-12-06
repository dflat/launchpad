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

class SysexMarquee(fonts.Marquee):
    SHADES = [4,5,6,7,0]
    def print_frame(self, frame):
        frame = [self.SHADES[i] for i in frame]
        self.painter.send_sysex(Page(frame))

class State:
    QUICK_SLOTS = [19,29,39,49,59,69,79,89]
    CONTROL_KEYS = list(range(101,109)) + list(range(10,81,10))
    CTRL = {'marquee':101, 'ddr': 102, 'ddr_auto': 103, 'load':106,
            'save':107, 'palette':108, 'brush_tool':10 ,'bucket_tool':20} 
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

class State_ChooseDDRSong:
    # TODO: select from a gui menu the song to be played
    def to_ddr(self):
        pass

class Song:
    SONGS = { }
    def __init__(self, name, bpm, sample_dir='voice_plucks', time_signature=(4,4)):
        self.name = name
        self.bpm = bpm
        self.sample_dir = sample_dir
        self.time_signature = time_signature 
        self._register()
    def _register(self):
        Song.SONGS[self.name] = self

    @classmethod
    def get_metadata(cls, name):
        return cls.SONGS[name]

Song('ddr_test', bpm=120, sample_dir='voice_plucks')
Song('fallen_down', bpm=110, sample_dir='voice_plucks', time_signature=(3,4))
Song('mario_theme', bpm=90, sample_dir='dumb')

class State_Canvas(State):
    """
    A rule is (next_state, transition_action, [arguments to transition_action])
    """
    rule = {State.CTRL['save']: ('State_SavePending', 'no_action', ()),
            State.CTRL['load']: ('State_LoadPending', 'no_action', ()),
            State.CTRL['palette']: ('State_Palette', 'to_palette', ()),
            State.CTRL['marquee']: ('State_Canvas', 'marquee', ()),
            State.CTRL['ddr']: ('State_DDR', 'to_ddr', ()), # TODO: fix state
            State.CTRL['ddr_auto']: ('State_DDR', 'to_ddr_auto', ()), 
            State.CTRL['brush_tool']: ('State_Canvas', 'switch_tool', ('brush',)),
            State.CTRL['bucket_tool']: ('State_Canvas', 'switch_tool', ('bucket',)),
            }
    tools = {'brush':'paint', 'bucket':'flood_fill'}
    current_tool = 'brush'

    def action(self, msg):
        self.song = Song.get_metadata('fallen_down') # TODO: just send this object in
        if self.is_pad_press(msg):
            paint_func = getattr(self.painter, self.tools[self.current_tool])
            paint_func()
        elif self.is_cc_press(msg):
            if msg.control in self.CONTROL_KEYS:
                newstate, transition, args = self.rule.get(msg.control,
                                                ('State_Canvas', 'no_action', ()))
                transition_func = getattr(self, transition)
                transition_func(*args)
                self.new_state(eval(newstate))
    def to_palette(self):
        self.painter.switch_to_palette(0)
    def marquee(self):
        self.painter.scroll_text('See you in hell?', fps=20)
    def switch_tool(self, tool):
        self.current_tool = tool
    def to_ddr(self):
        self.painter.play_ddr_minigame(self.song, rate=1, autoplay=False)
    def to_ddr_auto(self):
        self.painter.play_ddr_minigame(self.song, rate=1, autoplay=True)
    def no_action(self):
        pass


class Page:
    def __init__(self,colors, quick_id = None):
        self.colors = colors
        self.id = uuid.uuid1()
        self.quick_id = quick_id

    def edit(self, index, color):
        self.colors[index] = color

    def get_color(self, index):
        return self.colors[index]

class Gallery:
    DATA_FILEPATH = os.path.join(config.ASSETS_PATH, 'storage',
                                                    'gallery_items.pickle')
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
    SAMPLE_ROOT = os.path.join(config.ASSETS_PATH, 'samples')
    SAMPLE_PACKS = { }

    def __init__(self, sample_dir):
        pygame.mixer.init()
        pygame.mixer.set_num_channels(32)
        self.loaded_packs = { }
        self.load_samples(sample_dir)
        self.input_q = queue.Queue()

    def load_backing_track(self, fname='mario_theme'):
        pygame.mixer.music.load(os.path.join(config.ASSETS_PATH,
                                'music', fname + '.mp3'))

    def load_samples(self, sample_dir):
        """
        Load samples from disk into memory.
        """
        paths = os.scandir(os.path.join(self.SAMPLE_ROOT, sample_dir))
        self.MISS_SOUND = pygame.mixer.Sound(os.path.join(self.SAMPLE_ROOT, 'boo.wav'))
        sample_pack = { }
        for path in paths:
            note = int(path.name.split('.')[0])
            sound = pygame.mixer.Sound(path.path)
            sample_pack[note] = sound
        self.remap(list(range(64)))  # todo: maybe do a better mapping here
        self.loaded_packs[sample_dir] = sample_pack
        self.current_sample_pack = sample_dir

    def switch_sample_pack(self, sample_dir):
        """
        Switch Sampler to an already loaded sample pack.
        """
        sample_pack = self.loaded_packs.get(sample_dir)
        if sample_pack:
            self.current_sample_pack = sample_pack
        else:
            raise RuntimeError(f'Tried to switch to an unloaded sample pack:{sample_dir}')

    def play_backing_track(self):
        pygame.mixer.music.play()

    def stop_backing_track(self):
        try:
            pygame.mixer.music.fadeout(500)
        except pygame.error:
            pass

    def play_midi_note(self, note):
        sample_pack = self.loaded_packs[self.current_sample_pack]
        sound = sample_pack.get(note, self.MISS_SOUND)
        if sound:
            sound.play()

    def play_note(self, pad_index):
        t = time.time()
        self.input_q.put({'type':'hit', 'pad_index': pad_index,
                            'time': t})

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


    def play_ddr_minigame(self, song:Song, rate=1, autoplay=False):
        self.play_track = ddr.PlayTrack(song.name + '.mid', bpm=song.bpm,
                                        time_signature=song.time_signature, painter=self)
        self.sampler.load_backing_track(song.name)
        if song.sample_dir:
            self.sampler.load_samples(song.sample_dir)
        t = threading.Thread(target=self.play_track.play, args=(rate, autoplay))
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
        self._paint(pad_index, self.current_color)

    def _paint(self, pad_index, color):
        self._edit_canvas(pad_index, color)
        out_midi_note = self.padmap[pad_index]
        out_msg = mido.Message('note_on', note=out_midi_note,
                                velocity=color)
        self.send_note(out_msg)

    def _edit_canvas(self, pad_index, color):
        self.canvas.edit(pad_index, color)

    def flood_fill(self):
        pad_index = self.rev_padmap[self.msg.note]
        cover_color = self.canvas.get_color(pad_index)
        if self.current_color == cover_color:
            return
        self._flood_fill(pad_index, cover_color, visited=set())
        self.switch_to_current_page()

    def _flood_fill(self, pad_index, cover_color, visited):
        self._edit_canvas(pad_index, self.current_color)
        row, col = divmod(pad_index, 8)
        neighbors = set([(row-1, col), (row+1, col), (row, col-1), (row, col+1)])
        for r, c in neighbors - visited:
            if 0 <= r < 8 and 0 <= c < 8:
                visited.add((r,c))
                neighbor_index = r*8 + c
                neighbor_color = self.canvas.get_color(neighbor_index)
                if neighbor_color != cover_color:
                    continue
                self._flood_fill(neighbor_index, cover_color, visited)

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

