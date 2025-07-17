from flask import Flask, Response, render_template
import pyaudio
import threading, os, io, time
from pydub import AudioSegment

app = Flask(__name__)

music_folder = 'music'
FORMAT = pyaudio.paInt16
CHANNELS = 2
RATE = 44100
CHUNK = 4096
RECORD_SECONDS = 5
sampleRate = 44100
bitsPerSample = 16
channels = 2
 
audio1 = pyaudio.PyAudio()
z = False
stream = audio1.open(format=FORMAT, channels=CHANNELS,
                        rate=RATE, input=True,
                        frames_per_buffer=CHUNK)

def genHeader(sampleRate, bitsPerSample, channels):
    datasize = 2000*10**6
    o = bytes("RIFF",'ascii')                                               # (4byte) Marks file as RIFF
    o += (datasize + 36).to_bytes(4,'little')                               # (4byte) File size in bytes excluding this and RIFF marker
    o += bytes("WAVE",'ascii')                                              # (4byte) File type
    o += bytes("fmt ",'ascii')                                              # (4byte) Format Chunk Marker
    o += (16).to_bytes(4,'little')                                          # (4byte) Length of above format data
    o += (1).to_bytes(2,'little')                                           # (2byte) Format type (1 - PCM)
    o += (channels).to_bytes(2,'little')                                    # (2byte)
    o += (sampleRate).to_bytes(4,'little')                                  # (4byte)
    o += (sampleRate * channels * bitsPerSample // 8).to_bytes(4,'little')  # (4byte)
    o += (channels * bitsPerSample // 8).to_bytes(2,'little')               # (2byte)
    o += (bitsPerSample).to_bytes(2,'little')                               # (2byte)
    o += bytes("data",'ascii')                                              # (4byte) Data Chunk Marker
    o += (datasize).to_bytes(4,'little')                                    # (4byte) Data size in bytes
    return o

@app.route('/audio')
def audio():
    # start Recording
    def sound():
        
        wav_header = genHeader(sampleRate, bitsPerSample, channels)
        #frames = []
        first_run = True
        while True:
           if first_run:
               data = wav_header + z.read(CHUNK)
               first_run = False
           else:
               data = z.read(CHUNK)
           yield(data)
           time.sleep(1)

    return Response(sound())

@app.route('/')
def index():
    """Video streaming home page."""
    return render_template('index.html')

def writemusicworker():
    music_files = os.listdir(music_folder)
    music_files = [f for f in music_files if f.endswith('.mp3')]
    while True:  # Бесконечный цикл для воспроизведения плейлиста по кругу
        global z
        for file_name in music_files:
            # Загружаем MP3 файл
            faudio = AudioSegment.from_mp3(os.path.join(music_folder, file_name))
            audio = faudio.set_frame_rate(sampleRate).set_channels(channels).set_sample_width(2)
            raw_data = audio.raw_data
            stream = io.BytesIO(raw_data)
            z = stream
            print(round(len(faudio)/1000)+1)
            time.sleep(len(faudio)/1000)
            # stream.write(raw_data)

      
if __name__ == "__main__":
    asd = threading.Thread(target=writemusicworker)
    asd.start()
    app.run(host='0.0.0.0', threaded=True,port=5000)