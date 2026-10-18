const puppeteer=require("puppeteer-core");
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const b=await puppeteer.launch({executablePath:(process.env.CHROME||"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),headless:"new"});
 const p=await b.newPage();await p.setViewport({width:1280,height:720,deviceScaleFactor:1.5});
 await p.goto(process.env.R124,{waitUntil:"networkidle2",timeout:120000});await sleep(3000);
 const links=await p.evaluate(()=>[...document.querySelectorAll("a")].map(a=>({t:a.textContent.trim(),h:a.href})).filter(x=>/dashboard/i.test(x.t)||/dashboard/.test(x.h)));
 console.log(links.map(l=>l.t+" -> "+l.h.replace(/k=[0-9a-f]+/,"k=REDACTED")));
 const dash=links[0].h;require("fs").writeFileSync("dash.url",dash);
 await p.goto(dash,{waitUntil:"networkidle2",timeout:180000});await sleep(8000);
 await p.screenshot({path:"shots/dash-home.png"});
 const info=await p.evaluate(()=>({title:document.title,tabs:[...document.querySelectorAll("[role=tab],.tab,nav button,nav a,button")].map(e=>e.textContent.trim()).filter(t=>t&&t.length<40).slice(0,40),h:document.documentElement.scrollHeight}));
 console.log(JSON.stringify(info));
 await b.close();
})().catch(e=>{console.error("FAIL",e.message);process.exit(1)});
