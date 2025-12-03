import os, subprocess
from pathlib import Path
from itertools import combinations
from acoustid import fingerprint_file, compare_fingerprints
import sqlite3
from time import sleep
import random

#TO-DO LIST:
# Make a "database" of ads for comparison; include last-detected timestamp. 
# I think a "create table if not exists" sql command would be better

#Pressing issues:
# Stability; more readable naming and output determination
# Weird issue where I test for fp in database twice. 
# Need to make a new function to get around that, probably

RUN_ON_STARTUP = True
WAIT_TIME = 360
EXTRAP_REMOVED_CONTENT = True
#Comparison timing info 
#(recommend Delta is much smaller than Duration):
CMPR_DURATION = 10
CMPR_DELTA = 5
#Similarity thresholds
DESIRED_SIM_THRESHOLD = .9
INITIAL_SIM_THRESHOLD = .5
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
            parent_path=None, 
            start_time=None,
            end_time=None
        ):
        assert type(path) is str 
        assert INPUT_DIR in path or TEMP_DIR in path
        dprint(f"Processing and storing: {path}", 1)
        self.path = path
        self.epname = os.path.basename(os.path.dirname(path))
        self.fp = self.getFp(self.path)
        self.duration, self.fingerprint = self.fp[0], self.fp[1]
        self.subfiles = []
        self.parent_path = parent_path
        self.start_time = start_time
        self.end_time = end_time
    def getFp(self, file_path):
        #NOTE: this function gets a fingerprint from db
        #but also ADDS it to the db
        #if it isn't found. 
        #Fails if no file exists. 
        try: duration_and_fp = getFpfromDb(file_path)
        except: duration_and_fp = addFp(file_path)
        assert type(duration_and_fp) is tuple
        assert len(duration_and_fp) == 2
        return duration_and_fp
    def generateSubFiles(self): #prob needs a better name
        dprint(f"Getting subfiles for {self.path}")
        self.subfiles = splitFile(self)
    def deleteTempFiles(self):
        dprint(f"Deleting temp files.")
        for f in self.subfiles:
            try: os.remove(f.path)
            except: pass
        temp_folder = self.epname
        temp_folder = os.path.join(TEMP_DIR, temp_folder)
        dprint(f"Deleting temp directories.")
        try: os.removedirs(temp_folder)
        except: pass
    def __eq__(self, value):
        assert type(value.fingerprint) is bytes
        assert type(self.fingerprint) is bytes
        return compare_fingerprints(self.fp, value.fp) > INITIAL_SIM_THRESHOLD
    def __str__(self):
        return self.epname
        #old code that I'm keeping around in case it becomes 
        # useful again in the future
        fp = str(self.fingerprint[0:5])
        return f'{self.path:^20}|{self.duration:^8}|{fp:^10}'
    def __repr__(self):
        return self.epname

def getFiles(directory=INPUT_DIR):
    dprint(f"Fetching files in {directory}...")
    mp3_files = []
    def walk(dir):
        for entry in os.listdir(dir):
            full_path = os.path.join(dir, entry)
            # If it's a directory, recurse
            if os.path.isdir(full_path): walk(full_path)
            # If it's an mp3 file, add it
            elif full_path.lower().endswith(".mp3"): mp3_files.append(full_path)
    walk(directory)
    dprint('Beginning import for files:')
    [dprint(f, 1) for f in mp3_files]
    return [audioFile(f) for f in mp3_files]

