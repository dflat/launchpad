import wave
import os
# default segments should be 37 for 3 octaves and a finishing note
def chop_into_samples(wav_path, out_dir, n_segments, seconds_per_cut=1,
                        start_note=48):
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
