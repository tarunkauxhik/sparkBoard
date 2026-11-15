import sys, subprocess, re, numpy as np, librosa, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/voicefix"); from sts import convert; from retry import build, scribe
def pitch(p):
    y, sr = librosa.load(p, sr=16000); f0 = librosa.yin(y, fmin=80, fmax=400, sr=sr)
    rms = librosa.feature.rms(y=y)[0]; return float(np.median(f0[rms[:len(f0)] > np.percentile(rms, 60)]))
def dur(p): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p]).decode())
def sh(*a): subprocess.run(a, check=True)
opt, voice, i, seed, prev_in_ratio, prev_out = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), float(sys.argv[5]), sys.argv[6]
w = f"out/{opt}/work"
target = float(np.median([pitch(f"{w}/a2_16k.wav"), pitch(f"{w}/a3_16k.wav")]))
got = pitch(prev_out)
ratio = min(prev_in_ratio * target / got, 1.40)
slow = (i == "5")
af = (f"rubberband=tempo=0.75:" if slow else "rubberband=") + f"pitch={ratio:.4f}:formant=preserved:pitchq=quality"
src = f"{w}/pc_in{i}.wav"
sh("ffmpeg","-v","error","-y","-i",f"audio/c{i}_orig.wav","-ac","1","-af",af,"-ar","44100",src)
out = f"{w}/pc_sts{i}.mp3"
convert(src, voice, out, seed=seed)
fin = out
if slow:
    f = dur(out) / dur(f"audio/c{i}_orig.wav")
    sh("ffmpeg","-v","error","-y","-i",out,"-af",f"atempo={f:.6f}","-ac","1","-ar","44100",f"{w}/pc_fix{i}.wav"); fin = f"{w}/pc_fix{i}.wav"
sh("ffmpeg","-v","error","-y","-i",fin,"-ac","1","-ar","16000",f"{w}/pc_chk{i}.wav")
p = pitch(f"{w}/pc_chk{i}.wav"); t = scribe(f"{w}/pc_chk{i}.wav")
MUST = {"4": [r"feel"], "5": [r"दिखता", r"फर्क|फर्ग|frag|farak|frak|ferk|ferg"]}
ok_words = all(re.search(k, t) for k in MUST[i])
ok_pitch = abs(p / target - 1) <= 0.07
print(f"   {opt} clip{i}: in-ratio {ratio:.3f} -> pitch {p:.0f}Hz (target {target:.0f}, before {got:.0f}) words={'ok' if ok_words else 'MISS'} | {t[-70:]}")
if ok_pitch and (ok_words or i == "5" and abs(p / target - 1) < abs(got / target - 1)):
    build(opt, i, fin); print("   -> kept")
else:
    print("   -> rejected, previous version stays")
