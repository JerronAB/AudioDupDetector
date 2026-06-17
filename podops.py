from acoustid import fingerprint_file, compare_fingerprints
from random import shuffle
from pathlib import Path
from itertools import combinations
from podDB import selectComparison, selectFingerprint, insertFingerprint, insertComparison
#NOTE: I need to make sure I'm inserting comparisons and fps into the db where I should
#ADDITIONALLY I want to implement separate select funcs for comapisons and fps
from ffmpeg import createSnippetFile, deleteSnippetFile

CMPR_DELTA = 5
CMPR_DURATION = 10
MIN_SIM_THRESHOLD = 0.5

#May want this to just be a dataclass
class podcast():
    def __init__(self, pod_dir: Path):
        self.name = pod_dir.name
        self.episode_folders = [
            f
            for f in pod_dir.iterdir() 
            if f.is_dir()
        ]
        self.episodes = [episode(f) for f in self.episode_folders]
        self.episode_pairs = [p for p in combinations(self.episodes, 2)]
    def __hash__(self):
        return hash(self.name)

class episode():
    def __init__(self, ep_input_folder: Path):
        self.name = ep_input_folder.name
        self.abs_path = str(ep_input_folder.absolute())
        self.audio_file = next(ep_input_folder.glob("*.mp3"))
        self.duplicate_timestamps = []
        self.subfile_ids = []
        self.subfile_fps = []
        self.subfile_durs = []
        self.subfile_times = []
        self.duration_ = None
    def __hash__(self):
        return hash(self.abs_path)
    def __repr__(self):
        return self.name
    def addDuplicateTimestamps(self, timestamp_pairs: list):
        assert isinstance(timestamp_pairs, list)
        assert all([len(t) == 2 for t in timestamp_pairs])
        self.duplicate_timestamps.extend(timestamp_pairs)
    def cleanTimestamps(self):
        #Sort timestamps by start time
        self.duplicate_timestamps.sort(key=lambda x: x[0])
        merged = [self.duplicate_timestamps[0]]
        for current in self.duplicate_timestamps[1:]:
            last_start, last_end = merged[-1]
            curr_start, curr_end = current
            if curr_start <= last_end:
                #Overlap found; update the end of the last tuple
                merged[-1] = (last_start, max(last_end, curr_end))
            else:
                #No overlap; add the new tuple
                merged.append(current)
        self.duplicate_timestamps = merged
    def duration(self):
        if self.duration_: return self.duration_
        self.duration_, _ = fingerprint_file(self.audio_file.absolute())
        return self.duration_

def findDuplicateAudio(db_cursor, f1: episode, f2: episode):
    #Test if these have already been compared:
    cmpr_list = [f1, f2]
    cmpr_list.sort(key=lambda x: x.abs_path)
    cmpr_key = "->".join([c.abs_path for c in cmpr_list])
    print(f"Primary key for comparison: {cmpr_key}")
    timestamps_1, timestamps_2 = selectComparison(db_cursor, cmpr_key)
    if timestamps_1:
        #timestamps were inserted in sorted order
        print(f"Results from db: {timestamps_1} {timestamps_2}")
        cmpr_list[0].addDuplicateTimestamps(timestamps_1)
        cmpr_list[1].addDuplicateTimestamps(timestamps_2)
    else: 
        #Note there is a flaw here. Because addDupTimestamps always adds
        #we will be including timestamps from multiple different comparisons
        #in the database. 
        #I don't *think* that's a problem for now
        compareAllSubfiles(db_cursor, f1, f2)
        insertComparison(db_cursor, cmpr_key, (cmpr_list[0].duplicate_timestamps, cmpr_list[1].duplicate_timestamps))

