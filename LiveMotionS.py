import argparse, logging, sqlite3, os, sys, progressbar, time
from exiftool import ExifToolHelper as exifh
#from exiftool import ExifTool as exift
from datetime import datetime
import shutil
from exiftool.exceptions import ExifToolExecuteError as ExecuteError
#etr = exift()

heicUUID = "Apple:ContentIdentifier" if os.name != 'nt' else 'MakerNotes:ContentIdentifier'


def merge_files(image, video):
	return False # sorry not yet supported
	try:
		i_t = get_tags(image)
		v_t = get_tags(video)
	except ExecuteError:
		return False
	try:
		if i_t[0][heicUUID] != v_t[0]["Keys:ContentIdentifier"]:
			logging.warning("IDs do not match")
		i_t = list(i_t[0].values())[1:]
		v_t = list(v_t[0].values())[1:]
	except KeyError:
		logging.warning("In one of the files there's no ID")
	
	

def append_mpvd_to_heic(heic_file, video_file, video_size):
	logging.info(f"Appending {os.path.relpath(video_file, workingDir)} to {os.path.relpath(heic_file, outDir)}.")
	box_size = 8 + video_size
	box_type = b'mpvd'
	mpvd_box = box_size.to_bytes(4, 'big') + box_type
	with open(heic_file, 'ab') as p, open(video_file, 'rb') as v:
		p.write(mpvd_box)
		p.write(v.read())

def process_db(cur, db):
	xmp = "XMP-"
	gcam = xmp + "GCamera"
	gcont = xmp + "GContainer"

	cur.execute('SELECT COUNT(*) FROM pair')
	total = cur.fetchone()[0]
	bar = progressbar.ProgressBar(prefix='Processing: ', max_value=total, widgets=widgets)

	cur.execute("SELECT COUNT(*) FROM pair WHERE done = ?", (True,))
	done = cur.fetchone()[0]
	logging.info(f"Processed file count: {done}, total file count: {total}")
	bar.update(done)
	limit = 100

	count = 0
	photo_path = None
	video_path = None
	timestamp = None
	out_path = None
	
	print("Processing the database. Press CTRL-C in 5 seconds in order to cancel.")
	time.sleep(5)

	while True:
		cur.execute("SELECT * FROM pair WHERE done = ? AND p_path IS NOT NULL AND v_path IS NOT NULL LIMIT ?", (False, limit))
		rows = cur.fetchall()
		if not rows: break
		for row in rows:
			_, photo_path, video_path, timestamp, out_path, _ = row
			if not os.path.exists(photo_path) or not os.path.exists(video_path):
				logging.error(f"Either {os.path.relpath(photo_path, outDir)} or {os.path.relpath(video_path, workingDir)} doesn't exist. Skipping.\a")
				continue
			os.makedirs(os.path.dirname(out_path), exist_ok=True)
			if os.path.exists(out_path):
				logging.error(f"{os.path.relpath(out_path, outDir)} ({os.path.relpath(photo_path, workingDir)}) already exists! Count is {count}. Rewriting cuz done flag is unset.\a")
			shutil.copy2(photo_path, out_path)
			video_size = os.path.getsize(video_path)
			tags = {f"{gcam}:MotionPhoto":"1", f"{gcam}:MotionPhotoVersion":"1", f"{gcam}:MotionPhotoPresentationTimestampUs":timestamp,
				f"{gcont}:ContainerDirectory":"[{Item={Length=0,Mime=image/heic,Padding=8,Semantic=Primary}},{Item={Length=" + str(video_size) + ",Mime=video/quicktime,Padding=0,Semantic=MotionPhoto}}]"}
			#logging.info(f"Setting these tags to {os.path.relpath(out_path, outDir)}: {str(tags)}")
			et.set_tags(out_path, tags, "-overwrite_original_in_place")
			append_mpvd_to_heic(out_path, video_path, video_size)
			cur.execute("UPDATE pair SET done = ? WHERE out_path = ?", (True, out_path))
			if move:
				orig_dir = os.path.join(outDir, "..", "originals_" + os.path.basename(workingDir))
				newpath_dir = os.path.abspath(os.path.join(orig_dir, os.path.dirname(os.path.relpath(photo_path, workingDir))))
				if os.path.exists(newpath_dir):
					if not os.path.isdir(newpath_dir):
						logging.error(f"Location is a file: {newpath_dir}. No changes were made.\a")
						continue
				else:
					os.makedirs(newpath_dir, exist_ok=True)
				logging.info(f'Moving originals to {newpath_dir}')
				shutil.move(photo_path, newpath_dir)
				shutil.move(video_path, newpath_dir)
			bar.increment()
			++count
		db.commit()
	bar.finish(dirty=True)
	if total>(done+count):
		logging.warning("The list of unmerged files is in the database.")
	print("Done.")

