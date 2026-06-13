from acoustid import fingerprint_file, compare_fingerprints
from itertools import combinations
import os, subprocess
import sqlite3
import random
from json import dumps, loads

#TO-DO LIST:
# Make a "database" of ads for comparison; include last-detected timestamp. 

EXTRAP_REMOVED_CONTENT = True #Not yet implemented
#Comparison timing info 
CMPR_DURATION = 10
CMPR_DELTA = 5
#Similarity thresholds
MIN_SIM_THRESHOLD = .5
#Directory names
ROOT = os.getcwd()
INPUT_DIR = os.path.join(ROOT, 'assets')
TEMP_DIR = os.path.join(ROOT, 'temp')
OUTPUT_DIR = os.path.join(ROOT, 'complete')
DB = os.path.join(INPUT_DIR, 'fingerprints.db')
print(f'Input directory: {INPUT_DIR}')
print(f'Temp directory: {TEMP_DIR}')
print(f'Output directory: {OUTPUT_DIR}')

class audioFile():
    def __init__(
            self, 
            path: str, 
        ):
        dprint(f"Processing and storing: {path}", 1)
        assert type(path) is str 
        assert INPUT_DIR in path or TEMP_DIR in path
        self.path = path
        self.epname, self.podname = getNames(path)
        self.subfiles_processed = False
        self.setFp()
    def setFp(self):
        #look before leap on getting fingerprint
        fp = getFpfromDb(self.path)
        if fp is not None: self.fp = fp
        else: self.fp = addFpFromFile(self.path)
        self.duration, self.fingerprint = self.fp[0], self.fp[1]
    def getSubfiles(self):
        print(f"Getting subfiles for {self.epname}")
        if self.subfiles_processed: return
        self.subfiles = []
        temp_folder = self.path.replace(INPUT_DIR, TEMP_DIR)
        temp_folder = os.path.dirname(temp_folder)
        if not os.path.exists(temp_folder): os.makedirs(temp_folder, exist_ok=True)
        current_time = 0
        parent_path = self.path
        while current_time + CMPR_DELTA <= self.duration:
            #store start time and end time in subfile
            st = current_time
            et = current_time + CMPR_DURATION
            snippet_title = f"{self.epname}_snippet_{st}:{et}.mp3"
            snippet_path = os.path.join(temp_folder, snippet_title)
            dprint(f"Getting snippet: {snippet_path}", 1)
            self.subfiles.append(subFile(parent_path, snippet_path, st, et))
            current_time += CMPR_DELTA
        self.subfiles_processed = True
    def getExportPath(self):
        full_filepath = os.path.join(self.podname, self.epname) + ".mp3"
        full_filepath = os.path.join(TEMP_DIR,full_filepath)
        return full_filepath.replace("’","")
    def __eq__(self, value):
        assert type(value.fingerprint) is bytes
        assert type(self.fingerprint) is bytes
        return compare_fingerprints(self.fp, value.fp) > MIN_SIM_THRESHOLD
    def __repr__(self):
        return self.epname
    def __str__(self):
        return self.epname

class subFile(audioFile):
    def __init__(self, parent_path, subfile_path, start_time, end_time):
        self.parent_path = parent_path
        self.start_time = start_time
        self.end_time = end_time
        super().__init__(subfile_path)
    def setFp(self):
        fp = getFpfromDb(self.path)
        if fp is not None:
            self.fp = fp
        else:
            dprint("Attempted to get fingerprint for file: ")
            dprint(self.path)
            dprint("Failed, now trying to create clip from scratch... ")
            self.fp = self.getClip()
        self.duration, self.fingerprint = self.fp[0], self.fp[1]
    def getClip(self):
        input_path = self.parent_path
        start_time = self.start_time
        duration = self.end_time - self.start_time
        temp_folder = self.path.replace(INPUT_DIR, TEMP_DIR)
        temp_folder = os.path.dirname(temp_folder)
        if not os.path.exists(temp_folder): os.makedirs(temp_folder, exist_ok=True)
        #output_path = f"{self.epname}_snippet_{start_time}:{self.end_time}.mp3"
        #output_path = os.path.join(temp_folder, output_path)
        assert TEMP_DIR in self.path
        #Tries to find file in database first
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-ss', str(start_time),
            '-t', str(duration),
            '-i', input_path,
            '-c', 'copy',
            self.path
            #output_path
        ]
        dprint(" ".join(cmd), 1)
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        dprint("Adding fingerprint for file: ")
        dprint(self.path)
        fp = addFpFromFile(self.path)
        os.remove(self.path)
        return fp

