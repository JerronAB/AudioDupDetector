from podDB import ensureDatabase
import podops
from pathlib import Path
from ffmpeg import removeClips

### TO DO:
# Ensure files are temporary

#Directory names
ROOT = Path.cwd()
INPUT_DIR = ROOT/'assets'
OUTPUT_DIR = ROOT/'complete'
DB = INPUT_DIR/'fingerprints.db'
print(f'Input directory: {INPUT_DIR}')
print(f'Output directory: {OUTPUT_DIR}')

if __name__ == "__main__":
    fp_db, fp_cursor = ensureDatabase(DB)
    podcasts = podops.getPodcasts(INPUT_DIR,OUTPUT_DIR)
    print(podcasts)
    for p in podcasts:
        print("Analyzing episodes of: ", p.name)
        print("Testing combinations: ",p.episode_pairs)
        i = len(p.episode_pairs)
        for f1, f2 in p.episode_pairs:
            print(f"{i} pairs left...")
            podops.findDuplicateAudio(fp_cursor, f1, f2)
            i -= 1
        for f in p.episodes: f.cleanTimestamps()
        for f in p.episodes: print("Timestamps to remove: ",f.duplicate_timestamps)
        #now remove extra content:
        for ep in p.episodes:
            output_path = str(OUTPUT_DIR/p.name/ep.name) + '.mp3'
            removeClips(str(ep.audio_file), ep.duplicate_timestamps, str(output_path))
