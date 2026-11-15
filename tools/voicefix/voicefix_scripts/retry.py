import sys, subprocess, json, re, difflib, requests, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/claude/voicefix"); from sts import convert
KEY = open("/home/claude/.secrets/el.env").read().split("=",1)[1].strip()
ref = json.load(open("ref_transcripts.json"))
MUST = {"3": ["फिर"], "4": ["feel"], "5": ["फर्क", "दिखता"]}
def scribe(p):
    r = requests.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": KEY}, data={"model_id": "scribe_v1"}, files={"file": open(p, "rb")})
    return r.json().get("text", "")
def sh(*a): subprocess.run(a, check=True)
def build(opt, i, sts_file):
    w = f"out/{opt}/work"
    vdur = subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=duration","-of","csv=p=0",f"raw/clip{i}.mp4"]).decode().strip()
    sh("ffmpeg","-v","error","-y","-i",sts_file,"-i",f"sep/htdemucs/clip{i}/no_vocals.wav","-filter_complex",
       f"[0]aresample=48000,pan=stereo|c0=c0|c1=c0[v];[1]aresample=48000[b];[v][b]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,apad,atrim=0:{vdur}[a]",
       "-map","[a]","-ar","48000",f"{w}/mix{i}.wav")
    sh("ffmpeg","-v","error","-y","-i",f"raw/clip{i}.mp4","-i",f"{w}/mix{i}.wav","-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","192k","-shortest",f"out/{opt}/clip{i}.mp4")
    sh("ffmpeg","-v","error","-y","-i",f"out/{opt}/clip{i}.mp4","-vn","-ac","1","-ar","16000",f"{w}/a{i}_16k.wav")
if __name__ == "__main__":
    opt, voice, i = sys.argv[1], sys.argv[2], sys.argv[3]
    w = f"out/{opt}/work"
    attempts = [(7, None), (123, 1.07 if i == "5" else None)]
    for seed, ratio in attempts:
        src = f"{w}/in{i}.wav"
        if ratio:
            src = f"{w}/in{i}_r.wav"
            sh("ffmpeg","-v","error","-y","-i",f"audio/c{i}_orig.wav","-ac","1","-af",f"rubberband=pitch={ratio}:formant=preserved:pitchq=quality","-ar","44100",src)
        out = f"{w}/sts{i}_s{seed}.mp3"
        convert(src, voice, out, seed=seed)
        sh("ffmpeg","-v","error","-y","-i",out,"-ac","1","-ar","16000",f"{w}/try{i}.wav")
        txt = scribe(f"{w}/try{i}.wav")
        ok = all(k in txt for k in MUST[i])
        print(f"   {opt} clip{i} seed={seed} ratio={ratio}: {'PASS' if ok else 'fail'} | {txt}")
        if ok:
            build(opt, i, out); break
    else:
        print(f"   {opt} clip{i}: no passing take, keeping best previous and flagging")
