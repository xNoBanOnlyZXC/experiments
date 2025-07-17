from pydub import AudioSegment
import os
music_folder = 'music'
music_files = [f for f in os.listdir(music_folder) if f.endswith('.mp3')]

for filename in music_files:
    sound = AudioSegment.from_mp3(music_folder+'/'+filename)
    sound.export(music_folder+'/'+filename.split(".mp3")[0]+".wav", format="wav")

print('done')
