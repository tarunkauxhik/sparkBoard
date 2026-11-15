import sys, subprocess, requests, re
sys.path.insert(0, "/home/claude/voicefix"); from sts import convert; from retry import build, scribe
opt, voice = sys.argv[1], sys.argv[2]
w = f"out/{opt}/work"
def dur(p): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p]).decode())
slow = "test/c5_slow.wav"
out = f"{w}/sts5_slow.mp3"
if opt == "1_original_match":
    subprocess.run(["cp", "test/c5_slow_clone.mp3", out], check=True)
else:
    convert(slow, voice, out, seed=42)
target = dur("audio/c5_orig.wav")
factor = dur(out) / target
subprocess.run(["ffmpeg","-v","error","-y","-i",out,"-af",f"rubberband=tempo={factor:.5f}:pitchq=quality","-ac","1","-ar","44100",f"{w}/sts5_fixed.wav"], check=True)
subprocess.run(["ffmpeg","-v","error","-y","-i",f"{w}/sts5_fixed.wav","-ar","16000",f"{w}/try5.wav"], check=True)
txt = scribe(f"{w}/try5.wav")
ok = "दिखता" in txt and re.search(r"फर्क|फर्ग|frag|farak|frak|ferk", txt) is not None
print(f"   {opt} clip5 len={dur(f'{w}/sts5_fixed.wav'):.2f}s (orig {target:.2f}s): {'PASS' if ok else 'FAIL'} | {txt}")
if ok: build(opt, "5", f"{w}/sts5_fixed.wav")
