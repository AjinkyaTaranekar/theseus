const puppeteer=require("puppeteer-core");const fs=require("fs");
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const DSF=2.5;
const clipOf=async(p,fn,arg)=>{const r=await p.evaluateHandle(fn,arg);const rect=await r.evaluate(el=>{if(!el)return null;const b=el.getBoundingClientRect();return{x:b.left+scrollX,y:b.top+scrollY,width:b.width,height:b.height}});return rect};
async function save(p,name,rect,pad=0){if(!rect){console.log("MISSING",name);return}
 await p.screenshot({path:`captures/${name}.png`,clip:{x:Math.max(0,rect.x-pad),y:Math.max(0,rect.y-pad),width:rect.width+pad*2,height:rect.height+pad*2},captureBeyondViewport:true});console.log("saved",name,Math.round(rect.width),Math.round(rect.height))}
(async()=>{
 const b=await puppeteer.launch({executablePath:(process.env.CHROME||"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),headless:"new"});
 const p=await b.newPage();await p.setViewport({width:1280,height:720,deviceScaleFactor:DSF});
 await p.goto("https://guest-box.tail27b7c5.ts.net",{waitUntil:"networkidle2"});await sleep(2500);
 await p.screenshot({path:"captures/land-hero.png"});console.log("saved land-hero");
 await p.click('[data-preset="intern"]');await p.waitForFunction(()=>document.body.innerText.includes("Analyzed in"),{timeout:120000});await sleep(5000);
 const kids=await p.evaluate(()=>[...document.querySelector("#result").children].map(c=>c.tagName+"."+c.className+" "+Math.round(c.getBoundingClientRect().height)+" "+c.textContent.trim().slice(0,30).replace(/\s+/g," ")));console.log(kids.join("\n"));
 const sect=async(start)=>clipOf(p,(s)=>[...document.querySelector("#result").children].find(c=>c.textContent.trim().startsWith(s)),start);
 // verdict: card minus the Analyzed-in line
 const v=await sect("Verdict");const an=await clipOf(p,()=>{const w=document.createTreeWalker(document.querySelector("#result"),NodeFilter.SHOW_TEXT);let n;while(n=w.nextNode()){if(n.textContent.includes("Analyzed in"))return n.parentElement}return null});
 if(v&&an)v.height=an.y-v.y-8;await save(p,"try-verdict",v);
 // first path block
 const pth=await sect("Paths this change");
 if(pth){const r=await p.evaluate(()=>{const sec=[...document.querySelector("#result").children].find(c=>c.textContent.trim().startsWith("Paths this change"));const hs=[...sec.querySelectorAll("h3,h4")].filter(h=>h.textContent.includes("→"));const a=hs[0].getBoundingClientRect(),b2=hs[1].getBoundingClientRect(),s=sec.getBoundingClientRect();return{x:s.left+scrollX,y:a.top+scrollY-8,width:s.width,height:b2.top-a.top-24}});await save(p,"try-path1",r)}
 await save(p,"try-fixes",await sect("Fixes"));await save(p,"try-trace",await sect("What Theseus did"));
 await p.close();
 // review page 124
 const q=await b.newPage();await q.setViewport({width:1280,height:720,deviceScaleFactor:DSF});
 await q.goto(process.env.R124,{waitUntil:"networkidle2",timeout:120000});await sleep(7000);await q.screenshot({path:"captures/r124-top.png"});console.log("saved r124-top");await q.close();
 // dashboard
 const d=await b.newPage();await d.setViewport({width:1280,height:720,deviceScaleFactor:DSF});
 await d.goto(fs.readFileSync("dash.url","utf8").trim(),{waitUntil:"networkidle2",timeout:180000});await sleep(6000);
 const tab=async(t)=>{await d.evaluate((t)=>{[...document.querySelectorAll("button,a,[role=tab]")].find(e=>e.textContent.trim().startsWith(t))?.click()},t);await sleep(6500);await d.evaluate(()=>window.scrollTo(0,0))};
 await tab("Overview");await d.screenshot({path:"captures/dash-overview.png"});await d.evaluate(()=>window.scrollTo(0,420));await sleep(1500);await d.screenshot({path:"captures/dash-overview-b.png"});
 await tab("Findings");await d.evaluate(()=>{document.querySelector("table tbody tr")?.click()});await sleep(2500);await d.screenshot({path:"captures/dash-findings.png"});
 await tab("Weak points");await d.screenshot({path:"captures/dash-weak.png"});
 await tab("Incidents");await d.evaluate(()=>{[...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="Show")?.click()});await sleep(4000);await d.screenshot({path:"captures/dash-incidents.png"});
 await tab("Cost");await d.screenshot({path:"captures/dash-cost.png"});
 await tab("Graph");await sleep(4000);await d.screenshot({path:"captures/dash-graph.png"});
 console.log("dash done");await b.close();
})().catch(e=>{console.error("FAIL",e.message);process.exit(1)});
