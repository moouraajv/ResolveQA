import {spawn} from 'node:child_process';
import {writeFile} from 'node:fs/promises';
const browser=spawn('/usr/lib/chromium/chromium',['--headless','--no-sandbox','--disable-gpu','--disable-extensions','--disable-background-networking','--disable-sync','--no-first-run','--remote-debugging-port=0','--user-data-dir=/tmp/mola-qa-cdp','about:blank'],{stdio:['ignore','ignore','pipe']});
const pause=ms=>new Promise(r=>setTimeout(r,ms));
try{
 const endpoint=await new Promise((resolve,reject)=>{let log='';const t=setTimeout(()=>reject(Error('Browser startup timeout')),20000);browser.stderr.on('data',b=>{log+=b;const match=log.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(match){clearTimeout(t);resolve(match[1])}})});
 const base=new URL(endpoint);const targets=await (await fetch(`http://${base.host}/json/list`)).json();
 const ws=new WebSocket(targets.find(x=>x.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
 let n=0;const pending=new Map();const errors=[];
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result)}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)});
 const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++n;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}))});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value};
 await call('Page.enable');await call('Runtime.enable');await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:'http://127.0.0.1:5173/'});
 for(let i=0;i<100;i++){await pause(150);if(await evaluate('document.querySelector(".hero-stage .mola-sprite")?.dataset.atlas === "ready"'))break;}
 await evaluate('localStorage.clear()');await call('Page.reload');for(let i=0;i<100;i++){await pause(150);if(await evaluate('document.querySelector(".hero-stage .mola-sprite")?.dataset.atlas === "ready"'))break;}await pause(150);
 const shot=async name=>{const r=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile('/tmp/'+name+'.png',Buffer.from(r.data,'base64'))};
 const rect=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)})?.getBoundingClientRect().toJSON()`);
 const click=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
 const info=()=>evaluate(`({size:[innerWidth,innerHeight,document.documentElement.scrollWidth],atlas:document.querySelector('.hero-stage .mola-sprite')?.dataset.atlas,hero:document.querySelector('.hero-sprite-wrap')?.getBoundingClientRect().toJSON(),clip:document.querySelector('.hero-stage .mola-sprite')?.dataset.clip,frame:document.querySelector('.hero-stage .mola-sprite')?.dataset.frame})`);
 const layout=()=>evaluate(`(()=>{const r=document.querySelector('.hero-sprite-wrap').getBoundingClientRect();const c=document.querySelector('.hero-controls').getBoundingClientRect();const h=document.querySelector('.hero-hitbox').getBoundingClientRect();return {spriteBottom:r.bottom,controlsTop:c.top,hitboxBottom:h.bottom,overlap:h.bottom>c.top}})()`);
 const result={desktop:await info(),desktopLayout:await layout(),errors};
 await shot('mola-rainbow-desktop-final');
 await click('button[aria-label="Saltar"]');
 result.jump=[];
 for(let i=0;i<7;i++){await pause(80);result.jump.push(await info());if(i===2)await shot('mola-rainbow-jump');}
 await click('button[aria-label="Saudar"]');await pause(150);await click('button[aria-label="Pausar movimento"]');
 const paused1=await info();await pause(450);const paused2=await info();result.pause={before:paused1,after:paused2};await click('button[aria-label="Retomar movimento"]');await pause(180);result.resume=await info();
 const stage=await rect('.hero-playfield');
 await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:stage.left+30,y:stage.top+stage.height/2});await pause(1800);result.follow=await info();result.leftEdge=await evaluate(`(()=>{const s=document.querySelector('.hero-sprite-wrap').getBoundingClientRect(),p=document.querySelector('.hero-playfield').getBoundingClientRect();return {spriteLeft:s.left,fieldLeft:p.left,spriteRight:s.right,fieldRight:p.right}})()`);
 await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:0,y:0});
 const hit=await rect('.hero-hitbox');const hx=hit.left+hit.width/2,hy=hit.top+hit.height/2;
 await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:hx,y:hy});await call('Input.dispatchMouseEvent',{type:'mousePressed',x:hx,y:hy,button:'left',clickCount:1});await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:hx+45,y:hy-40,button:'left',buttons:1});await pause(100);result.drag=await info();await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:hx+45,y:hy-40,button:'left',clickCount:1});await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:0,y:0});await pause(2000);result.dragReturn=await info();
 // Board transport: real button, DOM phase/card anchor evidence and screenshot.
 await evaluate(`document.querySelector('.board-toolbar').scrollIntoView({block:'start',behavior:'instant'})`);await pause(100);
 result.beforeMove=await evaluate(`[...document.querySelectorAll('.column-count')].map(x=>x.textContent)`);
 await evaluate(`[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Avançar tarefa').click()`);
 result.transport=[];
 for(let i=0;i<18;i++){await pause(150);const sample=await evaluate(`(()=>{const t=document.querySelector('.transport');const c=t?.querySelector('.transport-card');const s=t?.querySelector('.mola-sprite');return {hidden:t?.hidden,phase:t?.dataset.phase,rect:t?.getBoundingClientRect().toJSON(),card:c?.getBoundingClientRect().toJSON(),sprite:s?.getBoundingClientRect().toJSON(),frame:s?.dataset.frame,counts:[...document.querySelectorAll('.column-count')].map(x=>x.textContent)}})()`);result.transport.push(sample);if(sample.phase==='carry'&&!result.transportShot){await shot('mola-rainbow-carry');result.transportShot=true;}}
 result.afterMove=await evaluate(`[...document.querySelectorAll('.column-count')].map(x=>x.textContent)`);
 await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await evaluate('scrollTo({top:0,behavior:"instant"})');await pause(250);result.mobile=await info();result.mobileLayout=await layout();await shot('mola-rainbow-mobile');
 await evaluate(`document.querySelector('.board-toolbar').scrollIntoView({block:'start',behavior:'instant'})`);await pause(100);result.mobileBefore=await evaluate(`[...document.querySelectorAll('.column-count')].map(x=>x.textContent)`);await evaluate(`[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Avançar tarefa').click()`);await pause(1100);result.mobileCarry=await evaluate(`({phase:document.querySelector('.transport').dataset.phase,hidden:document.querySelector('.transport').hidden,rect:document.querySelector('.transport').getBoundingClientRect().toJSON(),scroll:document.querySelector('.kanban').scrollLeft})`);await shot('mola-rainbow-mobile-carry');await pause(2300);result.mobileAfter=await evaluate(`[...document.querySelectorAll('.column-count')].map(x=>x.textContent)`);
 await evaluate(`[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Avançar tarefa').click()`);await pause(300);await call('Emulation.setDeviceMetricsOverride',{width:412,height:844,deviceScaleFactor:1,mobile:true});await pause(300);result.resizeAbort=await evaluate(`({hidden:document.querySelector('.transport').hidden,busy:document.querySelector('.advance-button').disabled})`);
 await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});await call('Page.reload');await pause(1000);result.reduced=await info();
 await writeFile('/tmp/mola-browser-qa.json',JSON.stringify(result,null,2));console.log(JSON.stringify({report:'/tmp/mola-browser-qa.json',desktop:result.desktop,mobile:result.mobile,move:[result.beforeMove,result.afterMove],errors}));
 ws.close();
}finally{browser.kill('SIGTERM');}
