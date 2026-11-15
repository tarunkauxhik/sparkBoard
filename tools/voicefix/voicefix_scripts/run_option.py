import sys, subprocess, json, numpy as np, librosa, warnings, os
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/voicefix"); from sts import convert
opt, voice = sys.argv[1], sys.argv[2]
TARGET = 250.0
os.makedirs(f"out/{opt}/work", exist_ok=True)
def pitch(p):
    y, sr = librosa.load(p, sr=16000); f0 = librosa.yin(y, fmin=80, fmax=400, sr=sr)
    rms = librosa.feature.rms(y=y)[0]; return float(np.median(f0[rms[:len(f0)] > np.percentile(rms, 60)]))
def sh(*a): subprocess.run(a, check=True)
for i in range(1, 6):
    w = f"out/{opt}/work"
    src = f"audio/c{i}_orig.wav"
    ratio = TARGET / pitch(f"audio/c{i}_16k.wav")
    af = f"rubberband=pitch={ratio:.3f}:formant=preserved:pitchq=quality" if abs(ratio - 1) > 0.03 else "anull"
    sh("ffmpeg", "-v", "error", "-y", "-i", src, "-ac", "1", "-af", af, "-ar", "44100", f"{w}/in{i}.wav")
    if not os.path.exists(f"{w}/sts{i}.mp3"):
        convert(f"{w}/in{i}.wav", voice, f"{w}/sts{i}.mp3")
    vdur = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration", "-of", "csv=p=0", f"raw/clip{i}.mp4"]).decode().strip()
    # voice + original room bed, loudness to -14 LUFS, exact video length
    sh("ffmpeg", "-v", "error", "-y", "-i", f"{w}/sts{i}.mp3", "-i", f"sep/htdemucs/clip{i}/no_vocals.wav",
       "-filter_complex", f"[0]aresample=48000,pan=stereo|c0=c0|c1=c0[v];[1]aresample=48000[b];[v][b]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,apad,atrim=0:{vdur}[a]",
       "-map", "[a]", "-ar", "48000", f"{w}/mix{i}.wav")
    sh("ffmpeg", "-v", "error", "-y", "-i", f"raw/clip{i}.mp4", "-i", f"{w}/mix{i}.wav", "-map", "0:v:0", "-map", "1:a:0",
       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", f"out/{opt}/clip{i}.mp4")
    sh("ffmpeg", "-v", "error", "-y", "-i", f"out/{opt}/clip{i}.mp4", "-vn", "-ac", "1", "-ar", "16000", f"{w}/a{i}_16k.wav")
    print(f"  clip{i}: pitch ratio {ratio:.3f} done")
