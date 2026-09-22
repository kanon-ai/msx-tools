const $=id=>document.getElementById(id);
const colors=['#000000','#000000','#21c842','#5edc78','#5455ed','#7d76fc','#d4524d','#42ebf5','#fc5554','#ff7978','#d4c154','#e6ce80','#21b03b','#c95bba','#cccccc','#ffffff'];
let source=null,palette=null,result=null,busy=false;const selected=new Set(Array.from({length:15},(_,i)=>i+1));
for(let i=1;i<16;i++){const b=document.createElement('button');b.type='button';b.className='swatch on';b.style.background=colors[i];b.title=`${i}: ${colors[i]}`;b.setAttribute('aria-label',`色 ${i}`);b.setAttribute('aria-pressed','true');b.onclick=()=>{selected.has(i)?selected.delete(i):selected.add(i);swatches()};$('swatches').append(b)}
function swatches(){[...$('swatches').children].forEach((b,i)=>{b.classList.toggle('on',selected.has(i+1));b.setAttribute('aria-pressed',String(selected.has(i+1)))})}
$('all-colors').onclick=()=>{for(let i=1;i<16;i++)selected.add(i);swatches()};$('metal-colors').onclick=()=>{selected.clear();[1,4,5,6,7,11,14,15].forEach(i=>selected.add(i));swatches()};
function read(file){if(!file)return;if(file.size>23*1024*1024){$('status').textContent='元画像は23MB以内にしてください。';return}const r=new FileReader();r.onload=()=>{source=String(r.result).split(',')[1];$('filename').textContent=file.name;$('convert').disabled=false;$('status').textContent='設定を選び、変換してください。'};r.readAsDataURL(file)}
$('image-file').onchange=e=>read(e.target.files[0]);$('drop').ondragover=e=>{e.preventDefault();$('drop').classList.add('drag')};$('drop').ondragleave=()=>$('drop').classList.remove('drag');$('drop').ondrop=e=>{e.preventDefault();$('drop').classList.remove('drag');read(e.dataTransfer.files[0])};
$('mode').onchange=()=>{const t=$('mode').value==='tms9918a';$('tms-colors').hidden=!t;$('v-palette').hidden=t;$('constraint').textContent=t?'固定15色から、横8ドットの各行で2色を選びます。':'16色をRGB555へ揃え、4bppの画素とパレットを出力します。';$('preset').value=t?'256,192':'256,212';$('preset').onchange()};
$('preset').onchange=()=>{if($('preset').value!=='custom'){const [w,h]=$('preset').value.split(',');$('width').value=w;$('height').value=h}};
['width','height'].forEach(id=>$(id).onchange=()=>$('preset').value='custom');
['edge','sharpen'].forEach(id=>$(id).oninput=()=>$(id+'-value').textContent=$(id).value);
$('palette-mode').onchange=()=>$('palette-upload').hidden=$('palette-mode').value!=='fixed';
$('palette-file').onchange=async e=>{try{const j=JSON.parse(await e.target.files[0].text());palette=j.rgb5||j.target_palette_rgb5||j;$('status').textContent='固定パレットを読み込みました。'}catch{palette=null;$('status').textContent='パレットJSONを読み込めませんでした。'}};
function zoom(){const z=$('zoom').value;for(const img of [$('before'),$('after'),$('error-image')]){img.parentElement.classList.toggle('fixed',z!=='fit');img.style.width=z==='fit'?'':`${result.report.dimensions[0]*Number(z)}px`;img.style.height=z==='fit'?'':`${result.report.dimensions[1]*Number(z)}px`}}
$('zoom').onchange=()=>{if(result)zoom()};
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('selected',t===b));document.querySelector('.compare').hidden=b.dataset.view==='error';document.querySelector('.errors').hidden=b.dataset.view!=='error'});
function metric(label,value){const d=document.createElement('div');d.className='metric';const s=document.createElement('small');s.textContent=label;const v=document.createElement('strong');v.textContent=value;d.append(s,v);return d}
$('convert').onclick=async()=>{
 if(!source||busy)return;busy=true;$('convert').disabled=true;$('status').textContent='色の組み合わせを評価し、出力を検証しています…';
 try{
  const options={mode:$('mode').value,width:Number($('width').value),height:Number($('height').value),fit:$('fit').value,resample:$('resample').value,edge:Number($('edge').value),sharpen:Number($('sharpen').value)};
  if(options.mode==='tms9918a')options.allowed_colors=[...selected];else if($('palette-mode').value==='fixed'){if(!palette)throw Error('固定パレットJSONを選択してください。');options.palette_rgb5=palette}
  const response=await fetch('/convert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image:source,options})});const j=await response.json();if(!response.ok)throw Error(j.error);result=j;
  $('before').src='data:image/png;base64,'+j.images['prepared.png'];$('after').src='data:image/png;base64,'+j.images['converted.png'];$('error-image').src='data:image/png;base64,'+j.images['error-map.png'];
  $('empty').hidden=true;$('previews').hidden=false;$('results').hidden=false;zoom();
  const r=j.report;$('metrics').replaceChildren(metric('出力サイズ',r.dimensions.join(' × ')),metric(options.mode==='tms9918a'?'PCGタイル数':'使用色数',r.tiles??r.colors_used),metric('画素の往復検証',r.roundtrip_verified?'一致':'不一致'),metric('色の誤差 RMSE',r.rmse.toFixed(1)));
  if(options.mode==='tms9918a')$('metrics').append(metric('2色制約違反',`${r.encoded_rows_exceeding_2_colors} 行`));
  const pal=r.palette_rgb5?r.palette_rgb5.map(c=>'#'+c.map(x=>Math.round(x*255/31).toString(16).padStart(2,'0')).join('')):r.allowed_palette_indices.map(i=>colors[i]);
  $('palette-result').replaceChildren(...pal.map(c=>{const s=document.createElement('span');s.className='palette-cell';s.style.background=c;s.title=c;return s}));
  const name=`${options.mode}-${r.dimensions.join('x')}`;$('png-download').href=$('after').src;$('png-download').download=name+'.png';$('zip-download').href='data:application/zip;base64,'+j.zip;$('zip-download').download=name+'.zip';
  $('export-note').textContent=options.mode==='tms9918a'?(r.full_screen2_vram_export?'PNG・PCGパターン・カラー・名前テーブル・VRAM・SC2・静止画確認ROM・検証JSONを出力します。':'PNG・PCGパターン・カラー・検証JSONを出力します。タイル配置はゲーム側で行います。'):'PNG・4bpp画素（上位ニブルが左画素）・RGB555各成分バイト・パレットJSON・検証JSONを出力します。';
  $('status').textContent='変換完了。等倍の見え方と誤差マップを確認できます。';
 }catch(e){$('status').textContent=e.message}finally{busy=false;$('convert').disabled=!source}
};