def process_file(file, cur):
	rel_file = os.path.relpath(file, workingDir)
	try:
		tags = get_tags(file)
	except ExecuteError as exc:
		logging.error(f'{rel_file} is a corrupted file. Moving to a different directory.\a')
		cor = os.path.join(os.path.dirname(file), "..", "corrupted_" + os.path.basename(os.path.dirname(file)))
		if os.path.exists(cor):
			if not os.path.isdir(cor):
				logging.error(f"Is a file: {cor}. Skipping...")
				return
		else:
			os.mkdir(cor)
		os.rename(file, os.path.join(cor, os.path.basename(rel_file)))
		return
	try:
		uuid = tags[0]["Keys:ContentIdentifier" if file.lower().endswith('.mov') else heicUUID]
	except KeyError:
		return
		
	tags = list(tags[0].values())[1:]
	if not file.lower().endswith('.mov'):
		dt = datetime.strptime(tags[1], "%Y:%m:%d %H:%M:%S")
		basename = dt.strftime("IMG%Y%m%d_%H%M%S")
		duplic = (cur.execute('SELECT COUNT(*) FROM pair WHERE out_path LIKE ? AND id != ?', ("%" + basename + "%", uuid))).fetchone()[0]
		count = f"_{duplic}" if duplic != 0 else ""
		ext = os.path.basename(file).split('.')[-1]
		newname = f"{basename}{count}MP.{ext}"
		outname = os.path.join(outDir, os.path.dirname(rel_file), newname)
	else:
		try:
			dur = round(min(tags[1:]) * 1000000)
		except KeyError:
			logging.info(f"Did not find a timestamp in {rel_file}. Treating as undefined.")
			dur = -1
			
	cur.execute('SELECT * FROM pair WHERE id = ?', (uuid,))
	row = cur.fetchone()
	if row:
		if file.lower().endswith('.mov'):
			if row[2] == file and row[3] == dur:
				return
			cur.execute('''
			UPDATE pair
			SET v_path = ?, timestamp = ?, done = ?
			WHERE id = ?
			''', (file, dur, False, uuid))
		else:
			if row[1] == file and row[4] == outname:
				return
			cur.execute('''
                        UPDATE pair
                        SET p_path = ?, out_path = ?, done = ?
                        WHERE id = ?
                        ''', (file, outname, False, uuid))
		logging.info(f'Updated row with id {row[0]}.')
	else:
		if file.lower().endswith('.mov'):
			cur.execute('''
			INSERT INTO pair(id, v_path, timestamp, done)
			VALUES(?, ?, ?, ?)
			''', (uuid, file, dur, False))
		else:
			cur.execute('''
			INSERT INTO pair(id, p_path, out_path, done)
                        VALUES(?, ?, ?, ?)
                        ''', (uuid, file, outname, False))

def count_files_in_directory():
	file_count = 0
	for _, _, files in os.walk(workingDir):
		file_count += len(files)
	return file_count

def scan_dir(cur, rec=False):
	bar = progressbar.ProgressBar(prefix='Scanning: ', widgets=widgets)
	try:
		if rec:
			bar.max_value = count_files_in_directory()
			for root, _, files in os.walk(workingDir):
				for name in files:
					file = os.path.join(root, name)
					if check_file(file):
						process_file(file, cur)
					bar.increment()
			bar.finish()
		else:
			for name in bar(os.listdir(workingDir)):
				file = os.path.join(workingDir, name)
				if not os.path.isfile(file):
					logging.info('Found a directory: ' + file)
					continue
				if check_file(file):
					process_file(file, cur)
	except KeyboardInterrupt:
		print("Interrupted! Saving database to disk.")
		return

