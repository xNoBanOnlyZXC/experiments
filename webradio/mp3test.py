from flask import Flask, render_template
from flask_socketio import SocketIO
import threading
import time
import os
from pydub import AudioSegment
import miniaudio
import io

app = Flask(__name__)
socketio = SocketIO(app)

music_folder = 'music'  # Папка с вашими mp3 файлами
music_files = os.listdir(music_folder)
current_track = 0
audio_stream = None
stream_thread = None
running = True

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

def audio_stream_worker(stream_file):
    global audio_stream
    audio_stream = miniaudio.decode_stream_file(stream_file, miniaudio.DecoderFormat.PCM16)
    while running:
        # Здесь вы можете обработать аудиоданные по своему усмотрению
        time.sleep(0.1)

def audio_stream():
    global current_track
    while True:
        if music_files:
            track_path = os.path.join(music_folder, music_files[current_track])
            audio = AudioSegment.from_mp3(track_path)

            # Конвертируем аудиофайл в байты
            audio_data = io.BytesIO()
            audio.export(audio_data, format='wav')  # Конвертируем в другой формат, чтобы отправить
            audio_data.seek(0)

            CHUNK = 1024
            sampleRate = 44100
            bitsPerSample = 16
            channels = 2
            first_run = True
            wav_header = genHeader(sampleRate, bitsPerSample, channels)
            # Отправляем аудиоданные
            if first_run:
                data = wav_header + audio_data.read()
            else:
                data = audio_data.read()
            socketio.emit('audio', {
                'data': data,  # Конвертируем в строку для передачи
                'track_name': music_files[current_track]
            })

            # Переходим к следующему треку
            current_track = (current_track + 1) % len(music_files)
            time.sleep(audio.duration_seconds)  # Ждем время длительности трека

@app.route('/')
def index():
    return render_template('test.html')

if __name__ == '__main__':
    threading.Thread(target=audio_stream).start()
    socketio.run(app)