def getPodcasts(directory=INPUT_DIR):
    print(f"Fetching folders in {directory}...")
    dir = [item for item in os.listdir(directory)]
    full_paths = [os.path.join(directory, item) for item in dir]
    folders = [fldr for fldr in full_paths if os.path.isdir(fldr)]
    print('Podcasts found: ')
    [print(f) for f in folders]
    return folders

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
        for f2 in subfiles_2:
            if f1 == f2: 
                #IF ISSUES, CHECK THAT THIS ISN'T CHECKING INCORRECT FP DATA BC OF DIRECTORIES IN DB
                dprint(f'\nFound match when comparing {f1.epname} to {f2.epname}')
                #There are 4 possible steps to take here:
                # expand f1 left and f2 left
                # expand f1 right and f2 right
                # expand f1 left and f2 right
                # expand f1 right and f2 left
                #These are just different enough that they are not worth abstracting
                #Perform each, and determine if similarity has increased or decreased. 
                p1 = f1.parent_path
                st1 = f1.start_time
                et1 = f1.end_time
                p2 = f2.parent_path
                st2 = f2.start_time
                et2 = f2.end_time
                #NOTE: Must revise this. Not robust to multiple podcast layouts
                pod_name = os.path.basename(os.path.dirname(f1.path))
                output_path = os.path.join(TEMP_DIR, pod_name)
                try: os.mkdir(output_path)
                except: pass
                output_path = os.path.join(output_path, f'{f1.epname}-{f2.epname}-ST_ET.mp3')
                # expand f1 left and f2 left
                current_similarity = compare_fingerprints(f1.fp, f2.fp)
                similarity_increased = True
                while similarity_increased and st1 >= 0:
                    dprint(f'Expanding clips "leftward".', 1)
                    new_st1 = st1 - CMPR_DELTA
                    new_st2 = st2 - CMPR_DELTA
                    new_duration = et1 - st1
                    assert (et1 - st1) == (et2 - st2)
                    f1_path = output_path.replace('ST',str(new_st1)).replace('ET',str(et1))
                    f2_path = output_path.replace('ST',str(new_st2)).replace('ET',str(et2))
                    f1_fp = generateClipandFp(p1, f1_path, new_st1, new_duration)
                    f2_fp = generateClipandFp(p2, f2_path, new_st2, new_duration)
                    new_similarity = compare_fingerprints(f1_fp, f2_fp)
                    similarity_increased = (new_similarity > current_similarity)
                    if similarity_increased: 
                        current_similarity = new_similarity
                        st1 = new_st1
                        st2 = new_st2
                # expand f1 right and f2 right
                similarity_increased = True
                while similarity_increased and et1 <= f1.duration:
                    dprint(f'Expanding clips "rightward".', 1)
                    new_et1 = et1 + CMPR_DELTA
                    new_et2 = et2 + CMPR_DELTA
                    new_duration = new_et1 - st1
                    assert (new_et1 - st1) == (new_et2 - st2)
                    f1_path = output_path.replace('ST',str(st1)).replace('ET',str(new_et1))
                    f2_path = output_path.replace('ST',str(st2)).replace('ET',str(new_et2))
                    f1_fp = generateClipandFp(p1, f1_path, st1, new_duration)
                    f2_fp = generateClipandFp(p2, f2_path, st2, new_duration)
                    new_similarity = compare_fingerprints(f1_fp, f2_fp)
                    similarity_increased = (new_similarity > current_similarity)
                    if similarity_increased:
                        current_similarity = new_similarity
                        et1 = new_et1
                        et2 = new_et2
                # expand f1 left and f2 right
                similarity_increased = True
                while similarity_increased and st1 >= 0 and et2 <= f2.duration:
                    dprint(f'Expanding clips left-and-right.', 1)
                    new_st1 = st1 - CMPR_DELTA
                    new_et2 = et2 + CMPR_DELTA
                    new_duration = et1 - new_st1
                    assert (et1 - new_st1) == (new_et2 - st2)
                    f1_path = output_path.replace('ST',str(new_st1)).replace('ET',str(et1))
                    f2_path = output_path.replace('ST',str(st2)).replace('ET',str(new_et2))
                    f1_fp = generateClipandFp(p1, f1_path, new_st1, new_duration)
                    f2_fp = generateClipandFp(p2, f2_path, st2, new_duration)
                    new_similarity = compare_fingerprints(f1_fp, f2_fp)
                    similarity_increased = (new_similarity > current_similarity)
                    if similarity_increased:
                        current_similarity = new_similarity
                        st1 = new_st1
                        et2 = new_et2
                # expand f1 right and f2 left
                similarity_increased = True
                while similarity_increased and st2 >= 0 and et1 <= f1.duration:
                    dprint(f'Expanding clips "right-and-left".', 1)
                    new_et1 = et1 + CMPR_DELTA
                    new_st2 = st2 - CMPR_DELTA
                    new_duration = new_et1 - st1
                    assert (new_et1 - st1) == (et2 - new_st2)
                    f1_path = output_path.replace('ST',str(st1)).replace('ET',str(new_et1))
                    f2_path = output_path.replace('ST',str(new_st2)).replace('ET',str(et2))
                    f1_fp = generateClipandFp(p1, f1_path, st1, new_duration)
                    f2_fp = generateClipandFp(p2, f2_path, new_st2, new_duration)
                    new_similarity = compare_fingerprints(f1_fp, f2_fp)
                    similarity_increased = (new_similarity > current_similarity)
                    if similarity_increased:
                        current_similarity = new_similarity
                        et1 = new_et1
                        st2 = new_st2
                #We want to return lists of (begin,end) timestamps
                try: cut_these_timestamps[f1.parent_path].append((st1, et1))
                except: cut_these_timestamps[f1.parent_path] = [(st1, et1)]
                try: cut_these_timestamps[f2.parent_path].append((st2, et2))
                except: cut_these_timestamps[f2.parent_path] = [(st2, et2)]
    return cut_these_timestamps