def getFpfromDb(path):
    res = fp_db_cur.execute(f"""
        SELECT duration, fingerprint FROM fingerprints 
        WHERE path=?
        """, (path,))
    result = res.fetchone()
    return result

def addFpFromFile(path):
    dprint(f"Fingerprinting file: {path}", 1)
    fp = fingerprint_file(path)
    if not fp or not fp[0] or not fp[1]: 
        raise Exception(f"File:{path}\nDuration:{fp[0]}\nFp:{fp[1]}")
    dprint(f"Adding fp to database...", 1)
    fp_db_cur.execute(f"""
        INSERT INTO fingerprints VALUES
        (?, ?, ?)
    """, (path, fp[0], fp[1]))
    fp_db.commit()
    return fp

def getNames(filepath) -> tuple[str, str]:
    assert type(filepath) is str
    episode_name = os.path.basename(os.path.dirname(filepath))
    podcast_title = os.path.basename(os.path.dirname(os.path.dirname(filepath)))
    return (episode_name, podcast_title)

def ensureDatabase():
    #create the table if it doesn't already exist
    print("Checking for databases...", )
    global fp_db
    global fp_db_cur
    fp_db = sqlite3.connect(DB)
    fp_db_cur = fp_db.cursor()
    res = fp_db_cur.execute("SELECT name FROM sqlite_master")
    if not res.fetchone(): #is None if table doesn't exist
        print("No database found. Creating new table...")
        fp_db.execute("""
        CREATE TABLE fingerprints (
        path TEXT PRIMARY KEY, 
        duration REAL, 
        fingerprint BLOB
        )""")
        fp_db.commit()
        fp_db.execute("""
        CREATE TABLE comparisons (
        files TEXT PRIMARY KEY, 
        timestamps TEXT
        )""")
        fp_db.commit()

def getPodcasts(directory=INPUT_DIR) -> list[str]:
    print(f"Fetching folders in {directory}...")
    dir = [item for item in os.listdir(directory)]
    full_paths = [os.path.join(directory, item) for item in dir]
    folders = [fldr for fldr in full_paths if os.path.isdir(fldr)]
    print('Podcasts found: ')
    [print(f) for f in folders]
    return folders

#Used to place already-processed podcasts
#at the end of our list
def podcastProcessed(podcast):
        eps_exist = []
        for ep_name in os.listdir(podcast):
            if not os.path.isdir(os.path.join(podcast, ep_name)): continue
            pod_name = os.path.basename(podcast)
            filename = os.path.join(OUTPUT_DIR, pod_name.replace("’",""), ep_name + ".mp3")
            episode_exists = os.path.exists(filename)
            eps_exist.append(episode_exists)
        return all(eps_exist)

def getFiles(directory=INPUT_DIR) -> list[str]:
    dprint(f"Fetching files in {directory}...")
    mp3_files = []
    def walk(dir):
        for entry in os.listdir(dir):
            full_path = os.path.join(dir, entry)
            #If it's a directory, recurse
            if os.path.isdir(full_path): walk(full_path)
            #If it's an mp3 file, add it
            elif full_path.lower().endswith(".mp3"): mp3_files.append(full_path)
    walk(directory)
    return mp3_files

