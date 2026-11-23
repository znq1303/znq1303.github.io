#!/usr/bin/env python3
"""把 videos/ 中的新视频转码到 videos-web/，并自动生成 videos.json 清单。

用法：在项目根目录执行  python tools\\build_videos.py
已转码且比源文件新的视频会自动跳过。
"""
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(ROOT, "videos")
DST_ROOT = os.path.join(ROOT, "videos-web")
MANIFEST = os.path.join(ROOT, "videos.js")
CATS = ["自制", "短剧"]
VF = ("scale=w='min(iw,1920)':h='min(ih,1920)':"
      "force_original_aspect_ratio=decrease:force_divisible_by=2")


def find_ffmpeg():
    candidates = [
        os.environ.get("FFMPEG"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Programs", "Trae CN", "resources", "app", "bin", "ffmpeg.exe"),
    ]
    candidates += glob.glob(r"C:\Program Files (x86)\bililive\ugc_assistant\*\ffmpeg.exe")
    import shutil
    candidates.append(shutil.which("ffmpeg"))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    sys.exit("未找到 ffmpeg，请安装后重试，或设置环境变量 FFMPEG 指向 ffmpeg.exe")


def encode(ffmpeg, src, dst):
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", src,
        "-map", "0:v:0", "-map", "0:a?",
        "-vf", VF,
        "-c:v", "libx264", "-preset", "faster", "-crf", "23",
        "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        dst,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-1500:])
        return False
    return True


def find_image_ffmpeg():
    candidates = [os.environ.get("FFMPEG_IMAGE")]
    candidates += glob.glob(r"C:\Program Files (x86)\bililive\ugc_assistant\*\ffmpeg.exe")
    import shutil
    candidates.append(shutil.which("ffmpeg"))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def find_ffprobe(ffmpeg):
    import shutil
    if ffmpeg:
        same_dir = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe")
        if os.path.isfile(same_dir):
            return same_dir
    trae = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                        "Programs", "Trae CN", "resources", "app", "bin", "ffprobe.exe")
    if os.path.isfile(trae):
        return trae
    return shutil.which("ffprobe")


def probe_duration(ffprobe, path):
    if not ffprobe:
        return None
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return round(float(r.stdout.strip()), 1)
    except ValueError:
        return None


def make_poster(ffmpeg, video, poster):
    for seek in ("1", "0"):
        r = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-ss", seek, "-i", video, "-frames:v", "1",
             "-vf", "scale=640:-2", "-q:v", "3", poster],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and os.path.exists(poster):
            return True
    return False


def mp4s(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(".mp4"))


def main():
    ffmpeg = find_ffmpeg()
    poster_ffmpeg = find_image_ffmpeg()
    ffprobe = find_ffprobe(ffmpeg)
    print(f"使用 ffmpeg: {ffmpeg}")
    print(f"生成封面: {poster_ffmpeg or '未找到支持图片输出的 ffmpeg，跳过'}")

    old = []
    if os.path.isfile(MANIFEST):
        try:
            with open(MANIFEST, encoding="utf-8") as fh:
                text = fh.read()
            old = json.loads(text[text.index("["):text.rindex("]") + 1])
        except (ValueError, OSError):
            print("旧 videos.js 无法读取，将重新生成")

    new_files = []
    for cat in CATS:
        src_dir = os.path.join(SRC_ROOT, cat)
        dst_dir = os.path.join(DST_ROOT, cat)
        os.makedirs(dst_dir, exist_ok=True)
        for name in mp4s(src_dir):
            src = os.path.join(src_dir, name)
            dst = os.path.join(dst_dir, name)
            if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                print(f"跳过（已是最新）: {cat}/{name}")
            else:
                print(f"转码: {cat}/{name}")
                t0 = time.time()
                if encode(ffmpeg, src, dst):
                    print(f"  完成 {os.path.getsize(dst) / 1048576:.1f} MB，用时 {time.time() - t0:.0f}s")
                    new_files.append((cat, name))
                else:
                    print(f"  失败: {cat}/{name}（若提示音频编码问题，源文件可能不是 AAC）")

            poster = os.path.splitext(dst)[0] + ".jpg"
            if os.path.exists(dst) and poster_ffmpeg and (
                    not os.path.exists(poster) or os.path.getmtime(poster) < os.path.getmtime(dst)):
                print("  生成封面...")
                if not make_poster(poster_ffmpeg, dst, poster):
                    print("  封面生成失败")

    manifest = []
    for cat in CATS:
        available = mp4s(os.path.join(DST_ROOT, cat))
        ordered = [e["file"] for e in old
                   if e.get("cat") == cat and e.get("file") in available]
        fresh = [f for f in available if f not in ordered]
        fresh.sort(key=lambda f: (0 if (cat, f) in new_files else 1, f))
        titles = {e["file"]: e.get("title", "") for e in old if e.get("cat") == cat}
        for name in fresh + ordered:
            entry = {
                "title": titles.get(name) or os.path.splitext(name)[0],
                "cat": cat,
                "file": name,
            }
            dur = probe_duration(ffprobe, os.path.join(DST_ROOT, cat, name))
            if dur:
                entry["dur"] = dur
            manifest.append(entry)

    with open(MANIFEST, "w", encoding="utf-8") as fh:
        fh.write("window.VIDEOS = ")
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write(";\n")

    total = sum(os.path.getsize(os.path.join(DST_ROOT, e["cat"], e["file"]))
                for e in manifest)
    print(f"\n清单已生成: {MANIFEST}")
    print(f"共 {len(manifest)} 个作品，合计 {total / 1048576:.1f} MB")


if __name__ == "__main__":
    main()
