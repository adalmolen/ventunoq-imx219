const $ = id => document.getElementById(id);
const canvas=$('view'), context=canvas.getContext('2d'), analysis=$('analysis'), analysisContext=analysis.getContext('2d');
const colours=['#b8ef77','#76d9dd','#ffc784','#d7b8ff','#ffb3ba'];
const translations={person:'Persoon',cup:'Beker','cell phone':'Telefoon',bottle:'Fles',chair:'Stoel',laptop:'Laptop',keyboard:'Toetsenbord',mouse:'Muis',book:'Boek',clock:'Klok',cat:'Kat',dog:'Hond','potted plant':'Plant',tv:'Televisie',car:'Auto',bicycle:'Fiets',backpack:'Rugzak'};
const labelFor=label=>translations[label]||label;
let liveImage=null, liveMeta=null, resultImage=null, resultId='', current=null, enabled=true, settingsBusy=false, mode='live';
let resultReceived=0, apiAvailable=false;
const age=(value,received)=>value==null?Infinity:value+performance.now()-received;

function paint(ctx,target,image,items=[]){
  ctx.clearRect(0,0,target.width,target.height);
  if(!image)return;
  ctx.drawImage(image,0,0,target.width,target.height);
  ctx.save();ctx.scale(target.width/1920,target.height/1080);ctx.lineWidth=4;ctx.font='600 25px system-ui';
  items.forEach((item,i)=>{
    const [x1,y1,x2,y2]=item.box, colour=colours[i%colours.length];
    ctx.strokeStyle=colour;ctx.strokeRect(x1,y1,x2-x1,y2-y1);
    const text=`${labelFor(item.label)}  ${Math.round(item.confidence*100)}%`, width=ctx.measureText(text).width+22;
    const left=Math.max(0,Math.min(x1,1920-width)), top=Math.max(0,y1-39);
    ctx.fillStyle=colour;ctx.fillRect(left,top,width,37);ctx.fillStyle='#152a22';ctx.fillText(text,left+11,top+27);
  });ctx.restore();
}

function updateStatus(){
  const previewAge=liveMeta?age(liveMeta.age,liveMeta.received):Infinity;
  const live=!!liveImage&&previewAge<3000&&apiAvailable;
  const resultAge=current?age(current.result_age_ms,resultReceived):Infinity;
  const recognised=!!resultImage&&resultId===current?.frame_id&&current.status==='live'&&resultAge<3000&&apiAvailable;
  const items=recognised?current.detections:[];
  const shown=mode==='live'?live:recognised;
  paint(context,canvas,mode==='live'?liveImage:resultImage,mode==='analysis'?items:[]);
  paint(analysisContext,analysis,resultImage,items);
  analysis.classList.toggle('stale',!recognised);
  $('placeholder').hidden=!!(mode==='live'?liveImage:resultImage);
  $('connection').className='connection '+(live?'live':'waiting');
  $('connection').lastElementChild.textContent=live?'Camera actief':'Camera voorbereiden';
  $('stage').classList.toggle('stale',!shown);
  $('image-status').hidden=shown||!(mode==='live'?liveImage:resultImage);
  $('image-status').textContent='Vorig beeld · wacht op een actueel beeld';
  $('frame-label').textContent=shown?`Frame ${mode==='live'?liveMeta.id:resultId}`:'Wachten op beeld';
  $('view').setAttribute('aria-label',mode==='live'?'Live camerabeeld':'Herkenningsbeeld met bijbehorende detectiekaders');
  $('preview-age').textContent=live?`${Math.round(previewAge)} ms`:'—';
  $('analysis-message').textContent=recognised?`${items.length} object${items.length===1?'':'en'} · ${(resultAge/1000).toFixed(1)} s geleden`:
    current?.enabled===false?'Herkenning gepauzeerd':current?.message||'De eerste analyse verschijnt hier.';
  $('count').textContent=recognised?items.length:'—';
  $('latency').textContent=recognised&&current.inference_ms!=null?`${Math.round(current.inference_ms)} ms`:'—';
  $('message').textContent=!apiAvailable?'Verbinding met de app wordt hersteld…':!live?current?.camera_message||'Camera wordt gestart…':
    mode==='analysis'?'Kaders en beeld horen bij dezelfde analyse.':enabled?'Livebeeld actief · herkenning wordt apart bijgewerkt.':'Livebeeld actief · herkenning gepauzeerd.';
  $('save').disabled=!(mode==='live'?liveImage:resultImage);
  $('result-count').textContent=items.length;$('objects').replaceChildren();
  items.forEach((item,i)=>{
    const row=document.createElement('li'), name=document.createElement('span'), dot=document.createElement('i'), score=document.createElement('span');
    name.className='object-label';dot.className='swatch';dot.style.background=colours[i%colours.length];
    name.append(dot,document.createTextNode(labelFor(item.label)));score.className='score';score.textContent=`${Math.round(item.confidence*100)}%`;
    row.append(name,score);$('objects').append(row);
  });
  $('empty').hidden=items.length>0;
  $('empty').textContent=enabled?'Nog geen actuele objecten boven de gekozen drempel.':'Herkenning is gepauzeerd.';
}

