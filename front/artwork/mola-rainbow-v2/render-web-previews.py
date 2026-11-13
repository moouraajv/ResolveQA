"""Deterministic web previews from the exact validated atlas (no generated artwork)."""
from pathlib import Path
from PIL import Image, ImageDraw
import subprocess
ROOT = Path(__file__).resolve().parent
SPECS = [('idle',6,179),('running-right',8,174),('running-left',8,174),('waving',4,174),('jumping',5,201),('failed',8,175),('waiting',6,175),('running',6,175),('review',6,173)]
OUT = ROOT/'qa/previews';OUT.mkdir(parents=True,exist_ok=True)
atlas = Image.open(ROOT/'final/atlas.png').convert('RGBA')
def canvas(row,frame,label=True):
 state,count,ground=SPECS[row]
 # Keep exact 192x208 cell pixels; align resting feet as the web runtime does.
 im=Image.new('RGB',(256,256),'#faf6ef')
 sprite=atlas.crop((frame*192,row*208,(frame+1)*192,(row+1)*208))
 im.paste(sprite,(32,220-ground),sprite)
 d=ImageDraw.Draw(im)
 d.line((16,221,240,221),fill='#d9d2c7')
 if label:d.text((12,12),f'{state} / {frame+1:02}',fill='#292b3a')
 return im
allframes=[canvas(row,i) for row,(_,n,_) in enumerate(SPECS) for i in range(n)]
def save(frames,name,durations=120):
 frames[0].save(OUT/name,save_all=True,append_images=frames[1:],duration=durations,loop=0,disposal=2)
save(allframes,'all-states.gif')
transition=[canvas(0,i) for i in range(6)]+[canvas(4,i) for i in range(5)]+[canvas(0,i) for i in range(6)]
save(transition,'idle-jump-idle.gif',140)
for index,(row,frame) in enumerate([(0,0),(1,3),(4,2),(5,4)]):canvas(row,frame).save(OUT/f'still-{index+1:02}.png')
subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(OUT/'all-states.gif'),'-pix_fmt','yuv420p','-movflags','+faststart',str(OUT/'all-states.mp4')],check=True)
print('Previews generated from final/atlas.png; 9 states, GIF+MP4, idle-jump-idle, 4 stills.')
