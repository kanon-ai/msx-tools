"""Deterministic image -> TMS9918A SCREEN 2 / project V9968 4bpp converter."""
from __future__ import annotations
import argparse,base64,hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps,ImageFilter

# TMS9918A nominal RGB approximation. Physical composite/RGB output varies.
TMS=np.array([(0,0,0),(0,0,0),(33,200,66),(94,220,120),(84,85,237),
 (125,118,252),(212,82,77),(66,235,245),(252,85,84),(255,121,120),
 (212,193,84),(230,206,128),(33,176,59),(201,91,186),(204,204,204),(255,255,255)],dtype=np.uint8)
CHANNEL=np.array([.30,.59,.11],dtype=np.float32)

def rgb5(palette):return np.rint(np.asarray(palette,dtype=float)*31/255).astype(np.uint8)
def expand5(palette):return np.rint(np.asarray(palette,dtype=float)*255/31).astype(np.uint8)
def png(im):
 b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()
def indexed(indices,palette):
 im=Image.fromarray(np.asarray(indices,dtype=np.uint8),'P')
 flat=np.asarray(palette,dtype=np.uint8).flatten().tolist();im.putpalette(flat+[0]*(768-len(flat)))
 return im

def prepare(source,options):
 w,h=int(options.get('width',256)),int(options.get('height',192))
 mode=options.get('mode','tms9918a')
 if mode not in ('tms9918a','v9968'):raise ValueError('対応形式を選択してください。')
 if not 8<=w<=1024 or not 8<=h<=4096 or w*h>1048576:raise ValueError('寸法は幅8〜1024、高さ8〜4096、合計1048576画素以内です。')
 if mode=='tms9918a' and (w%8 or h%8):raise ValueError('TMS9918Aの幅・高さは8の倍数にしてください。')
 if mode=='v9968' and w%2:raise ValueError('4bpp画像の幅は偶数にしてください。')
 im=ImageOps.exif_transpose(source).convert('RGBA')
 background=Image.new('RGBA',im.size,(0,0,0,255));background.alpha_composite(im);im=background.convert('RGB')
 resample={'nearest':Image.Resampling.NEAREST,'box':Image.Resampling.BOX,'lanczos':Image.Resampling.LANCZOS}.get(options.get('resample','box'))
 if resample is None:raise ValueError('縮小方式が不正です。')
 fit=options.get('fit','contain')
 if fit=='contain':
  im=ImageOps.contain(im,(w,h),resample);canvas=Image.new('RGB',(w,h));canvas.paste(im,((w-im.width)//2,(h-im.height)//2));im=canvas
 elif fit=='crop':im=ImageOps.fit(im,(w,h),resample)
 elif fit=='stretch':im=im.resize((w,h),resample)
 else:raise ValueError('配置方法が不正です。')
 sharp=float(options.get('sharpen',0))
 if not 0<=sharp<=150:raise ValueError('輪郭強調は0〜150です。')
 if sharp:im=im.filter(ImageFilter.UnsharpMask(radius=.7,percent=int(sharp),threshold=3))
 return im

def weights(rgb,strength):
 if not 0<=strength<=4:raise ValueError('輪郭優先度は0〜4です。')
 a=np.asarray(rgb,dtype=np.float32)
 lum=a@CHANNEL
 dx=np.zeros_like(lum);dy=dx.copy()
 dx[:,1:]=np.abs(np.diff(lum,axis=1));dy[1:]=np.abs(np.diff(lum,axis=0))
 return 1+strength*np.maximum(dx,dy)/255

def pcg_from_indices(indices,palette):
 a=np.asarray(indices,dtype=np.uint8);h,w=a.shape;p=bytearray();c=bytearray()
 for ty in range(0,h,8):
  for tx in range(0,w,8):
   for y in range(ty,ty+8):
    row=a[y,tx:tx+8];colors=np.unique(row)
    if len(colors)>2:raise ValueError('PCGの横8ドット2色制約に違反しています。')
    bg=int(colors[0]);fg=int(colors[-1]);n=0
    for value in row:n=(n<<1)|int(value==fg)
    p.append(n);c.append(fg*16+bg)
 return bytes(p),bytes(c)

def decode_pcg(patterns,colors,w,h):
 if len(patterns)!=w*h//8 or len(colors)!=len(patterns):raise ValueError('PCGデータ長が不正です。')
 a=np.zeros((h,w),np.uint8)
 for t in range(w*h//64):
  tx=t%(w//8)*8;ty=t//(w//8)*8
  for y in range(8):
   v=colors[t*8+y]
   for x in range(8):a[ty+y,tx+x]=v>>4 if patterns[t*8+y]&(128>>x) else v&15
 return a

def screen2_viewer(patterns,colors,names):
 """16 KiB plain ROM, using the external machine BIOS for SCREEN 2 upload."""
 code=bytearray.fromhex('F33100F33E02CD5F00')
 for source,dest,length in [(0x4080,0,6144),(0x5880,0x2000,6144),(0x7080,0x1800,768),(0x7380,0x1b00,1)]:
  code+=b'\x21'+source.to_bytes(2,'little')+b'\x11'+dest.to_bytes(2,'little')+b'\x01'+length.to_bytes(2,'little')+bytes.fromhex('CD5C00')
 code+=bytes.fromhex('F33E01D3993E87D399FB7618FD')
 assert len(code)<=112
 return (b'AB\x10\x40'+bytes(12)+code).ljust(128,b'\xff')+patterns+colors+names+b'\xd0'+bytes([255])*(16384-128-6144-6144-768-1)

def tms_convert(im,options):
 allowed=sorted(set(int(v) for v in options.get('allowed_colors',range(1,16))))
 if not allowed or any(v<1 or v>15 for v in allowed):raise ValueError('TMSの使用色は1〜15から1色以上選んでください。色0は透明扱いのため除外します。')
 a=np.asarray(im,dtype=np.float32);h,w=a.shape[:2]
 weight=weights(a,float(options.get('edge',1)))
 # Work in batches to bound memory even for tall maps.
 rows=a.reshape(h,w//8,8,3).reshape(-1,8,3)
 wr=weight.reshape(-1,8);result=np.empty((len(rows),8),np.uint8)
 pair_a=[];pair_b=[]
 for i,x in enumerate(allowed):
  for y in allowed[i:]:pair_a.append(x);pair_b.append(y)
 pa=np.array(pair_a);pb=np.array(pair_b)
 naive_violations=0
 for start in range(0,len(rows),256):
  batch=rows[start:start+256]
  distance=(((batch[:,:,None,:]-TMS[None,None,:,:])**2)*CHANNEL).sum(axis=3)
  naive=np.array(allowed)[distance[:,:,allowed].argmin(axis=2)]
  naive_violations+=sum(len(np.unique(row))>2 for row in naive)
  score=(np.minimum(distance[:,:,pa],distance[:,:,pb])*wr[start:start+len(batch),:,None]).sum(axis=1)
  best=score.argmin(axis=1);lo=pa[best];hi=pb[best]
  d0=np.take_along_axis(distance,lo[:,None,None].repeat(8,axis=1),axis=2)[:,:,0]
  d1=np.take_along_axis(distance,hi[:,None,None].repeat(8,axis=1),axis=2)[:,:,0]
  result[start:start+len(batch)]=np.where(d1<d0,hi[:,None],lo[:,None])
 indices=result.reshape(h,w)
 p,c=pcg_from_indices(indices,TMS)
 assert np.array_equal(indices,decode_pcg(p,c,w,h))
 files={'patterns.bin':p,'colors.bin':c}
 if (w,h)==(256,192):
  names=bytes(range(256))*3
  vram=bytearray(16384);vram[:6144]=p;vram[0x1800:0x1b00]=names;vram[0x2000:0x3800]=c;vram[0x1b00]=208
  files.update({'names.bin':names,'vram.bin':bytes(vram),'image.sc2':bytes.fromhex('FE0000FF3F0000')+vram,'preview-msx1.rom':screen2_viewer(p,c,names)})
 report={'tiles':w*h//64,'pattern_bytes':len(p),'color_bytes':len(c),'naive_rows_exceeding_2_colors':int(naive_violations),'encoded_rows_exceeding_2_colors':0,'allowed_palette_indices':allowed,'full_screen2_vram_export':(w,h)==(256,192)}
 return indexed(indices,TMS),files,report

def nearest(rgb,palette):
 a=np.asarray(rgb,dtype=np.float32).reshape(-1,3);out=np.empty(len(a),np.uint8)
 for start in range(0,len(a),8192):
  d=(((a[start:start+8192,None,:]-palette[None,:,:])**2)*CHANNEL).sum(axis=2);out[start:start+8192]=d.argmin(axis=1)
 return out

def v9968_convert(im,options):
 fixed=options.get('palette_rgb5')
 a=np.asarray(im,dtype=np.float32)
 if fixed is not None:
  p5=np.asarray(fixed)
  if p5.shape!=(16,3) or not np.all(p5==np.floor(p5)) or np.any(p5<0) or np.any(p5>31):raise ValueError('固定パレットは0〜31の整数による16組のRGB値です。')
  p5=p5.astype(np.uint8);palette=expand5(p5)
 else:
  initial=im.quantize(colors=16,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
  raw=initial.getpalette()[:48];raw+=([0]*(48-len(raw)))
  palette=np.array(raw,np.uint8).reshape(16,3)
  # Deterministic Lloyd refinement. Snap every center to the actual RGB555 grid.
  flat=a.reshape(-1,3);weighted=weights(a,float(options.get('edge',1))).reshape(-1)
  step=max(1,len(flat)//65536);sample=flat[::step];wt=weighted[::step]
  preserve=options.get('preserve_highlights',True)
  extremes=[]
  if preserve:
   lum=sample@CHANNEL;cut=max(1,len(sample)//500);order=np.argsort(lum)
   extremes=[expand5(rgb5(sample[order[:cut]].mean(axis=0))),expand5(rgb5(sample[order[-cut:]].mean(axis=0)))]
  for _ in range(8):
   if preserve:palette[:2]=extremes
   palette=expand5(rgb5(palette));labels=nearest(sample,palette)
   updated=palette.astype(np.float32)
   for k in range(16):
    mask=labels==k
    if mask.any():updated[k]=np.average(sample[mask],axis=0,weights=wt[mask])
   refined=expand5(rgb5(updated))
   if preserve:refined[:2]=extremes
   # RGB555 rounding can merge centers: spend spare colors on the largest error.
   seen=set()
   for k in range(16):
    key=tuple(refined[k])
    if key in seen:
     existing=np.array(list(seen),dtype=np.float32)
     lab=nearest(sample,existing)
     error=(((sample-existing[lab])**2)*CHANNEL).sum(axis=1)*wt
     candidate=expand5(rgb5(sample[int(error.argmax())]))
     if tuple(candidate) not in seen:refined[k]=candidate;key=tuple(candidate)
    seen.add(key)
   if np.array_equal(refined,palette):break
   palette=refined
  p5=rgb5(palette);palette=expand5(p5)
 indices=nearest(a,palette).reshape(im.height,im.width)
 flat=indices.flatten();packed=((flat[::2]<<4)|flat[1::2]).tobytes()
 check=np.empty(len(flat),np.uint8);data=np.frombuffer(packed,np.uint8);check[::2]=data>>4;check[1::2]=data&15
 assert np.array_equal(flat,check)
 files={'pixels-4bpp.bin':packed,'palette-rgb5.bin':p5.tobytes(),'palette.json':json.dumps({'rgb5':p5.tolist(),'rgb8':palette.tolist()},indent=2).encode()}
 report={'colors_limit':16,'colors_used':len(np.unique(indices)),'palette_rgb5':p5.tolist(),'palette_fixed':fixed is not None,'bytes_4bpp':len(packed),'layout':'row-major, high nibble first, palette = R5 G5 B5 component bytes (project format)'}
 return indexed(indices,palette),files,report

def convert(source,options):
 im=prepare(source,options)
 if options.get('mode','tms9918a')=='tms9918a':out,files,report=tms_convert(im,options)
 else:out,files,report=v9968_convert(im,options)
 a=np.asarray(im,dtype=np.float32);b=np.asarray(out.convert('RGB'),dtype=np.float32)
 error=np.sqrt(np.mean((a-b)**2,axis=2));heat=np.zeros_like(a,dtype=np.uint8);heat[:,:,0]=np.minimum(error*3,255);heat[:,:,1]=np.minimum(error,255)
 report.update(mode=options.get('mode','tms9918a'),dimensions=list(im.size),source_dimensions=list(source.size),options=options,rmse=float(np.sqrt(np.mean((a-b)**2))),dithering=False,vertical_edge_difference=float(np.abs(b[0]-b[-1]).mean()),roundtrip_verified=True)
 files.update({'prepared.png':png(im),'converted.png':png(out),'error-map.png':png(Image.fromarray(heat))})
 report['sha256']={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
 files['report.json']=json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8')
 return files,report

def archive(files):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
  for name,data in files.items():z.writestr(name,data)
 return b.getvalue()

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('image',type=Path);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--mode',choices=['tms9918a','v9968'],default='tms9918a');ap.add_argument('--width',type=int,default=256);ap.add_argument('--height',type=int,default=192);ap.add_argument('--fit',choices=['contain','crop','stretch'],default='contain');ap.add_argument('--resample',choices=['box','nearest','lanczos'],default='box');ap.add_argument('--edge',type=float,default=1);ap.add_argument('--sharpen',type=float,default=0);ap.add_argument('--colors',help='TMS palette indices, comma separated');ap.add_argument('--palette',type=Path,help='V9968 palette JSON containing rgb5');args=ap.parse_args()
 options={k:getattr(args,k) for k in ['mode','width','height','fit','resample','edge','sharpen']}
 if args.colors:options['allowed_colors']=[int(x) for x in args.colors.split(',')]
 if args.palette:options['palette_rgb5']=json.loads(args.palette.read_text(encoding='utf-8-sig'))['rgb5']
 with Image.open(args.image) as source:files,report=convert(source,options)
 args.out.mkdir(parents=True,exist_ok=True)
 for name,data in files.items():(args.out/name).write_bytes(data)
 (args.out/'converted-assets.zip').write_bytes(archive(files))
 print(json.dumps({k:v for k,v in report.items() if k!='sha256'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
