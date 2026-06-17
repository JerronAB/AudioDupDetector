from __future__ import annotations #so we can typehint "episode"
from tempfile import TemporaryDirectory
from acoustid import fingerprint_file
import subprocess
from pathlib import Path
ROOT = Path.cwd()
TEMP_DIR = Path('/dev/shm/')/'temp'

#Trick from stackoverflow:
# You still need to import the module for the static type checker,
# but you can do it behind a TYPE_CHECKING guard so it's ignored at runtime.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from podops import episode  # Only seen by IDE/Mypy, ignored at runtime

def createSnippetFile(file: episode, start_time: int, end_time: int):
    start_time = max(start_time,0)
    end_time = min(end_time, file.duration())
    dir = str(TEMP_DIR/file.name)
    duration = end_time - start_time
    snippet_file = f"{dir}_snippet_{start_time}:{end_time}.mp3"
    #print(f"Exporting file: {snippet_file}")
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-ss', str(start_time),
        '-t', str(duration),
        '-i', str(file.audio_file),
        '-c', 'copy',
        snippet_file
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    dur, fp = fingerprint_file(snippet_file)
    return ((dur,fp), snippet_file)

def deleteSnippetFile(filename: str):
    file = Path(filename)
    file.unlink(missing_ok=False)

def removeClips(input_path: str, timestamps: list, output_path: str):
    for s in timestamps: assert type(s) is tuple
    assert isinstance(output_path, str)
    output_path = output_path.replace("’","")
    #ensure directory for podcast exists:
    outfile = Path(output_path)
    outfile.parent.mkdir(parents=True,exist_ok=True)
    if outfile.exists():
        print(f"File already present; not exporting {output_path}")
        return
    #max() here is a quickfix for the fact that sometimes 
    #timestamps go negative because of the way acoustid 
    #calculates fingerprints and similarity
    bt_strings = [f'between(t\\,{max(start,0)}\\,{end})' for start, end in timestamps]
    bt_string = '+'.join(bt_strings)
    filter_expr = f"aselect=not({bt_string})"
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', input_path,
        '-af', filter_expr, 
        output_path
    ]
    print(" ".join(cmd))
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print(res.stdout)
    print(res.stderr)

    output_path = output_path.replace(".mp3", " ADS.mp3")
    bt_strings = [f'between(t\\,{start}\\,{end})' for start, end in timestamps]
    bt_string = '+'.join(bt_strings)
    filter_expr = f"aselect={bt_string}"
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', input_path,
        '-af', filter_expr, 
        output_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print(res.stdout)
    print(res.stderr)
    