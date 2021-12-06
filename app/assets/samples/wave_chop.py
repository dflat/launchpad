#!/usr/bin/env python3
import wave
import os
import sys

def chop_into_samples(wav_path, out_dir, n_segments, seconds_per_cut=1,
                        start_note=48):
    if not os.path.exists(out_dir):
        os.mkdir(out_dir)
    f = wave.open(wav_path, 'rb')
    chunk_size = seconds_per_cut*f.getframerate()*f.getnchannels()
    params = list(f.getparams())
    params[3] = chunk_size   # n frames
    note_midi_val = start_note
    for i in range(n_segments):
        try:
            segment = f.readframes(chunk_size)
        except wave.Error:
            break
        outpath = os.path.join(out_dir, f'{note_midi_val}.wav') 
        with wave.open(outpath, 'wb') as g:
            g.setparams(params)
            g.writeframes(segment)
        note_midi_val += 1 
    f.close()

def make_midi_file_chromatic(start_note=24, octaves=6, note_len=480*4,
                                velocity=64):
    track = mido.MidiTrack()
    for i in range(12*octaves):
        msg = mido.Message('note_on', note=start_note+i,
                            velocity=velocity, time=note_len)
        track.append(msg)
    mid = mido.MidiFile()
    mid.tracks.append(track)
    name = f'chromatic_{start_note}_to_{start_note+12*octaves}.mid' 
    mid.save(name)
    return mid

DEFAULT_START_NOTE = 24
DEFAULT_SEGMENTS = 12*6
if __name__ == '__main__':
    program, *args = sys.argv
    if args[0].lower() in ['h', '-h', 'help', '--help']:
        print(f"USAGE: {__file__} source_wav_path out_dir_name [n_segments] [start_note]")
        print(f"\t The default n_segments is {DEFAULT_SEGMENTS}")
        print(f"\t The default start_note is {DEFAULT_START_NOTE}")
        sys.exit(0)
    source_wav = args[0]
    out_dir = args[1]
    n_segments = DEFAULT_SEGMENTS
    start_note = DEFAULT_START_NOTE
    if len(args) > 2:
        n_segments = int(args[2])
    if len(args) > 3:
        start_note = int(args[3])
    print(source_wav, out_dir, n_segments, start_note)
    chop_into_samples(source_wav, out_dir, n_segments=n_segments,
                                        seconds_per_cut=1, start_note=start_note)