def compareAllSubfiles(db_cursor, f1: episode, f2: episode) -> dict[podcast, list]:
    #This only runs if we don't have a comparison
    #for these two files in the DB
    #So, we get fingerprints from snippets 
    # (check episode object first, then DB, then ffmpeg if necessary)
    #and compare fingerprints from there
    print(f"Now comparing subfiles {f1.name} -> {f2.name}...")
    for file in (f1, f2):
        print(f"Getting subfiles for file: {file.name}")
        if file.subfile_fps: continue
        current_time = 0
        while current_time + CMPR_DELTA <= file.duration():
            #may be causing issues by not cutting et to 
            #always be less than the duration of the 
            #audio; check on this later
            st = current_time
            et = current_time + CMPR_DURATION if current_time < file.duration_ else file.duration_
            snippet_id = f"{file.abs_path}_snippet_{st}:{et}.mp3"
            snippet_fp = selectFingerprint(db_cursor,snippet_id)
            if not snippet_fp:
                snippet_fp, fname = createSnippetFile(file, st, et)
                insertFingerprint(db_cursor, snippet_id, snippet_fp)
                deleteSnippetFile(fname)
            file.subfile_ids.append(snippet_id)
            file.subfile_fps.append(snippet_fp)
            file.subfile_times.append((st, et))
            current_time += CMPR_DELTA
    #Now f1 and f2 both have fingerprints
    #Storing results in DB is NOT necessary here
    i = 0
    for s1_id, s1_fp, s1_ts in zip(f1.subfile_ids,f1.subfile_fps,f1.subfile_times):
        if (i % 100) == 0: print(f"Comparing {f1.name} subfile {i}/{len(f1.subfile_ids)} to all subfiles from {f2.name}...")
        i += 1
        for s2_id, s2_fp, s2_ts in zip(f2.subfile_ids,f2.subfile_fps,f2.subfile_times):
            similarity = compare_fingerprints(s1_fp,s2_fp)
            if similarity > MIN_SIM_THRESHOLD:
                s1_start, s1_end = s1_ts
                s2_start, s2_end = s2_ts
                s1_start, s1_end, s2_start, s2_end = getExpandedClips(db_cursor, f1, f2, similarity, s1_start, s1_end, s2_start, s2_end)
                f1.addDuplicateTimestamps([(s1_start, s1_end)])
                f2.addDuplicateTimestamps([(s2_start, s2_end)])
    print(f"Finished comparing {f1.name} to {f2.name}...")