def generateClipandFp(input_path, output_path, start_time, duration) -> tuple:
    assert TEMP_DIR in output_path
    #Tries to find file in database first
    try:
        fp = getFpfromDb(output_path)
    except:
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-ss', str(start_time),
            '-t', str(duration),
            '-i', input_path,
            '-c', 'copy',
            output_path
        ]
        dprint(" ".join(cmd), 1)
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0: #TEMPORARY MEASURE
            print(f"Error removing clips from {input_path}: {result.stderr}")
        fp = addFp(output_path)
    return fp

def removeClips(input_path: str, output_path: str, timestamps: list, includeCuts=True):
    assert type(timestamps) is list
    for s in timestamps: assert type(s) is tuple
    output_path = output_path.replace("’","")
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
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0: #TEMPORARY MEASURE
        print(f"Error removing clips from {input_path}: {result.stderr}")
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
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print(f"Error removing clips from {input_path}: {result.stderr}")

def splitFile(audio_file):
    #make a folder for the file, to store subfiles in
    temp_folder = audio_file.path.replace(INPUT_DIR, TEMP_DIR)
    temp_folder = os.path.dirname(temp_folder)
    if not os.path.exists(temp_folder): os.makedirs(temp_folder, exist_ok=True)
    subfiles = []
    current_time = 0
    p = audio_file.path #path of "parent" audio file
    while current_time + CMPR_DURATION*2 <= audio_file.duration:
        #store start time and end time in subfile
        st = current_time
        et = current_time + CMPR_DURATION
        snippet_title = f"{audio_file.epname}_snippet_{current_time}"
        snippet_path = os.path.join(temp_folder, f"{snippet_title}.mp3")
        dprint(f"Getting snippet: {snippet_path}", 1)
        generateClipandFp(p, snippet_path, current_time, CMPR_DURATION)
        subfiles.append(audioFile(snippet_path, p, st, et))
        current_time += CMPR_DELTA
    return subfiles

def createFpDatabase():
    #create the table if it doesn't already exist
    print("Checking for database...", )
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

def getFpfromDb(path):
    res = fp_db_cur.execute(f"""
        SELECT duration, fingerprint FROM fingerprints 
        WHERE path=?
        """, (path,))
    result = res.fetchone()
    if not result: raise Exception
    else: return result

