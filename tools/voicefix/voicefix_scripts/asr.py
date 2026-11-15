import sys, json
from faster_whisper import WhisperModel
m = WhisperModel(sys.argv[1], device="cpu", compute_type="int8")
out = {}
for p in sys.argv[2:]:
    import librosa; a,_ = librosa.load(p, sr=16000); segs, info = m.transcribe(a, word_timestamps=True, task="transcribe")
    ws = [{"w": x.word.strip(), "s": round(x.start, 2), "e": round(x.end, 2)} for s in segs for x in s.words]
    out[p] = ws
    print(info.language, round(info.language_probability,2), p.split('/')[-1], f"[{ws[0]['s']}-{ws[-1]['e']}s]" if ws else "", " ".join(w["w"] for w in ws))
json.dump(out, open(sys.argv[2].rsplit('/',1)[0] + "/asr_" + sys.argv[1] + ".json", "w"), indent=1)
