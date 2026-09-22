import io,json,sys,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from convert import convert,decode_pcg,prepare,archive,TMS,CHANNEL

class ConverterTests(unittest.TestCase):
 def sample(self,w=32,h=16):
  y,x=np.mgrid[:h,:w]
  return Image.fromarray(np.stack(((x*31)%256,(y*53)%256,((x+y)*17)%256),axis=2).astype('uint8'))
 def test_tms_constraints_and_binary_roundtrip(self):
  f,r=convert(self.sample(),dict(mode='tms9918a',width=32,height=16,fit='stretch',edge=2))
  out=np.array(Image.open(io.BytesIO(f['converted.png'])))
  self.assertTrue(np.array_equal(out,decode_pcg(f['patterns.bin'],f['colors.bin'],32,16)))
  self.assertEqual(len(f['patterns.bin']),64)
  for y in range(16):
   for x in range(0,32,8):self.assertLessEqual(len(np.unique(out[y,x:x+8])),2)
  self.assertNotIn(0,np.unique(out))
 def test_row_pair_is_global_minimum(self):
  im=self.sample(8,8);allowed=[1,4,7,11,15]
  f,r=convert(im,dict(mode='tms9918a',width=8,height=8,allowed_colors=allowed,edge=0))
  result=np.asarray(Image.open(io.BytesIO(f['converted.png'])).convert('RGB'),dtype=float)
  src=np.asarray(im,dtype=float)
  for y in range(8):
   observed=(((src[y]-result[y])**2)*CHANNEL).sum()
   optimum=min(np.minimum((((src[y]-TMS[a])**2)*CHANNEL).sum(axis=1),(((src[y]-TMS[b])**2)*CHANNEL).sum(axis=1)).sum() for a in allowed for b in allowed)
   self.assertAlmostEqual(observed,optimum,delta=.03)
 def test_full_screen2_memory_layout(self):
  f,r=convert(self.sample(),dict(mode='tms9918a',width=256,height=192))
  v=f['vram.bin'];self.assertEqual(len(v),16384)
  self.assertEqual(v[:6144],f['patterns.bin']);self.assertEqual(v[8192:14336],f['colors.bin'])
  self.assertEqual(v[0x1800:0x1b00],bytes(range(256))*3);self.assertEqual(v[0x1b00],208)
  self.assertEqual(f['image.sc2'][:7],bytes.fromhex('FE0000FF3F0000'))
  self.assertEqual(f['image.sc2'][7:],v)
  self.assertEqual(len(f['preview-msx1.rom']),16384);self.assertEqual(f['preview-msx1.rom'][:4],b'AB\x10\x40')
  self.assertEqual(f['preview-msx1.rom'][128:6272],f['patterns.bin'])
 def test_v9968_palette_and_nibbles(self):
  f,r=convert(self.sample(),dict(mode='v9968',width=32,height=16))
  p=np.frombuffer(f['palette-rgb5.bin'],np.uint8).reshape(16,3);self.assertTrue(np.all(p<=31))
  pix=np.frombuffer(f['pixels-4bpp.bin'],np.uint8);out=np.array(Image.open(io.BytesIO(f['converted.png']))).flatten()
  self.assertTrue(np.array_equal(pix>>4,out[::2]));self.assertTrue(np.array_equal(pix&15,out[1::2]))
  self.assertEqual(len(f['palette-rgb5.bin']),48)
 def test_fixed_palette_keeps_order(self):
  palette=[[i*2,i,31-i] for i in range(16)]
  f,r=convert(self.sample(),dict(mode='v9968',width=32,height=16,palette_rgb5=palette))
  self.assertEqual(list(f['palette-rgb5.bin']),sum(palette,[]))
 def test_flat_image_and_determinism(self):
  for mode in ['tms9918a','v9968']:
   a=convert(Image.new('RGB',(8,8),'black'),dict(mode=mode,width=8,height=8))[0]
   b=convert(Image.new('RGB',(8,8),'black'),dict(mode=mode,width=8,height=8))[0]
   self.assertEqual(a,b)
 def test_reject_invalid_geometry_and_palette(self):
  for options in [dict(mode='tms9918a',width=257,height=192),dict(mode='v9968',width=31,height=16),dict(mode='tms9918a',width=8,height=8,allowed_colors=[]),dict(mode='v9968',width=8,height=8,palette_rgb5=[[32,0,0]]*16)]:
   with self.assertRaises(ValueError):convert(self.sample(),options)
 def test_alpha_and_contain(self):
  src=Image.new('RGBA',(16,8),(255,0,0,0));im=prepare(src,dict(width=16,height=16))
  self.assertEqual(im.getbbox(),None)
 def test_zip_report_has_checksums(self):
  f,r=convert(self.sample(),dict(width=32,height=16))
  with zipfile.ZipFile(io.BytesIO(archive(f))) as z:
   self.assertIsNone(z.testzip());self.assertIn('patterns.bin',json.loads(z.read('report.json'))['sha256'])

if __name__=='__main__':unittest.main()