#This design choice assumes we will
#never make a fingerprint that we don't store.
def addFp(path):
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

def filesChanged(directory=INPUT_DIR): 
    #Simple, last-minute way to 
    #prevent running unless a new file is present
    #FIX THIS
    text_file = os.path.join(directory, "file_list.txt")
    if not os.path.exists(text_file): return True
    folders = os.listdir(directory)
    folders = [os.path.join(directory, f) for f in folders]
    all_files = []
    for folder in folders:
        if os.path.isdir(folder):
            files = os.listdir(folder)
            files = [os.path.join(folder, f) for f in files]
            all_files.extend(files)
        else:
            all_files.append(folder)
    all_files_str = "\n".join(all_files)
    with open(text_file, "r") as f:
        old_filelist = f.read()
    if old_filelist != all_files_str:
        with open(text_file, "w") as f:
            f.write(all_files_str)
    return old_filelist != all_files_str

def main():
    #create the table if it doesn't already exist
    createFpDatabase()
    #now get the files and parse/store their fingerprint data
    podcasts = getPodcasts()
    random.shuffle(podcasts)
    #place already-processed podcasts at the end of the list
    def podcastProcessed(podcast):
        eps_exist = []
        for ep_name in os.listdir(podcast):
            if not os.path.isdir(os.path.join(podcast, ep_name)): continue
            pod_name = os.path.basename(podcast)
            filename = os.path.join(OUTPUT_DIR, pod_name.replace("’",""), ep_name + ".mp3")
            eps_exist.append(os.path.exists(filename))
        return all(eps_exist)
    podcasts.sort(key=podcastProcessed)
    for podcast in podcasts:
        files = getFiles(podcast)
        assert all([type(f) is audioFile for f in files])
        print(f"Now getting subfile fp's for each episode in {podcast}...")
        for f in files: f.generateSubFiles()
        #now perform comparisons between each two subfiles:
        removable_timestamps = {} #parent_file_path:[(0,10),(50,60),(11,21)]
        pairs = combinations(files, 2)
        print(f"Pairs: {[p for p in combinations(files, 2)]}")
        for f1, f2 in pairs:
            print(f"Comparing {f1} to {f2}")
            timestamps = compareSubfiles(f1, f2)
            assert type(timestamps) is dict and all([type(value) is list for _, value in timestamps.items()])
            for _, l in timestamps.items(): assert all([len(s) == 2 for s in l])
            #put our compareSubfiles results into total removable_timestamps results
            for filepath, cut_segments in timestamps.items():
                try: removable_timestamps[filepath].extend(cut_segments)
                except: removable_timestamps[filepath] = cut_segments
        for f in files: f.deleteTempFiles()
        #now remove the selected clips
        for path, timestamps in removable_timestamps.items():
            #Eventually I'll make this less janky
            ep_name = os.path.basename(os.path.dirname(path))
            pod_name = os.path.basename(os.path.dirname(os.path.dirname(path)))
            filename = os.path.join(pod_name, ep_name) + ".mp3"
            output = os.path.join(OUTPUT_DIR,filename)
            os.makedirs(os.path.join(OUTPUT_DIR, pod_name.replace("’","")), exist_ok=True)
            #Only output if a file doesn't already exist
            if not os.path.exists(output):
                removeClips(path, output, timestamps)
        fp_db.commit()
    fp_db.close()

def dprint(print_str: str, indents: int=0):
    indent = "    "*indents + "- " if indents != 0 else ""
    if __debug__: print(f"{indent}{print_str}")

if __name__ == '__main__':
    #I put these run conditions outside of main() 
    #just for modularity going forward (since this probably won't be permanent)
    while True:
        if filesChanged() or RUN_ON_STARTUP: 
            print("Starting main loop. ")
            main()
        RUN_ON_STARTUP = False
        print(f"Now sleeping until new files are detected...")
        sleep(WAIT_TIME)