async function pollLive(){
  const start=performance.now();
  try{
    const response=await fetch('/api/frame.jpg?after_id='+encodeURIComponent(liveMeta?.id||''),{cache:'no-store',signal:AbortSignal.timeout(2500)});
    if(![200,204].includes(response.status))throw new Error('Camera wordt voorbereid');
    const id=response.headers.get('X-Frame-Id'), frameAge=Number(response.headers.get('X-Frame-Age-Ms'));
    if(id==null||!Number.isFinite(frameAge))throw new Error('Geen framegegevens');
    if(response.status===200){
      const next=await createImageBitmap(await response.blob());
      if(liveImage)liveImage.close();liveImage=next;
    }
    liveMeta={id,age:Math.max(0,frameAge)+performance.now()-start,received:performance.now()};
    updateStatus();
  }catch(error){/* Keep the last image, with its original timestamp and stale indicator. */}
  setTimeout(pollLive,Math.max(10,100-(performance.now()-start)));
}

async function pollResult(){
  try{
    const response=await fetch('/api/result?after_id='+encodeURIComponent(resultId),{cache:'no-store',signal:AbortSignal.timeout(3000)});
    if(!response.ok)throw new Error('App-server niet bereikbaar');
    const packet=await response.json();
    if(packet.image&&packet.frame_id!==resultId){
      const next=new Image();next.src=packet.image;await next.decode();resultImage=next;resultId=packet.frame_id;
    }
    current=packet;resultReceived=performance.now();apiAvailable=true;enabled=packet.enabled;
    if(!settingsBusy&&document.activeElement!==$('confidence')){
      $('confidence').value=Math.round(packet.confidence*100);$('confidence-value').textContent=`${Math.round(packet.confidence*100)}%`;
    }
    $('toggle').textContent=enabled?'Pauzeren':'Hervatten';$('toggle').setAttribute('aria-pressed',String(enabled));
    $('model').textContent=packet.model||'Object Detection';
    $('model-size').textContent=packet.model_size?`${packet.model_size.join(' × ')} modelinvoer · 1920 × 1080 camera`:'Verwerking op de Ventuno Q';
  }catch(error){apiAvailable=false;}
  updateStatus();setTimeout(pollResult,150);
}

