"""녹화본에 장면 설명(영문 자막)을 얹는다. captions.json: [{t, text|null}, ...] — 다음 자막이 나올 때까지 보인다."""
import json, subprocess, sys, textwrap, os
S = os.environ.get("OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
caps = json.load(open(f"{S}/captions.json"))
dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f"{S}/demo-raw.mp4"]).decode().strip())
filters = []
for i, c in enumerate(caps):
    if not c["text"]:
        continue
    a = c["t"]; b = caps[i + 1]["t"] if i + 1 < len(caps) else dur
    path = f"{S}/cap_{i}.txt"
    open(path, "w").write("\n".join(textwrap.wrap(c["text"], 78)))
    filters.append(f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:textfile={path}:fontsize=30:fontcolor=white"
                   f":box=1:boxcolor=black@0.62:boxborderw=18:line_spacing=10:x=(w-text_w)/2:y=h-text_h-56:enable='between(t,{a:.2f},{b:.2f})'")
# 개인정보(연락처·Drive 파일 목록)는 흐리게 — 영역마다 잘라 흐린 뒤 그 시간에만 덮는다.
blurs = json.load(open(f"{S}/blurs.json")) if os.path.exists(f"{S}/blurs.json") else []
graph, last = [], "0:v"
for k, b in enumerate(blurs):
    t1 = b["t1"] if b["t1"] is not None else dur
    w = min(b["w"], 1920 - b["x"]) // 2 * 2; h = min(b["h"], 1080 - b["y"]) // 2 * 2
    graph.append(f"[{last}]split[m{k}][c{k}];[c{k}]crop={w}:{h}:{b['x']}:{b['y']},boxblur=9:2[b{k}];"
                 f"[m{k}][b{k}]overlay={b['x']}:{b['y']}:enable='between(t,{b['t0']:.2f},{t1:.2f})'[v{k}]")
    last = f"v{k}"
graph.append(f"[{last}]" + ",".join(filters) + "[out]")
out = sys.argv[1] if len(sys.argv) > 1 else f"{S}/blackmoa-oauth-demo.mp4"
subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{S}/demo-raw.mp4", "-filter_complex", ";".join(graph), "-map", "[out]",
                       "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
print(out, os.path.getsize(out))
