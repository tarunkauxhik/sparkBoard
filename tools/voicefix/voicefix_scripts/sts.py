import os, sys, json, subprocess, requests, time
KEY = open("/home/claude/.secrets/el.env").read().split("=",1)[1].strip()
LEDGER = "/home/claude/voicefix/ledger.json"
CAP_SECONDS = 240  # hard cap: 4 min of audio total (~$0.48 at $0.12/min)
def dur(p): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p]).decode())
def convert(src, voice_id, out, seed=42):
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {"seconds": 0, "calls": []}
    d = dur(src)
    if led["seconds"] + d > CAP_SECONDS: sys.exit(f"BUDGET CAP: {led['seconds']:.1f}s used, +{d:.1f}s would exceed {CAP_SECONDS}s")
    r = requests.post(f"https://api.elevenlabs.io/v1/speech-to-speech/{voice_id}?output_format=mp3_44100_128",
        headers={"xi-api-key": KEY},
        data={"model_id": "eleven_multilingual_sts_v2", "seed": str(seed), "remove_background_noise": "false",
              "voice_settings": json.dumps({"stability": 0.5, "similarity_boost": 0.85, "style": 0.0, "use_speaker_boost": True})},
        files={"audio": open(src, "rb")}, timeout=180)
    if r.status_code != 200: sys.exit(f"ERROR {r.status_code}: {r.text[:300]}")
    open(out, "wb").write(r.content)
    led["seconds"] += d; led["calls"].append({"src": src, "voice": voice_id, "sec": round(d, 2), "t": time.ctime()})
    json.dump(led, open(LEDGER, "w"), indent=1)
    print(f"ok {out}  in={d:.2f}s out={dur(out):.2f}s  total_used={led['seconds']:.1f}s (~${led['seconds']/60*0.12:.3f})")
if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2], sys.argv[3])
