from PIL import Image
from PIL import ImageChops
from PIL import ImageFile # maybe fixes truncation error
from collections import deque
import os
import numpy as np
import time
import signal
import subprocess
import requests
import threading
import sys
import shutil
from config import *
from datetime import datetime

ImageFile.LOAD_TRUNCATED_IMAGES = True

testing = False 

FRAME_DIR = 'frames'
FFMPEG = "%ffmpeg%" if sys.platform == 'win32' else 'ffmpeg'
CMD = f'{FFMPEG} -hide_banner -loglevel error -y -i {STREAM_URL} -vf fps=1 {FRAME_DIR}/frame%05d.jpg'


if testing:
	discord_hook_url = TEST_HOOK_URL
else:
	discord_hook_url = PRODUCTION_DISCORD_HOOK_URL

class MotionDetector():
	def __init__(self):
		self.LOG_FILE = 'detector.log'
		self.ims = deque(maxlen = 2)
		self.diff = None
		self.scale = 2
		self.threshhold = 50
		self.delay = 5
		self.min_diff = 0.02
		self.max_diff = 1 if testing else 0.5
		self.last_created = None
		self.frame_count = 1
		self.recording = False
		self.remote = threading.Event()

	def log(self, msg):
		with open(self.LOG_FILE, 'a') as f:
			f.write(f'{msg}\t{datetime.now()}\n')

	def process_and_grab_img(self):
		path = self.get_frame()
		full_path = os.path.join(FRAME_DIR,path)
		im = Image.open(full_path)
		im = self.rescale(im)
		os.remove(full_path)
		self.frame_count += 1
		return im

	def get_frame(self):
		while True:
			path = self.check_if_new_frame()
			if path:
				print(path)
				return path
			else:
				print("***SLEEPING****")
				time.sleep(0.5)

	def end_stream(self):
		os.killpg(os.getpgid(self.pro.pid), signal.SIGTERM)

	def check_if_new_frame(self):
		f = [i for i in os.scandir(FRAME_DIR) if i.name == f'frame{self.frame_count:05d}.jpg']
		if not f:
			return
		return f[0].name

	def open_im(self,path):
		return Image.open(path)

	def rescale(self,im):
		w,h = im.size
		scaled = im.resize((w//self.scale,h//self.scale))
		return scaled

	def img_diff(self,a,b):
		return ImageChops.difference(a,b)

	def thresh(self,arr):
		mask = arr < self.threshhold
		arr[mask] = 0
		return Image.fromarray(arr)

	def get_array(self,im):
		return np.array(im)

	def get_next_im(self):
		self.ims.append(self.process_and_grab_img())

	def get_diff(self):
		self.diff = self.img_diff(self.ims[0].convert("L"),self.ims[1].convert("L"))
		return self.diff

	def total_changed(self,arr):
		#a = np.array(diff)
		return np.sum(arr > 0)/arr.size

	def _record_stream(self,stream_url, outname="out_vid", secs=10, framerate=30):
		self.recording = True
		outpath = f'{outname}.mp4'
		cmd = f"{FFMPEG} -hide_banner -loglevel error -y -i {stream_url} -r {framerate} -t {secs} {outpath}"
		os.system(cmd)
		post_file_to_discord(outpath)
		self.recording = False

	def record_stream(self):
		t = threading.Thread(target = self._record_stream, args = (STREAM_URL, 'out_vid', 60))
		t.start()

	def grab_frames(self):
		t = threading.Thread(target = self._grab_frames)
		t.start()

	def _grab_frames(self):
		self.grabbing_frames = True 
		#self.pro = subprocess.Popen(CMD, stdout=subprocess.PIPE, shell=True) #preexec_fn=os.setsid)
		try:
			self.pro = subprocess.check_call(CMD, shell = True)

		except subprocess.CalledProcessError:
			self.log("restarting ffmpeg frame grabber")			
			self.grabbing_frames = False

	def restart(self):
		print('setting frame count to zero')
		print('launching ffmpeg')
		self.frame_count = 1
		if os.path.exists(FRAME_DIR):
			shutil.rmtree(FRAME_DIR)
		os.makedirs(FRAME_DIR)
		self.grab_frames()

	def run(self):
		#self.tasks = get_process()
		self.restart()
		#print(self.pro.pid)
		time.sleep(1)
		#self.new = set(get_process()) - set(self.tasks)
		#print(self.new)
		while True:
			print(f'capturing image {self.frame_count}')
			try:
				self.get_next_im()
				if len(self.ims) < 2:
					continue
				diff = self.get_diff()
				arr = self.get_array(diff)
				diff_cleaned = self.thresh(arr)
				change = self.total_changed(arr)
				print(f'percent change in img: {change:.2%}')
				if self.max_diff > change > self.min_diff:
					#diff.show()
					self.ims[1].save("full_color.jpg")
					if not self.recording:
						print('starting recording')
						post_file_to_discord("full_color.jpg")
						self.record_stream()
				if not self.grabbing_frames:
					self.restart()
			except KeyboardInterrupt:
				#self.end_stream()
				break

def get_process():
    pass
    #dosen't work with linux
    #proc = subprocess.Popen('tasklist', stdout=subprocess.PIPE)
    #return [i.split()[0] for i in proc.stdout.readlines()[1:]]

def post_to_discord(link):
	data = {'content':link}
	requests.post(discord_hook_url, json = data)

def post_file_to_discord(path, msg="bird spotted?"):
    payload = {"content":msg, "username":"ulla"}
    with open(path, 'rb') as f:
        multipart = {"file":(f.name, f, "application/octet-stream")}
        resp = requests.post(discord_hook_url, files=multipart, data=payload)
    return resp

if __name__ == "__main__":
    Mo = MotionDetector()
    Mo.run()
