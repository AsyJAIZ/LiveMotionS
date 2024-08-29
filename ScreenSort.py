import argparse, logging, os, sys, progressbar
from exiftool import ExifToolHelper as exifh
import shutil
from exiftool.exceptions import ExifToolExecuteError as ExecuteError

comm = 'UserComment'
exif = f'ExifIFD:{comm}'
xmp = f'XMP-exif:{comm}'

def process_file(file):
	rel_file = os.path.relpath(file, workingDir)
	try:
		tags = list(get_tags(file)[0].values())[1:]
	except ExecuteError as exc:
		logging.error(f'{rel_file} is a corrupted file. Moving to a different directory.\a')
		cor = os.path.join(os.path.dirname(file), "..", "corruptedScreenshots_" + os.path.basename(os.path.dirname(file)))
		if os.path.exists(cor):
			if not os.path.isdir(cor):
				logging.error(f"Is a file: {cor}. Skipping...")
				return
		else:
			os.mkdir(cor)
		os.rename(file, os.path.join(cor, os.path.basename(rel_file)))
		return
	try:
		comment = tags[0]
	except IndexError:
		return

	screenshot_current = os.path.abspath(os.path.join(screenshotsDir, os.path.dirname(os.path.relpath(file, workingDir))))
	if os.path.exists(screenshot_current):
		if not os.path.isdir(screenshot_current):
			logging.error(f"Location is a file: {screenshot_current}. No changes were made.\a")
			return
	else:
		os.makedirs(screenshot_current, exist_ok=True)
	shutil.move(file, screenshot_current)

def count_files_in_directory():
	file_count = 0
	for _, _, files in os.walk(workingDir):
		file_count += len(files)
	return file_count

def scan_dir(rec=False):
	bar = progressbar.ProgressBar(prefix='Scanning: ', widgets=widgets)
	try:
		if rec:
			bar.max_value = count_files_in_directory()
			for root, _, files in os.walk(workingDir):
				for name in files:
					file = os.path.join(root, name)
					if check_file(file):
						process_file(file)
					bar.increment()
			bar.finish()
		else:
			for name in bar(os.listdir(workingDir)):
				file = os.path.join(workingDir, name)
				if not os.path.isfile(file):
					logging.info('Found a directory: ' + file)
					continue
				if check_file(file):
					process_file(file)
		print("Done.")
	except KeyboardInterrupt:
		print("Interrupted!")
		return

def get_tags(file):
	return et.get_tags(file, [exif, xmp])

def check_file(*files):
	for file in files:
		if not os.path.exists(file) or not file.lower().endswith(('.png', '.jpg')):
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

		global widgets
		widgets = [progressbar.widgets.SimpleProgress(), ', ', progressbar.widgets.Percentage(), ' ', progressbar.widgets.GranularBar(), ' ', progressbar.widgets.AdaptiveTransferSpeed(), ', ', progressbar.widgets.SmoothingETA()]
		
		global workingDir
		workingDir = os.path.abspath(args.directory)
		global screenshotsDir
		screenshotsDir = os.path.join(outDir, "screenshots_" + os.path.basename(workingDir))
		scan_dir(args.recursive)
		exit()
	else:
		logging.error('Need --dir. Abort')
		exit(1)

if __name__ == '__main__':
	parser = argparse.ArgumentParser(
		description='Moves screenshots to another folder')
	parser.add_argument('-d', '--directory', '--dir', help='A directory to read from')
	parser.add_argument('-r', '--recursive', '--re', help='Read from subdirectories', action='store_true')
	parser.add_argument('-o', '--output', '--out', help='A directory to write to')
	parser.add_argument('-v', '--verbose', '--ver', action='count')
	main(parser.parse_args())