def getExpandedClips(
        db_cursor,
        f1: episode,
        f2: episode,
        curr_similarity: float,
        s1_st: int,
        s1_et: int,
        s2_st: int,
        s2_et: int,
    ):
    def expandClipsLeft(s1_st_, s2_st_, s1_et_, s2_et_, curr_similarity):
        similarity_increased = True
        while similarity_increased and s1_st_ >= 0:
            print(f'Expanding clips "leftward"...',end=" ")
            new_s1_st = s1_st_ - CMPR_DELTA
            new_s2_st = s2_st_ - CMPR_DELTA
            assert (s1_et_ - s1_st_) == (s2_et_ - s2_st_)
            snippet_id = f"{f1.abs_path}_snippet_{new_s1_st}:{s1_et_}.mp3"
            f1_fp = selectFingerprint(db_cursor,snippet_id)
            if not f1_fp:
                f1_fp, fname = createSnippetFile(f1,new_s1_st,s1_et_)
                insertFingerprint(db_cursor, snippet_id, f1_fp)
                deleteSnippetFile(fname)
            snippet_id = f"{f2.abs_path}_snippet_{new_s2_st}:{s2_et_}.mp3"
            f2_fp = selectFingerprint(db_cursor,snippet_id)
            if not f2_fp:
                f2_fp, fname = createSnippetFile(f2,new_s2_st,s2_et_)
                insertFingerprint(db_cursor, snippet_id, f1_fp)
                deleteSnippetFile(fname)
            try: new_similarity = compare_fingerprints(f1_fp, f2_fp)
            except: new_similarity = 0
            similarity_increased = (new_similarity > curr_similarity)
            if similarity_increased: 
                curr_similarity = new_similarity
                s1_st_ = new_s1_st
                s2_st_ = new_s2_st
        return (s1_st_, s2_st_, curr_similarity)
    def expandClipsRight(s1_st_, s2_st_, s1_et_, s2_et_, curr_similarity):
        similarity_increased = True
        while similarity_increased and s1_et_ <= f1.duration_:
            print(f'Expanding clips "rightward"...',end=" ")
            new_s1_et = s1_et_ + CMPR_DELTA
            new_s2_et = s2_et_ + CMPR_DELTA
            assert (new_s1_et - s1_st_) == (new_s2_et - s2_st_)
            snippet_id = f"{f1.abs_path}_snippet_{s1_st_}:{new_s1_et}.mp3"
            f1_fp = selectFingerprint(db_cursor,snippet_id)
            if not f1_fp:
                f1_fp, fname = createSnippetFile(f1, s1_st_, new_s1_et)
                insertFingerprint(db_cursor, snippet_id, f1_fp)
                deleteSnippetFile(fname)
            snippet_id = f"{f2.abs_path}_snippet_{s2_st_}:{new_s2_et}.mp3"
            f2_fp = selectFingerprint(db_cursor,snippet_id)
            if not f2_fp:
                f2_fp, fname = createSnippetFile(f2, s2_st_, new_s2_et)
                insertFingerprint(db_cursor, snippet_id, f2_fp)
                deleteSnippetFile(fname)
            try: new_similarity = compare_fingerprints(f1_fp, f2_fp)
            except: new_similarity = 0
            similarity_increased = (new_similarity > curr_similarity)
            if similarity_increased:
                curr_similarity = new_similarity
                s1_et_ = new_s1_et
                s2_et_ = new_s2_et
        return (s1_et_, s2_et_, curr_similarity)
    def expandClipsLeftRight(s1_st_, s2_st_, s1_et_, s2_et_, curr_similarity):
        similarity_increased = True
        while similarity_increased and s1_st_ >= 0 and s2_et_ <= f2.duration_:
            print(f'Expanding clips left-and-right...',end=" ")
            new_s1_st = s1_st_ - CMPR_DELTA
            new_s2_et = s2_et_ + CMPR_DELTA
            assert (s1_et_ - new_s1_st) == (new_s2_et - s2_st_)
            snippet_id = f"{f1.abs_path}_snippet_{new_s1_st}:{s1_et_}.mp3"
            f1_fp = selectFingerprint(db_cursor, snippet_id)
            if not f1_fp:
                f1_fp, fname = createSnippetFile(f1, new_s1_st, s1_et_)
                insertFingerprint(db_cursor, snippet_id, f1_fp)
                deleteSnippetFile(fname)
            snippet_id = f"{f1.abs_path}_snippet_{s2_st_}:{new_s2_et}.mp3"
            f2_fp = selectFingerprint(db_cursor, snippet_id)
            if not f2_fp:
                f2_fp, fname = createSnippetFile(f2, s2_st_, new_s2_et)
                insertFingerprint(db_cursor, snippet_id, f2_fp)
                deleteSnippetFile(f2)
            try: new_similarity = compare_fingerprints(f1_fp, f2_fp)
            except: new_similarity = 0
            similarity_increased = (new_similarity > curr_similarity)
            if similarity_increased:
                curr_similarity = new_similarity
                s1_st_ = new_s1_st
                s2_et_ = new_s2_et
        return (s1_st_, s2_et_, curr_similarity)
    def expandClipsRightLeft(s1_st_, s2_st_, s1_et_, s2_et_, curr_similarity):
        similarity_increased = True
        while similarity_increased and s2_st_ >= 0 and s1_et_ <= f1.duration_:
            print(f'Expanding clips "right-and-left"...')
            new_s1_et = s1_et_ + CMPR_DELTA
            new_s2_st = s2_st_ - CMPR_DELTA
            assert (new_s1_et - s1_st_) == (s2_et_ - new_s2_st)
            snippet_id = f"{f1.abs_path}_snippet_{s1_st_}:{new_s1_et}.mp3"
            f1_fp = selectFingerprint(db_cursor, snippet_id)
            if not f1_fp:
                f1_fp, fname = createSnippetFile(f1, s1_st_, new_s1_et)
                insertFingerprint(db_cursor, snippet_id, f1_fp)
                deleteSnippetFile(fname)
            snippet_id = f"{f1.abs_path}_snippet_{new_s2_st}:{s2_et_}.mp3"
            f2_fp = selectFingerprint(db_cursor, snippet_id)
            if not f2_fp:
                f2_fp, fname = createSnippetFile(f2, new_s2_st, s2_et_)
                insertFingerprint(db_cursor, snippet_id, f2_fp)
                deleteSnippetFile(fname)
            try: new_similarity = compare_fingerprints(f1_fp, f2_fp)
            except: new_similarity = 0
            similarity_increased = (new_similarity > curr_similarity)
            if similarity_increased:
                curr_similarity = new_similarity
                s1_et_ = new_s1_et
                s2_st_ = new_s2_st
        return (s1_et_, s2_st_, curr_similarity)
    s1_st, s2_st, curr_similarity = expandClipsLeft(s1_st, s2_st, s1_et, s2_et, curr_similarity)
    s1_et, s2_et, curr_similarity = expandClipsRight(s1_st, s2_st, s1_et, s2_et, curr_similarity)
    s1_st, s2_et, curr_similarity = expandClipsLeftRight(s1_st, s2_st, s1_et, s2_et, curr_similarity)
    s1_et, s2_st, curr_similarity = expandClipsRightLeft(s1_st, s2_st, s1_et, s2_et, curr_similarity)
    return (s1_st, s1_et, s2_st, s2_et)

def getPodcasts(input_dir: Path, output_dir: Path) -> list[podcast]:
    def podcastNeedsProcessed(p: podcast):
        podcast_name = p.name.replace("'","")
        folders = p.episode_folders
        for ep in folders:
            if not ep.is_dir(): continue
            #Create the expected mp3 path
            expected_filename = output_dir / podcast_name / f"{ep.name}.mp3"
            if not expected_filename.exists(): return True
        return False
    podcast_list = [
        podcast(f)
        for f in input_dir.iterdir()
        if f.is_dir()
    ]
    podcast_list = [
        p
        for p in podcast_list 
        if podcastNeedsProcessed(p)
    ]
    #Now we have our list of podcast objects
    shuffle(podcast_list)
    return podcast_list