def get_tags(file):
	if file.lower().endswith('.mov'):
		return et.get_tags(file, ['ContentIdentifier', 'Track5:TrackDuration', 'Track4:TrackDuration', 'Track3:TrackDuration'])
	else:
		return et.get_tags(file, [heicUUID, 'DateTimeOriginal'])

def check_file(*files):
	for file in files:
		if not os.path.exists(file) or not file.lower().endswith(('.mov', '.heic')):
			return False
	return True

def main(args):
	progressbar.streams.wrap_stderr()
	progressbar.streams.wrap_stdout()
	log = logging.INFO if args.verbose else logging.ERROR
	logging.basicConfig(level=log, stream=sys.stdout, format="%(message)s")
	logging.info("Verbose mode")
	logging.info(f"Runs on: {os.name}")
	global et
	logger = logging.getLogger(__name__) if log is logging.DEBUG else None
	et = exifh(common_args=['-G1', '-n'], logger=logger)
	et.run()
	ver = 12.46
	if ver > float(et.version):
		logging.critical(f"Update ExifTool to version {ver} to support iOS 17.0")

	global outDir
	outDir = os.path.abspath(args.output) if args.output is not None else os.path.abspath("output")
	logging.info(f'Output path is {outDir}')

	if args.directory is not None:
		if not os.path.exists(args.directory):
			logging.error("--dir doesn't exist.")
			exit(1)
		if not os.path.isdir(args.directory):
			logging.error('--dir is not a directory.')
			exit(1)

		database = sqlite3.connect(os.path.abspath(args.database) if args.database is not None else os.path.join(args.directory, 'photos.db'))
		cur = database.cursor()
		check = cur.execute("SELECT name FROM sqlite_master WHERE name='pair'")
		global move
		move = args.move
		global widgets
		widgets = [progressbar.widgets.SimpleProgress(), ', ', progressbar.widgets.Percentage(), ' ', progressbar.widgets.GranularBar(), ' ', progressbar.widgets.AdaptiveTransferSpeed(), ', ', progressbar.widgets.SmoothingETA()]
		
		global workingDir
		workingDir = os.path.abspath(args.directory)
		if check.fetchone() is None or args.overwrite:
			logging.info('Creating a database.')
			cur.execute("DROP TABLE IF EXISTS pair")
			cur.execute("CREATE TABLE pair(id, p_path, v_path, timestamp, out_path, done)")
		else:
			if not args.dry_run:
				process_db(cur, database)
				exit()

		scan_dir(cur, args.recursive)
		database.commit()
		if not args.dry_run:
			process_db(cur, database)
			exit()
		else:
			exit()

	else:
		if args.image is None or args.video is None:
			logging.error('Need --dir or both --img and --mov. Abort')
			exit(1)
		else:
			if not (check_file(args.image, args.video) and merge_files(args.image, args.video)):
				logging.error("Can't check provided files. Exiting")
				exit(1)

if __name__ == '__main__':
	parser = argparse.ArgumentParser(
		description='Gathers information about photos/videos into a database and merges Apple Live Photos into Google Motion Photos')
	parser.add_argument('-n', '--dry-run', '--dry', help='Scan directory only', action='store_true')
	parser.add_argument('-b', '--database', '--db', help='Specify a database path')
	parser.add_argument('-w', '--overwrite', '--ovrw', help="If the database already exists, suppress prompts and overwrite the database. If not specified, update it", action='store_true')
	parser.add_argument('-d', '--directory', '--dir', help='A directory to read from. Overrides --img and --mov')
	parser.add_argument('-r', '--recursive', '--re', help='Read from subdirectories', action='store_true')
	parser.add_argument('-c', '--move', '--cd', help='Move original files to different directory to separate', action='store_true')
	parser.add_argument('-i', '--image', '--img', help='Used in pair with --video')
	parser.add_argument('-m', '--video', '--mov')
	parser.add_argument('-o', '--output', '--out', help='A directory to write to')
	parser.add_argument('-v', '--verbose', '--ver', action='count')
	main(parser.parse_args())

