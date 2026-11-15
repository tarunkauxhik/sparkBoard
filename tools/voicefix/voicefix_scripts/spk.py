import numpy as np, librosa, warnings, sys
warnings.filterwarnings("ignore")
from resemblyzer import VoiceEncoder, preprocess_wav
files = sys.argv[1:]
enc = VoiceEncoder("cpu", verbose=False)
E = []
for p in files:
    E.append(enc.embed_utterance(preprocess_wav(p)))
    y, sr = librosa.load(p, sr=16000)
    f0 = librosa.yin(y, fmin=80, fmax=400, sr=sr)
    rms = librosa.feature.rms(y=y)[0]
    voiced = f0[(rms[:len(f0)] > np.percentile(rms, 60))]
    print(f"{p.split('/')[-1]:28s} pitch_median={np.median(voiced):5.0f}Hz")
E = np.array(E); S = E @ E.T
print("similarity matrix:")
for i, p in enumerate(files):
    print(f"{i+1}: " + " ".join(f"{S[i,j]:.2f}" for j in range(len(files))))
