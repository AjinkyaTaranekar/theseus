const puppeteer=require("puppeteer-core");const fs=require("fs");const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const b=await puppeteer.launch({executablePath:(process.env.CHROME||"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),headless:"new"});
 const d=await b.newPage();await d.setViewport({width:1440,height:900,deviceScaleFactor:2.2});
 await d.goto(fs.readFileSync("dash.url","utf8").trim(),{waitUntil:"networkidle2",timeout:180000});await sleep(5000);
 const tab=async(t)=>{await d.evaluate((t)=>{[...document.querySelectorAll("button,a,[role=tab]")].find(e=>e.textContent.trim().startsWith(t))?.click()},t);await sleep(6000);await d.evaluate(()=>window.scrollTo(0,0))};
 const panel=async(name)=>{const r=await d.evaluate(()=>{const e=[...document.querySelectorAll("*")].find(x=>x.children.length&&x.textContent.includes("Click a node for details")&&x.textContent.length<900&&x.getBoundingClientRect().height>300);let p=e;while(p&&p.getBoundingClientRect().width<700)p=p.parentElement;const bb=(p||e).getBoundingClientRect();return{x:bb.left+scrollX,y:bb.top+scrollY,width:bb.width,height:bb.height}});console.log(name,JSON.stringify(r));await d.screenshot({path:`captures/${name}.png`,clip:{x:r.x,y:r.y,width:r.width,height:r.height},captureBeyondViewport:true})};
 await tab("Graph");
 for(const n of ["Everything","Fit"]){await d.evaluate((n)=>{[...document.querySelectorAll("button")].find(e=>e.textContent.trim()===n)?.click()},n);await sleep(5000)}
 await d.screenshot({path:"captures/graph-page.png"});
 await panel("graph-everything");
 await d.evaluate(()=>{[...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="Outage")?.click()});await sleep(5000);await d.screenshot({path:"captures/graph-outage-page.png"});
 console.log("done");await b.close();
})().catch(e=>{console.error("FAIL",e.message);process.exit(1)});
