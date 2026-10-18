const puppeteer=require("puppeteer-core");const fs=require("fs");const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const b=await puppeteer.launch({executablePath:(process.env.CHROME||"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),headless:"new"});
 const d=await b.newPage();await d.setViewport({width:1280,height:720,deviceScaleFactor:2.5});
 await d.goto(fs.readFileSync("dash.url","utf8").trim(),{waitUntil:"networkidle2",timeout:180000});await sleep(5000);
 await d.evaluate(()=>{[...document.querySelectorAll("button,a,[role=tab]")].find(e=>e.textContent.trim().startsWith("Findings"))?.click()});await sleep(6000);
 const n=await d.evaluate(()=>{const rows=[...document.querySelectorAll("table tbody tr")];const r=rows.find(r=>r.textContent.includes("demo-0001"));r?.click();return rows.length});await sleep(3000);
 await d.screenshot({path:"captures/dash-findings1.png"});console.log("rows",n);
 const lp=await b.newPage();await lp.setViewport({width:700,height:700,deviceScaleFactor:1});
 await lp.setContent('<body style="margin:0;background:transparent"><img id=l src="data:image/svg+xml;base64,'+fs.readFileSync("../../theseus/web/logo.svg").toString("base64")+'" width=600 height=600></body>');await sleep(500);
 await lp.screenshot({path:"captures/logo.png",omitBackground:true,clip:{x:0,y:0,width:600,height:600}});console.log("logo ok");
 await b.close();
})();