def getExpandedClips(f1: subFile, f2: subFile):
    p1 = f1.parent_path
    st1 = f1.start_time
    et1 = f1.end_time
    p2 = f2.parent_path
    st2 = f2.start_time
    et2 = f2.end_time
    output_path = f1.getExportPath()
    try: os.mkdir(output_path)
    except: pass
    current_similarity = compare_fingerprints(f1.fp, f2.fp)
    output_path = os.path.join(output_path, f'{f1.epname}-{f2.epname}-ST:ET.mp3')
    def expandClipsLeft(st1_, st2_, et1_, et2_, current_similarity):
        similarity_increased = True
        while similarity_increased and st1_ >= 0:
            dprint(f'Expanding clips "leftward".', 1)
            new_st1 = st1_ - CMPR_DELTA
            new_st2 = st2_ - CMPR_DELTA
            assert (et1_ - st1_) == (et2_ - st2_)
            f1_path = output_path.replace('ST',str(new_st1)).replace('ET',str(et1_))
            f2_path = output_path.replace('ST',str(new_st2)).replace('ET',str(et2_))
            f1_fp = subFile(p1, f1_path, new_st1, et1_).fp
            f2_fp = subFile(p2, f2_path, new_st2, et2_).fp
            try: new_similarity = compare_fingerprints(f1_fp, f2_fp)
            except: new_similarity = 0
            similarity_increased = (new_similarity > current_similarity)
            if similarity_increased: 
                current_similarity = new_similarity
                st1_ = new_st1
                st2_ = new_st2
        return (st1_, st2_, current_similarity)
    def expandClipsRight(st1_, st2_, et1_, et2_, current_similarity):
        similarity_increased = True
        while similarity_increased and et1_ <= f1.duration:
            dprint(f'Expanding clips "rightward".', 1)
            new_et1 = et1_ + CMPR_DELTA
            new_et2 = et2_ + CMPR_DELTA
            assert (new_et1 - st1_) == (new_et2 - st2_)
            f1_path = output_path.replace('ST',str(st1_)).replace('ET',str(new_et1))
            f2_path = output_path.replace('ST',str(st2_)).replace('ET',str(new_et2))
            f1_fp = subFile(p1, f1_path, st1_, new_et1).fp
            f2_fp = subFile(p2, f2_path, st2_, new_et2).fp
            try: new_similarity = compare_fingerprints(f1_fp, f2_fp)
            except: new_similarity = 0
            similarity_increased = (new_similarity > current_similarity)
            if similarity_increased:
                current_similarity = new_similarity
                et1_ = new_et1
                et2_ = new_et2
        return (et1_, et2_, current_similarity)
    def expandClipsLeftRight(st1_, st2_, et1_, et2_, current_similarity):
        similarity_increased = True
        while similarity_increased and st1_ >= 0 and et2_ <= f2.duration:
            dprint(f'Expanding clips left-and-right.', 1)
            new_st1 = st1_ - CMPR_DELTA
            new_et2 = et2_ + CMPR_DELTA
            assert (et1_ - new_st1) == (new_et2 - st2_)
            f1_path = output_path.replace('ST',str(new_st1)).replace('ET',str(et1_))
            f2_path = output_path.replace('ST',str(st2_)).replace('ET',str(new_et2))
            f1_fp = subFile(p1, f1_path, new_st1, et1_).fp
            f2_fp = subFile(p2, f2_path, st2_, new_et2).fp
            try: new_similarity = compare_fingerprints(f1_fp, f2_fp)
            except: new_similarity = 0
            similarity_increased = (new_similarity > current_similarity)
            if similarity_increased:
                current_similarity = new_similarity
                st1_ = new_st1
                et2_ = new_et2
        return (st1_, et2_, current_similarity)
    def expandClipsRightLeft(st1_, st2_, et1_, et2_, current_similarity):
        similarity_increased = True
        while similarity_increased and st2_ >= 0 and et1_ <= f1.duration:
            dprint(f'Expanding clips "right-and-left".', 1)
            new_et1 = et1_ + CMPR_DELTA
            new_st2 = st2_ - CMPR_DELTA
            assert (new_et1 - st1_) == (et2_ - new_st2)
            f1_path = output_path.replace('ST',str(st1_)).replace('ET',str(new_et1))
            f2_path = output_path.replace('ST',str(new_st2)).replace('ET',str(et2_))
            f1_fp = subFile(p1, f1_path, st1_, new_et1).fp
            f2_fp = subFile(p2, f2_path, new_st2, et2_).fp
            try: new_similarity = compare_fingerprints(f1_fp, f2_fp)
            except: new_similarity = 0
            similarity_increased = (new_similarity > current_similarity)
            if similarity_increased:
                current_similarity = new_similarity
                et1_ = new_et1
                st2_ = new_st2
        return (et1_, st2_, current_similarity)
    st1, st2, current_similarity = expandClipsLeft(st1, st2, et1, et2, current_similarity)
    et1, et2, current_similarity = expandClipsRight(st1, st2, et1, et2, current_similarity)
    st1, et2, current_similarity = expandClipsLeftRight(st1, st2, et1, et2, current_similarity)
    et1, st2, current_similarity = expandClipsRightLeft(st1, st2, et1, et2, current_similarity)
    return (st1, et1, st2, et2)

