import asyncio
import json
import re
import subprocess
import sys
import wave

import edge_tts
import imageio_ffmpeg

VOICE = sys.argv[1] if len(sys.argv) > 1 else "en-US-AndrewNeural"
RATE = sys.argv[2] if len(sys.argv) > 2 else "+14%"
FF = imageio_ffmpeg.get_ffmpeg_exe()


def speak(t):
    t = re.sub(r"\bLLM\b", "L L M", t)
    t = re.sub(r"\bMCP\b", "M C P", t)
    t = (
        t.replace("STS", "S T S")
        .replace("GRAPH.COPY", "graph copy")
        .replace("theseus.yaml", "theseus dot yaml")
        .replace("FalkorDB", "Falkor D B")
    )
    return t


async def one(s):
    c = edge_tts.Communicate(speak(s["show"]), VOICE, rate=RATE, boundary="WordBoundary")
    ev = []
    with open(f"audio/{s['id']}.mp3", "wb") as f:
        async for ch in c.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                ev.append(
                    [
                        round(ch["offset"] / 1e7, 3),
                        round((ch["offset"] + ch["duration"]) / 1e7, 3),
                        ch["text"],
                    ]
                )
    subprocess.run(
        [
            FF,
            "-y",
            "-loglevel",
            "error",
            "-i",
            f"audio/{s['id']}.mp3",
            "-ar",
            "44100",
            "-ac",
            "1",
            f"audio/{s['id']}.wav",
        ],
        check=True,
    )
    w = wave.open(f"audio/{s['id']}.wav")
    s["dur"] = round(w.getnframes() / w.getframerate(), 3)
    s["words"] = ev


async def main():
    sc = json.load(open("script.json"))
    for s in sc:
        await one(s)
        print(s["id"], s["dur"], len(s["words"]))
    json.dump(sc, open("script.json", "w"), indent=1)
    print("total", round(sum(s["dur"] + 0.55 + s["tail"] for s in sc), 1), "s")


asyncio.run(main())