async function configure(values){
  settingsBusy=true;
  try{
    const response=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values),signal:AbortSignal.timeout(3000)});
    if(!response.ok)throw new Error('Instelling kon niet worden opgeslagen.');
    const result=await response.json();enabled=result.enabled;
    $('toggle').textContent=enabled?'Pauzeren':'Hervatten';$('toggle').setAttribute('aria-pressed',String(enabled));
    if(current){current={...current,status:'waiting',detections:[]};updateStatus();}
  }catch(error){$('message').textContent=error.message;}
  finally{settingsBusy=false;}
}
function setMode(next){mode=next;$('mode-live').setAttribute('aria-pressed',String(mode==='live'));$('mode-analysis').setAttribute('aria-pressed',String(mode==='analysis'));updateStatus();}
$('mode-live').addEventListener('click',()=>setMode('live'));
$('mode-analysis').addEventListener('click',()=>setMode('analysis'));
$('confidence').addEventListener('input',()=>{$('confidence-value').textContent=$('confidence').value+'%';});
$('confidence').addEventListener('change',()=>configure({confidence:Number($('confidence').value)/100}));
$('toggle').addEventListener('click',()=>configure({enabled:!enabled}));
$('save').addEventListener('click',()=>{const a=document.createElement('a');a.href=canvas.toDataURL('image/png');a.download=`imx219-${mode}-${new Date().toISOString().replace(/[:.]/g,'-')}.png`;a.click();});
setInterval(updateStatus,500);pollLive();pollResult();

// Serialize writes so a slow response cannot undo a newer slider position.
let pictureSaving=false, pictureDirty=false, pictureSequence=0, pictureTimer=null;
function pictureValues(){return {brightness:Number($('brightness').value),contrast:Number($('contrast').value)};}
function showPicture(values){
  for(const key of ['brightness','contrast']){
    $(key).value=values[key];$(key+'-value').textContent=values[key]+'%';
    $(key).setAttribute('aria-valuetext',values[key]+' procent');
    $(key).disabled=false;
  }
  $('picture-reset').disabled=false;
}
function pictureMessage(text,error=false){
  $('picture-message').textContent=text;
  $('picture-message').classList.toggle('error',error);
}
async function savePicture(){
  if(pictureSaving)return;
  pictureSaving=true;
  const sequence=pictureSequence, values=pictureValues();
  pictureMessage('Beeld aanpassen…');
  try{
    const response=await fetch('/api/picture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values),signal:AbortSignal.timeout(4000)});
    const result=await response.json();
    if(!response.ok)throw new Error(result.detail||'Instellingen konden niet worden opgeslagen.');
    if(sequence===pictureSequence){showPicture(result);pictureDirty=false;pictureMessage('Opgeslagen · blijft bewaard na afsluiten.');}
  }catch(error){
    if(sequence===pictureSequence)pictureMessage('Niet opgeslagen. '+error.message,true);
  }finally{
    pictureSaving=false;
    if(sequence!==pictureSequence){clearTimeout(pictureTimer);pictureTimer=setTimeout(savePicture,100);}
  }
}
function queuePicture(){
  pictureDirty=true;pictureSequence++;
  for(const key of ['brightness','contrast']){
    $(key+'-value').textContent=$(key).value+'%';
    $(key).setAttribute('aria-valuetext',$(key).value+' procent');
  }
  pictureMessage('Wijziging klaar om toe te passen…');
  clearTimeout(pictureTimer);pictureTimer=setTimeout(savePicture,250);
}
async function loadPicture(){
  if(!pictureSaving&&!pictureDirty&&!['brightness','contrast'].includes(document.activeElement?.id)){
    const sequence=pictureSequence;
    try{
      const response=await fetch('/api/picture',{cache:'no-store',signal:AbortSignal.timeout(3000)});
      const values=await response.json();
      if(!response.ok)throw new Error(values.detail||'Cameradienst niet bereikbaar.');
      if(sequence===pictureSequence&&!pictureSaving&&!pictureDirty){showPicture(values);pictureMessage('Instellingen worden automatisch bewaard.');}
    }catch(error){if(!pictureDirty&&!pictureSaving)pictureMessage('Instellingen niet bereikbaar. Opnieuw verbinden…',true);}
  }
  setTimeout(loadPicture,5000);
}
for(const key of ['brightness','contrast'])$(key).addEventListener('input',queuePicture);
$('picture-reset').addEventListener('click',()=>{showPicture({brightness:100,contrast:100});queuePicture();});
loadPicture();