def compareSubfiles(audio_1, audio_2):
    #This architecture would have an extreme benefit
    #from using a near-neighbor search on fingerprints. 
    #Then, all entries are simply checked against existing entries, 
    #and a function is run when a match is detected
    assert type(audio_1) is audioFile and type(audio_2) is audioFile
    dprint(f"Comparing {audio_1.path} to {audio_2.path}...")
    cut_these_timestamps = {}
    subfiles_1 = audio_1.subfiles
    subfiles_2 = audio_2.subfiles
    for f1 in subfiles_1:
        dprint(f"Comparing clip {f1.path} ({audio_1.duration} total) to all clips in {audio_2.epname}...")
        for f2 in subfiles_2:
            assert type(f1) is subFile and type(f2) is subFile
            #Check if comparison is already in DB, and return if so
            #This helps for quick-resuming on interruptions
            comparison_key = [f1.path, f2.path]
            comparison_key.sort()
            res = fp_db_cur.execute(f"""
                SELECT timestamps FROM comparisons 
                WHERE files=?
                """, ("".join(comparison_key),)
            )
            result = res.fetchone()
            if result: 
                st1, et1, st2, et2 = loads(result[0])
                try: cut_these_timestamps[f1.parent_path].append((st1, et1))
                except: cut_these_timestamps[f1.parent_path] = [(st1, et1)]
                try: cut_these_timestamps[f2.parent_path].append((st2, et2))
                except: cut_these_timestamps[f2.parent_path] = [(st2, et2)]
            elif f1 == f2:
                dprint(f'\nFound match when comparing {f1.epname} to {f2.epname}')
                st1, et1, st2, et2 = getExpandedClips(f1, f2)
                fp_db_cur.execute(f"""
                    INSERT INTO comparisons VALUES
                    (?, ?)
                """, ("".join(comparison_key), dumps([st1, et1, st2, et2])))
                #We want to return lists of (begin,end) timestamps
                try: cut_these_timestamps[f1.parent_path].append((st1, et1))
                except: cut_these_timestamps[f1.parent_path] = [(st1, et1)]
                try: cut_these_timestamps[f2.parent_path].append((st2, et2))
                except: cut_these_timestamps[f2.parent_path] = [(st2, et2)]
    return cut_these_timestamps

def removeClips(input_path: str, output_path: str, timestamps: list, includeCuts=EXTRAP_REMOVED_CONTENT):
    assert type(timestamps) is list
    for s in timestamps: assert type(s) is tuple
    output_path = output_path.replace("’","")
    def mergeIntervals(intervals):
        #Sort timestamps by start time
        intervals.sort(key=lambda x: x[0])
        merged = [intervals[0]]
        for current in intervals[1:]:
            last_start, last_end = merged[-1]
            curr_start, curr_end = current
            if curr_start <= last_end:
                #Overlap found; update the end of the last tuple
                merged[-1] = (last_start, max(last_end, curr_end))
            else:
                #No overlap; add the new tuple
                merged.append(current)
        return merged
    timestamps = mergeIntervals(timestamps)
    bt_strings = [f'between(t\\,{start}\\,{end})' for start, end in timestamps]
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
    if includeCuts:
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
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

def main():
    podcasts = getPodcasts()
    random.shuffle(podcasts)
    podcasts.sort(key=podcastProcessed)
    for podcast in podcasts:
        mp3_files = getFiles(podcast)
        files = [audioFile(file) for file in mp3_files]
        random.shuffle(files)
        pairs = combinations(files, 2)
        print(f"Pairs: {[p for p in combinations(files, 2)]}")
        removable_timestamps = {} #parent_file_path:[(0,10),(50,60),(11,21)]
        #now perform comparisons between each two subfiles:
        for f1, f2 in pairs:
            f1.getSubfiles()
            f2.getSubfiles()
            print(f"Comparing {f1} to {f2}")
            #check if the timestamp results are already in DB
            comparison_key = [f1.path, f2.path]
            comparison_key.sort()
            res = fp_db_cur.execute(f"""
                SELECT timestamps FROM comparisons 
                WHERE files=?
                """, ("".join(comparison_key),)
            )
            result = res.fetchone()
            if result: 
                timestamps = loads(result[0])
            else:
                timestamps = compareSubfiles(f1, f2)
                fp_db_cur.execute(f"""
                    INSERT INTO comparisons VALUES
                    (?, ?)
                """, ("".join(comparison_key), dumps(timestamps)))
            #put our compareSubfiles results into total removable_timestamps results
            for filepath, cut_segments in timestamps.items():
                try: removable_timestamps[filepath].extend(cut_segments)
                except: removable_timestamps[filepath] = cut_segments
        #now remove the selected clips
        for path, timestamps in removable_timestamps.items():
            ep_name, pod_name = getNames(path)
            podcast_path = os.path.join(OUTPUT_DIR, pod_name.replace("’",""))
            output = os.path.join(podcast_path, ep_name) + ".mp3"
            os.makedirs(podcast_path, exist_ok=True)
            #Only output if a file doesn't already exist
            if not os.path.exists(output):
                removeClips(path, output, timestamps)
        fp_db.commit()
    fp_db.close()

def dprint(print_str: str, indents: int=0):
    indent = "    "*indents + "- " if indents != 0 else ""
    if __debug__: print(f"{indent}{print_str}")

if __name__ == '__main__':
    ensureDatabase()
    main()