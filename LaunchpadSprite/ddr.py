import random
import mido
from copy import deepcopy
import os

PROJ_ROOT = 'LaunchpadSprite'
MIDI_DIR = 'assets/midi'
MIDI_DIR_PATH = os.path.join(PROJ_ROOT, MIDI_DIR)

def build_play_track(segments, note_set, cols=8):
    def build_row(track_row):
        display_row = [-1]*8
        n = len(track_row)
        display_row[:n] = track_row 
        return display_row
    def build_note_map(note_set):
        note_map = { }
        for i, note in enumerate(sorted(note_set)):
            note_map[note] = i % cols
        return note_map
    note_map = build_note_map(note_set)
    track = []
    track.extend([0]*8*cols) # intro padding
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
        track.extend(track_row)
    track.extend([0]*8*cols) # outro padding
    return track

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
    def __init__(self, midi_path, bpm=120, ticks_per_beat=480, segment_ticks=40):
        self.midi_path = os.path.join(MIDI_DIR_PATH, midi_path)
        self.bpm = bpm
        self.ticks_per_beat = ticks_per_beat
        self.seconds_per_beat = 60/bpm
        self.bpm_ticks = int(self.seconds_per_beat*10**5)
        self.segment_ticks = segment_ticks
        self.seconds_per_segment = (segment_ticks/ticks_per_beat)*(60/bpm) 
        self._prepare_play_track()

    def _prepare_play_track(self):
        self.midi_file = mido.MidiFile(self.midi_path)
        self.midi_track = self.midi_file.tracks[0]
        self.segments = midi_segmenter(self.midi_track)
        self.note_set = set(m.note for m in self.midi_track if isinstance(m, mido.Message)
                        and m.type == 'note_on')
        self.play_track = build_play_track(self.segments, self.note_set, cols=8)
        self.frames = self._build_frames(self.play_track)

    def _build_frames(self, play_track):
        n = len(play_track)//8 - 8
        frames = []
        for i in range(n):
            frame = get_window(play_track, offset=i)
            flipped = flip_frame_for_display(frame)
            frames.append(flipped)
        return frames

