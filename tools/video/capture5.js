const puppeteer=require("puppeteer-core");const fs=require("fs");const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const b=await puppeteer.launch({executablePath:(process.env.CHROME||"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),headless:"new"});
 const d=await b.newPage();await d.setViewport({width:1280,height:720,deviceScaleFactor:2.5});
 await d.goto(fs.readFileSync("dash.url","utf8").trim(),{waitUntil:"networkidle2",timeout:180000});await sleep(5000);
 const tab=async(t)=>{await d.evaluate((t)=>{[...document.querySelectorAll("button,a,[role=tab]")].find(e=>e.textContent.trim().startsWith(t))?.click()},t);await sleep(6000);await d.evaluate(()=>window.scrollTo(0,0))};
 // weak points: open first row
 await tab("Weak points");
 await d.evaluate(()=>{const r=[...document.querySelectorAll("table tbody tr")].find(r=>r.textContent.includes("prod-db-credentials"));r?.click()});await sleep(3500);
 await d.screenshot({path:"captures/weak-open.png"});
 // incidents: real click on first Show
 await tab("Incidents");
 const btns=await d.$$("button");let shown=false;
 for(const bt of btns){const tx=await bt.evaluate(e=>e.textContent.trim());if(tx==="Show"){await bt.click();shown=true;break}}
 await sleep(6000);await d.screenshot({path:"captures/inc-open.png"});
 const info=await d.evaluate(()=>({h:document.documentElement.scrollHeight,close:[...document.querySelectorAll("button")].filter(b=>b.textContent.trim()==="Close").length,txt:document.body.innerText.slice(0,0)}));console.log("shown",shown,JSON.stringify(info));
 await d.evaluate(()=>window.scrollTo(0,520));await sleep(2500);await d.screenshot({path:"captures/inc-open-b.png"});
 // graph
 await tab("Graph");
 for(const name of ["Everything","Fit"]){await d.evaluate((n)=>{[...document.querySelectorAll("button")].find(e=>e.textContent.trim()===n)?.click()},name);await sleep(4500)}
 await d.screenshot({path:"captures/graph-all.png"});
 await d.evaluate(()=>{[...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="Risky paths")?.click()});await sleep(4500);await d.screenshot({path:"captures/graph-risky.png"});
 console.log("done");await b.close();
})().catch(e=>{console.error("FAIL",e.message);process.exit(1)});
