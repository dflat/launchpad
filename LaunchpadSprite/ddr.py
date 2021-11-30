import random
import mido
from copy import deepcopy
import os
import time
from . import config

MIDI_DIR = 'assets/midi'
MIDI_DIR_PATH = os.path.join(config.PROJECT_ROOT, MIDI_DIR)

def build_play_track(segments, note_set, cols):
    # todo: make playtrack entries into objects instead of
    #      plain ints, to store extra metadata (e.g is_triplet, color)
    def build_display_row(track_row):
        display_row = [-1]*8 # fix a blank color e.g. -1 
        n = len(track_row)
        start = (8-n)//2
        display_row[start:start+n] = track_row 
        return display_row
    def build_note_map(note_set):
        note_map = { }
        for i, note in enumerate(sorted(note_set)):
            note_map[note] = i % cols
        return note_map
    note_map = build_note_map(note_set)
    track = []
    for _ in range(8):        # intro padding
        track.extend(build_display_row([0]*cols))
    for segment in segments:
        track_row = [0]*cols
        for i, msg in enumerate(segment):
            index = note_map[msg.note] 
            got = track_row[index]
            if got == 0:         # first (or only) note in chord
                track_row[index] = msg.note
            else:                # handle chord placement
                index = index + random.randint(1, cols-1)
                track_row[index % cols] = msg.note
        track_row = build_display_row(track_row)
        track.extend(track_row)
    for _ in range(8):        # outro padding
        track.extend(build_display_row([0]*cols))
    return track

def playback(segs, port, seg_secs=(40/480)*(60/120)):
    for seg in segs:
        for msg in seg:
            port.send(msg)
            time.sleep(.001)
        time.sleep(seg_secs)
        for msg in seg:
            port.send(msg.copy(velocity=0))

def get_window(track, offset, cols=8, rows=8):
    return track[offset*cols:offset*cols+(cols*rows)]

def flip_frame_for_display(frame):
    flipped = []
    for i in reversed(range(8)):
        row = frame[i*8:(i+1)*8]
        flipped.extend(row)
    return flipped

