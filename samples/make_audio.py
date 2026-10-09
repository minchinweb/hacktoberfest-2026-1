"""Generate synthetic memo audio from samples/memos.json into samples/audio/.

Piper (https://github.com/OHF-Voice/piper1-gpl):  python samples/make_audio.py --voice en_US-lessac-medium.onnx
Windows fallback (SAPI, no install):               python samples/make_audio.py --sapi
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

here = Path(__file__).parent
ap = argparse.ArgumentParser()
ap.add_argument("--voice", help="path to a Piper .onnx voice")
ap.add_argument("--sapi", action="store_true")
args = ap.parse_args()
out = here / "audio"
out.mkdir(exist_ok=True)
for m in json.loads((here / "memos.json").read_text(encoding="utf-8")):
    wav = out / f"{m['ts']}.wav"
    if args.sapi:
        ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              f"$s.SetOutputToWaveFile('{wav}'); $s.Speak('{m['say'].replace(chr(39), chr(39)*2)}'); $s.Dispose()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    elif args.voice:
        subprocess.run([sys.executable, "-m", "piper", "-m", args.voice, "-f", str(wav)], input=m["say"], text=True, check=True)
    else:
        sys.exit("pass --voice <piper.onnx> or --sapi")
    print(wav)
