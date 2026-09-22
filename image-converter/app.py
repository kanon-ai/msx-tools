"""Local-only browser UI; uploaded images stay in this process."""
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import argparse,base64,io,json,threading,webbrowser
import urllib.request
from PIL import Image,UnidentifiedImageError
from convert import convert,archive
ROOT=Path(__file__).resolve().parent
class LocalServer(ThreadingHTTPServer):
 allow_reuse_address=False
class Handler(BaseHTTPRequestHandler):
 def send(self,status,data,mime='application/json; charset=utf-8'):
  self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
 def do_GET(self):
  if self.path=='/health':return self.send(200,b'{"app":"MSX Image Converter","version":"1.0"}')
  routes={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
  if self.path not in routes:return self.send(404,b'{}')
  name,mime=routes[self.path];self.send(200,(ROOT/'web'/name).read_bytes(),mime)
 def do_POST(self):
  if self.path!='/convert':return self.send(404,b'{}')
  origin=self.headers.get('Origin')
  if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
   return self.send(403,b'{"error":"Local requests only"}')
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=32*1024*1024:raise ValueError('画像を含む要求は32MB以内にしてください。')
   req=json.loads(self.rfile.read(size))
   data=base64.b64decode(req['image'],validate=True)
   with Image.open(io.BytesIO(data)) as source:
    if source.width*source.height>32000000:raise ValueError('元画像は3200万画素以内にしてください。')
    files,report=convert(source,req['options'])
   response={'report':report,'images':{name:base64.b64encode(files[name]).decode() for name in ['prepared.png','converted.png','error-map.png']},'zip':base64.b64encode(archive(files)).decode()}
   self.send(200,json.dumps(response,ensure_ascii=False).encode())
  except (ValueError,KeyError,TypeError,UnidentifiedImageError,Image.DecompressionBombError) as e:
   self.send(400,json.dumps({'error':str(e)},ensure_ascii=False).encode())
  except Exception as e:
   print(type(e).__name__,str(e),flush=True);self.send(500,json.dumps({'error':'変換に失敗しました。入力と設定を確認してください。'},ensure_ascii=False).encode())
 def log_message(self,fmt,*args):print(fmt%args,flush=True)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--port',type=int,default=8791);ap.add_argument('--no-browser',action='store_true');args=ap.parse_args()
 try:server=LocalServer(('127.0.0.1',args.port),Handler)
 except OSError:
  url=f'http://127.0.0.1:{args.port}'
  try:
   with urllib.request.urlopen(url+'/health',timeout=2) as response:status=json.load(response)
   if status.get('app')!='MSX Image Converter':raise RuntimeError('指定ポートは別のアプリが使用しています。--portで変更してください。')
  except Exception:raise RuntimeError('指定ポートを使用できません。--portで変更してください。') from None
  print('Already running: '+url)
  if not args.no_browser:webbrowser.open(url)
  return
 url=f'http://127.0.0.1:{server.server_port}'
 print('MSX Image Converter: '+url,flush=True)
 if not args.no_browser:threading.Timer(.6,lambda:webbrowser.open(url)).start()
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
if __name__=='__main__':main()