class PlayTrack:
    FRAME_RECOLOR_MAP = {-1: 3, -2: 0,  0: 8, 1: 32, 2: 12, 3: 44,
                            4: 4, 5: 24, 6:47, 7:56 }
    INTRO_PAD_FRAMES = 8
    OUTRO_PAD_FRAMES = 8
    def __init__(self, midi_path, painter, bpm=120, ticks_per_beat=480, segment_ticks=40):
        self.midi_path = os.path.join(MIDI_DIR_PATH, midi_path)
        self.painter = painter
        self.bpm = bpm
        self.ticks_per_beat = ticks_per_beat
        self.seconds_per_beat = 60/bpm
        self.bpm_ticks = int(self.seconds_per_beat*10**5)
        self.segment_ticks = segment_ticks
        self._prepare_play_track()

    @property
    def seconds_per_segment(self):
        return (self.segment_ticks/self.ticks_per_beat)*(60/self.bpm)

    def _ticks_to_seconds(self, ticks):
        return (ticks/self.ticks_per_beat)*(60/self.bpm)

    def _recolor_frames(self):
        recolored_frames = []
        for i in range(len(self.frames)):
            recolored = self._recolor_frame(self.frames[i], i)
            recolored_frames.append(recolored)
        return recolored_frames

    def _recolor_frame(self, frame, frame_no):
        recolored = []
        for i in range(len(frame)):
            blank = True
            if frame[i] == -1:
                map_index = -1
            elif frame[i] == 0:
                map_index = -2
            else:
                map_index = i % 8 # column index
                blank = False
            base_color = self.FRAME_RECOLOR_MAP[map_index]
            if not blank:
                row = (i // 8)    # brighten based on row 
            else:
                row = 0
            recolored.append(base_color + row//2)
        return recolored         

    def animate(self, rate=1, autoplay=False, remote=None):
        # todo: drift-correct timing...
        if rate == 0.5:
            backing_track = 'mario_halftime.mp3'
            self.painter.sampler.load_samples('dyno_sim')
        elif rate == 1:
            backing_track = 'mario.mp3'
        else:
            backing_track = None
        if backing_track:
            self.painter.sampler._load_backing_track(backing_track)

        print(self._ticks_to_seconds(sum(self.timing_track)))
        t0 = time.time()
        input_time = 0
        actual_sleep = 0
        for i in range(len(self.frames)):
            if i == self.INTRO_PAD_FRAMES and backing_track:
                self.painter.sampler.play_backing_track()
            # todo: give a pre-frame lead grace period to allow early hits
            input_time += self.timing_track[i] / rate

            self.painter.remap_sampler(self.frames[i])
            self.painter.send_sysex(self.painter.as_page(self.colored_frames[i]))
            if autoplay:
                for j in range(56, 64):
                    if self.frames[i][j] > 0:
                        self.painter.sampler.play_note(j)
            #frame_duration = self._ticks_to_seconds(self.timing_track[i]) / rate
            #lead_time = .05
            #frame_delay = frame_duration - lead_time
            #time.sleep(frame_delay)
            #try:
            #    self.painter.remap_sampler(self.frames[i+1])
            #except IndexError:
            #    break
            #time.sleep(lead_time)
            playback_time = time.time() - t0
            duration_to_next_frame = self._ticks_to_seconds(input_time) - playback_time
            if duration_to_next_frame > 0.0:
                actual_sleep += duration_to_next_frame
                time.sleep(duration_to_next_frame)
        t1 = time.time()
        elapsed = t1 - t0# - 16*self._ticks_to_seconds(120*16)
        print(f'midi track finished in {elapsed:.2f} seconds.')
        print(f'actual_sleep: {actual_sleep:.2f}')
        print(f'input_time: {self._ticks_to_seconds(input_time):.2f}')

    def _prepare_play_track(self, re_segment=True):
        self.midi_file = mido.MidiFile(self.midi_path)
        self.midi_track = self.midi_file.tracks[0]
        self.segments = midi_segmenter(self.midi_track)
        self.note_set = set(m.note for m in self.midi_track if isinstance(m, mido.Message)
                        and m.type == 'note_on')
        if re_segment:
            self._re_segment()
        self.play_track = build_play_track(self.segments, self.note_set, cols=3)
        self.frames = self._build_frames(self.play_track)
        self.colored_frames = self._recolor_frames()
        #self.colored_frames = [self._recolor_frame(f) for f in self.frames]

    def _build_frames(self, play_track):
        n = len(play_track)//8 - 8
        frames = []
        for i in range(n):
            frame = get_window(play_track, offset=i)
            flipped = flip_frame_for_display(frame)
            frames.append(flipped)
        return frames

    def _re_segment(self, seg_ticks=40):
        # introduce variable timing to the playtrack
        # e.g. handle triplets w/different speed than straight-divisions
        segs_per_quarter_note = 12
        timing_track = []
        new_segments = []
        for _ in range(self.INTRO_PAD_FRAMES): # intro pad timing
            timing_track.append(seg_ticks*3)
        def divide_into_three(quarter_note):
            divisions = quarter_note[::4]
            for triplet_hit in divisions:
                new_segments.append(triplet_hit)
                timing_track.append(seg_ticks*4)
        def divide_into_four(quarter_note):
            divisions = quarter_note[::3]
            for sixteenth_hit in divisions:
                new_segments.append(sixteenth_hit)
                timing_track.append(seg_ticks*3)
        strikes = { 'triplet': (1,0,0,0,1,0,0,0,1,0,0,0) }
        # check a quarter note at a time, check for triplet spacing
        for i in range(0, len(self.segments), segs_per_quarter_note):
            quarter_note = self.segments[i:i+segs_per_quarter_note]
            strike_map = tuple(1 if x else 0 for x in quarter_note)
            if strike_map == strikes['triplet']:
                divide_into_three(quarter_note)
            else:
                divide_into_four(quarter_note)

        for _ in range(self.OUTRO_PAD_FRAMES): # todo: fix consistency with padding
            timing_track.append(seg_ticks*3)
        self.timing_track = timing_track
        self.segments = new_segments

def midi_segmenter(msgs: mido.MidiTrack):
    msgs = [m for m in msgs if isinstance(m, mido.Message)]
    ticks_per_segment = 40 # 12th of a quarter note in ticks
    sequence = iter(msgs)
    t = 0
    i = 0
    segments = []
    current_segment = []
    for msg in sequence:
        t += msg.time
        if msg.type != 'note_on':
            continue
        if t >= (i+1)*ticks_per_segment:
            residual = t - i*ticks_per_segment
            passed_segments = residual // ticks_per_segment
            segments.append(deepcopy(current_segment))
            current_segment = [ ]
            for _ in range(passed_segments - 1):
                segments.append([])
            i += passed_segments # advance to next segment (12th of a q-note)
        if msg.velocity > 0:
            current_segment.append(msg)
    return segments

