import random
import mido
from copy import deepcopy
import os
import time
import threading
import queue
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

class PlayMonitor: # todo: unused so far, breakaway class for PlayTrack playback
    def __init__(self, playtrack, rate=1, autoplay=False):
        self.playtrack = playtrack
        self.rate = rate
        self.autoplay = autoplay

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
        self.segment_ticks = segment_ticks
        self._prepare_play_track()
        self._input_q = self.painter.sampler.input_q

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
            blank = False
            if frame[i] == -1:
                map_index = -1
            elif frame[i] == 0:
                map_index = -2
                blank = True
            else:
                map_index = i % 8 # column index
            base_color = self.FRAME_RECOLOR_MAP[map_index]
            if not blank and False: # todo: this is a test auto-false here..
                row = (i // 8)    # brighten based on row 
            else:
                row = 0
            if map_index == -1 and i//8 == 7: # color bottom row walls green
                base_color = 30
            recolored.append(base_color + row//2)
        return recolored         

    def _clear_queue(self):
        while not self._input_q.empty():
            self._input_q.get()

    def _input_listener(self):
        self._clear_queue()
        current_frame_no = -1
        next_frame_no = 0
        hit_or_miss_log = {i:None for i in range(self.n_frames)}
        self.hit_or_miss_log = hit_or_miss_log
        def get_expected_times():
            t = 0
            times = []
            for note_time in self.timing_track:
                times.append(t)
                t += self._ticks_to_seconds(note_time) / self.rate
            return times
        expected_times = get_expected_times()

        def check_for_hit(pad_index, hit_time, current_frame_no, next_frame_no):
            thresh = self._ticks_to_seconds(self.segment_ticks*2) / self.rate

            expected_time = expected_times[current_frame_no]
            next_expected_time = expected_times[next_frame_no]
            
            print(f'thresh percent = {thresh/(next_expected_time-expected_time):.2f}')

            # todo: should there be a late allowance? or just early..?
            diff = hit_time - expected_time # todo: use this to grade accuracy

            # first time check.
            check_for_leading_hit = False
            if hit_time < next_expected_time:
                # check for hit within current frame
                if hit_or_miss_log[current_frame_no] is None:
                    # current frame has not been hit yet
                    # maybe its a blank and this is a leading hit 
                    if hit_time > (next_expected_time - thresh):
                        check_for_leading_hit = True
                    # or, maybe this is a first well-timed hit
                    # check if correct columns were hit...
                    hit_pad_note = self.frames[current_frame_no][pad_index] 
                    if pad_index >= 56 and hit_pad_note > 0:
                        # make sure pad hit was in bottom row
                        # and that it was not a blank
                        return 'current', hit_pad_note, diff 
                else:
                    check_for_leading_hit = True

                if check_for_leading_hit:
                    # current frame has already been hit (or blank frame leading?)
                    # maybe its a leading hit of the next frame
                    if hit_time > (next_expected_time - thresh):
                        hit_pad_note = self.frames[next_frame_no][pad_index]
                        #print('check for early hit:', next_strike_row)
                        if pad_index >= 56 and hit_pad_note > 0:
                            # make sure pad hit was in bottom row
                            # and that it was not a blank
                            return 'next', hit_pad_note, diff 
            
                    
        notes_in_current_frame = { }
        notes_in_next_frame = { }
        while True:
            got = self._input_q.get()
            if got['type'] == 'hit':
                hit_time = got['time'] - self.start_time
                pad_index = got['pad_index']
                hit_data = check_for_hit(pad_index, hit_time,current_frame_no,
                                                            next_frame_no)
                if not hit_data:
                    self.painter.sampler.play_midi_note(-1) # make sound
                    print('MISS!')
                    continue
                cur_or_next, note_hit, diff = hit_data
                if cur_or_next == 'current':
                    print(f'got a current hit...{diff:.2f} [{note_hit}]')
                    # check if already got a hit early last frame
                    if hit_or_miss_log[current_frame_no]:
                        print('already hit last frame')
                        continue 
                    else:
                        notes_in_current_frame[note_hit] = True
                        self.painter.sampler.play_midi_note(note_hit) # make sound
                        if all(notes_in_current_frame.values()): # whole chord/note hit 
                            hit_or_miss_log[current_frame_no] = diff  # log accuracy of hit
                if cur_or_next == 'next':
                    print(f'got a leading hit...{diff:.2f} [{note_hit}]')
                    notes_in_next_frame[note_hit] = True
                    self.painter.sampler.play_midi_note(note_hit) # make sound
                    if all(notes_in_next_frame.values()): # whole chord/note hit 
                        hit_or_miss_log[next_frame_no] = diff  # log accuracy of hit
            elif got['type'] == 'frame_started':
                # todo: account for if frame was already early hit during last frame
                # by checking hit or miss log
                current_frame_no += 1
                next_frame_no = min(self.n_frames-1, current_frame_no + 1)
                if current_frame_no > 0:
                    if hit_or_miss_log[current_frame_no-1] is None:
                        # check if previous frame was a miss and mark it as such if so.
                        if len(notes_in_current_frame) > 0:
                            hit_or_miss_log[current_frame_no-1] = False
                            print('missed frame #', current_frame_no-1)
                # reset frame variables (current and look ahead [next] frames)
                current_strike_row = self.frames[current_frame_no][56:]
                notes_in_current_frame = {i:False for i in current_strike_row if i > 0}
                next_strike_row = self.frames[next_frame_no][56:]
                notes_in_next_frame = {i:False for i in next_strike_row if i > 0}
            elif got['type'] == 'exit':
                break
        print('ddr playtrack stopped listening')

    def _listen_for_input(self):
        t = threading.Thread(target=self._input_listener, args=())
        t.start()

    def test_player(self):
        def play():
            pass
        t = threading.Thread(target=play, args=())
        t.start()

    def animate(self, rate=1, autoplay=False, remote=None):
        self.rate = rate
        if rate == 0.5:
            backing_track = 'mario_halftime.mp3'
            self.painter.sampler.load_samples('dyno_sim')
        elif rate == 1: 
            backing_track = 'mario_v2.mp3'
        else:
            backing_track = None
        if backing_track:
            self.painter.sampler._load_backing_track(backing_track)

        print(self._ticks_to_seconds(sum(self.timing_track)))
        self.start_time = time.time()
        self._listen_for_input()
        input_time = 0
        actual_sleep = 0
        new_frame_signal = {'type': 'frame_started'}
        self._stop = threading.Event()
        for i in range(len(self.frames)):
            if self._stop.is_set():
                print('playback stopped early.')
                return
            self._input_q.put(new_frame_signal)
            if i == self.INTRO_PAD_FRAMES and backing_track:
                self.painter.sampler.play_backing_track()
            input_time += self.timing_track[i] / rate

            self.painter.remap_sampler(self.frames[i])
            self.painter.send_sysex(self.painter.as_page(self.colored_frames[i]))
            if autoplay:
                for j in range(56, 64):
                    if self.frames[i][j] > 0:
                        delay = random.random()
                        delay = 0*delay
                        t = threading.Timer(delay, self.painter.sampler.play_note,
                                            args=(j,))
                        t.start()
            playback_time = time.time() - self.start_time
            duration_to_next_frame = self._ticks_to_seconds(input_time) - playback_time
            if duration_to_next_frame > 0.0:
                actual_sleep += duration_to_next_frame
                time.sleep(duration_to_next_frame)
        self.end_time = time.time()
        self.stop_listening()
        self.show_diagnostics(actual_sleep, input_time)
        self.display_score(self.hit_or_miss_log)

    def stop_listening(self):
        self._stop.set()
        self.painter.sampler.stop_backing_track()
        self._input_q.put({'type': 'exit'})

    def show_diagnostics(self, actual_sleep, input_time):
        elapsed = self.end_time - self.start_time
        print(f'midi track finished in {elapsed:.2f} seconds.')
        print(f'actual_sleep: {actual_sleep:.2f}')
        print(f'input_time: {self._ticks_to_seconds(input_time):.2f}')

    def display_score(self, hit_or_miss_log):
        for frame, accuracy in hit_or_miss_log.items():
            if accuracy is None:
                continue
            elif accuracy is False:
                print(f'{frame:<4}: miss')
            else:    
                print(f'{frame:<4}: {accuracy:.2f}')
        results = list(hit_or_miss_log.values())
        hits = sum(1 for i in results if i)
        misses = sum(1 for i in results if i == False)
        blanks = sum(1 for i in results if i == None)
        print(f'hits:{hits}, misses:{misses}, blanks:{blanks}')
        print(f'frames:{hits+misses+blanks}')
        

    def _prepare_play_track(self, re_segment=True):
        self.midi_file = mido.MidiFile(self.midi_path)
        self.midi_track = self.midi_file.tracks[0]
        self.segments = midi_segmenter(self.midi_track)
        self.note_set = set(m.note for m in self.midi_track if isinstance(m, mido.Message)
                        and m.type == 'note_on')
        if re_segment:
            self._re_segment(swing=1)
        self.play_track = build_play_track(self.segments, self.note_set, cols=3)
        self.frames = self._build_frames(self.play_track)
        self.n_frames = len(self.frames)
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

    def _re_segment(self, seg_ticks=40, swing=1):
        # introduce variable timing to the playtrack
        # e.g. handle triplets w/different speed than straight-divisions
        segs_per_quarter_note = 12
        timing_track = []
        new_segments = []
        for _ in range(self.INTRO_PAD_FRAMES): # intro pad timing
            timing_track.append(seg_ticks*3)
        def get_swing_ratio(ticks_per_q, ratio):
            assert(ratio >= 1)
            semi = ticks_per_q / 2
            short = semi/ratio
            taken = semi - short
            long = semi + taken
            return round(short), round(long)
        def divide_into_three(quarter_note):
            divisions = quarter_note[::4]
            for triplet_hit in divisions:
                new_segments.append(triplet_hit)
                timing_track.append(seg_ticks*4)
        def divide_into_four(quarter_note):
            divisions = quarter_note[::3]
            swing_short, swing_long = get_swing_ratio(480, swing)
            for i, sixteenth_hit in enumerate(divisions):
                eighth_ticks = swing_long if i < 2 else swing_short
                new_segments.append(sixteenth_hit)
                #timing_track.append(seg_ticks*3)
                timing_track.append(round(eighth_ticks/2))
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

