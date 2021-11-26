from PIL import Image
import string
import os 
import time

ROOT_DIR = '/Users/Ricky/Code/Python/Games/Snake/LaunchpadSprite'
FONT_ITALIC_IMG = os.path.join(ROOT_DIR, 'font_italic.png')

class Character:
    SHADES = ['m', 'e', 'x', 'o', ' ']
    def __init__(self, pixels, width, rows=8):
        self.pixels = pixels
        self.width = width
        self.rows = rows
        
    def get_row(self, i):
        assert(i < self.rows)
        offset = self.width*i
        return self.pixels[offset:offset+self.width]
        
class Font:
    VALID_CHARS = string.ascii_uppercase + '!?. '
    WHITE_VAL = 4
    SPACE_WIDTH = 5
    def __init__(self, source_image):
        self.im = Image.open(source_image)
        self.characters = []
        self._load()
        self._build_lookup() 
        
    def get_char(self, char):
        char = char.upper()
        assert(char in self.VALID_CHARS) 
        return self._lookup[char]
        
    def _load(self):
        self.im = self.im.convert('RGB')
        w,h = self.im.size
        self.pixels = list(self.im.getdata())
        self.track_row = self.pixels[260*(h-1):]    
        offset = 0
        while True:
            character, offset = self._read_letter(offset)    
            self.characters.append(character)
            if offset >= w:
                break
                
    def _read_letter(self, offset):
        space = (255,0,0) 
        letter_width = 0
        im_w, im_h = self.im.size
        while self.track_row[offset] == space: # skip past leading space
            offset += 1
        while True:                      # read until next space
            index = offset + letter_width
            if index >= im_w or self.track_row[index] == space:
                break
            letter_width += 1            # calculate letter width 
        letter = []
        for row in range(im_h):
            for col in range(letter_width):
                pix = self.pixels[row*im_w + offset + col]
                shade = self._get_quartile(pix[0]) # use Red Channel of Pixel
                letter.append(shade)
        return Character(letter, letter_width), offset+letter_width
        
    def _get_quartile(self, val):
        return (val // 64) + 1 if val > 0 else 0

    def _build_lookup(self):
        """
        Build (ascii character) => (pixel representation) mapping/lookup
        """
        # add a space character
        sw = self.__class__.SPACE_WIDTH
        space_char = Character([self.WHITE_VAL]*sw*8, sw) 
        self.characters.append(space_char)
        self._lookup = dict(zip(self.VALID_CHARS, self.characters))

class Message:
    WHITE_SPACE = 4 # code to signify white/off pixel 
    ROWS = 8 
    def __init__(self, message, font):
        self.font = font
        self.message = message.upper()
        self.total_width = None
        self._validate()
        self._get_chars() 
        self._construct()
        
    def print(self):
        for i in range(Message.ROWS):
            for j in range(self.total_width):
                print(Character.SHADES[self.pixels[i*self.total_width + j]], end=" ")
            print()

    def _validate(self):
        for c in self.message:
            assert(c in self.font.__class__.VALID_CHARS)
            
    def _get_chars(self):  
        self.chars = [self.font.get_char(c) for c in self.message] 
        
    def _construct(self, spaces=1):
        chars = self.chars
        pixels = []
        self.total_width = sum(c.width+spaces for c in chars)
        n = len(chars)
        for row in range(Message.ROWS):
            for i in range(n):
                segment = chars[i].get_row(row)
                pixels.extend(segment + [self.WHITE_SPACE]*spaces)
        self.pixels = pixels 

class Marquee:
    def __init__(self, message: str, font:Font=None, painter=None):
        if font is None:
            font = Font(source_image=FONT_ITALIC_IMG)
        self.font = font
        self.message = Message(message, font) 
        self.frames = []
        self.painter = painter
        self._build_sequence() 

    def _crop(self, offset, window_width=8):
        cropped = []
        for i in range(self.message.ROWS):
            start = i*self.message.total_width + offset
            segment = self.message.pixels[start:start+window_width]
            cropped.extend(segment)
        return cropped 
     
    def _build_sequence(self, window_width=8):
        last = self.message.total_width - window_width
        for offset in range(last):
            frame = self._crop(offset)             
            self.frames.append(frame)

    def animate(self, fps=15):
        for frame in self.frames:
            self.print_frame(frame)
            time.sleep(1/fps)

    def print_frame(self, frame, width=8): # TODO: overwrite this method as sysex
        if os.name == 'posix':
            os.system('clear')
        else:
            os.system('cls')
        for i in range(8):
            for j in range(width):
                print(Character.SHADES[frame[i*width + j]], end=" ")
            print()

