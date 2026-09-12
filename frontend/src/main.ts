import "maplibre-gl/dist/maplibre-gl.css";
import "./style.css";
import type { Candidate, HistoricalMapLayer, InvestigationResult } from "./types";
import type { Map as MapLibreMap } from "maplibre-gl";

type Lang = "zh" | "en";
type View = "identity" | "timeline" | "atlas" | "sources";

const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `
<div class="shell">
  <header class="topbar">
    <button class="brand" id="brandBtn" aria-label="ContextLens home"><span class="brand-mark" id="brandMark">文</span><span><b id="brandName">文脉镜 ContextLens</b><small>SHANGHAI ADDRESS DOSSIER</small></span></button>
    <div class="top-actions"><span class="service"><i id="statusDot"></i><span id="serviceText">上海图书馆官方数据</span></span><button class="ghost" id="methodBtn">方法</button><button class="ghost" id="langBtn" aria-label="Switch language">EN</button></div>
  </header>

  <main id="home" class="home">
    <section class="home-copy">
      <p class="kicker">ONE ADDRESS · FOUR ANSWERS</p>
      <h1 id="homeTitle">一条地址，<br>四个可核查答案。</h1>
      <p class="lead" id="homeLead">它过去叫什么？这里发生过什么？今天在哪里？每个答案由哪条上海图书馆记录支撑？</p>
      <form class="search-card" id="searchForm">
        <label><span id="addressLabel">上海旧址、路名或门牌</span><input id="addressInput" value="霞飞路436号" autocomplete="off"></label>
        <label class="era"><span id="eraLabel">约略年代（可选）</span><input id="eraInput" value="1930年代" autocomplete="off"></label>
        <button class="primary" id="resolveBtn" type="submit">建立地址档案 →</button>
      </form>
      <div class="examples" id="examples" aria-label="经过人工检查的示例">
        <span id="examplesLabel">先看一个完整案例</span>
        <button data-address="霞飞路436号" data-era="1930年代">霞飞路436号</button>
        <button data-address="外滩20号" data-era="1930年代">外滩20号</button>
        <button data-address="南京路百货公司" data-era="1940年代">南京路百货</button>
      </div>
      <div class="candidate-box" id="candidateBox"><p id="candidateMessage"></p><div id="candidateList"></div></div>
      <div class="trust-row"><span><b id="officialCount">154</b> <span id="officialRecordsLabel">条官方快照记录</span></span><span><b>0</b> <span id="demoRecordsLabel">条演示数据</span></span><span><b id="sourceEveryLabel">逐条</b> <span id="sourceReturnLabel">返回原始来源</span></span></div>
    </section>
    <section class="archive-hero" aria-label="1943 Shanghai archival map preview">
      <img src="https://iiif-cloud.princeton.edu/iiif/2/42%2F8a%2F93%2F428a930342fb4c36ae9b4ecdc57eae37%2Fintermediate_file/full/1600,/0/default.jpg" alt="1943 Plan of Shanghai archival map" id="heroArchiveImg">
      <div class="archive-shade"></div>
      <div class="archive-year">1943</div>
      <article><small>ARCHIVAL MAP · PUBLIC IIIF</small><h2 id="archiveTitle">先看见史料，<br>再阅读解释。</h2><p id="archiveCopy">原图来自 Princeton University Library / AGSL。历史地图只用于辨认街道结构，不制造精确门牌。</p></article>
      <a id="archiveLink" href="https://geodiscovery.uwm.edu/catalog/princeton-8623j0184" target="_blank" rel="noopener noreferrer">打开原图记录 ↗</a>
    </section>
  </main>

  <main id="dossier" class="dossier" hidden>
    <header class="dossier-head">
      <button class="back" id="backBtn">← 新建调查</button>
      <div><p class="kicker">VERIFIED ADDRESS DOSSIER</p><h1 id="placeTitle"></h1><p id="placeSummary"></p></div>
      <div class="head-actions"><button class="secondary" id="printBtn">打印 / 保存 PDF</button><button class="primary" id="downloadBtn">下载证据档案</button></div>
    </header>
    <nav class="dossier-tabs" id="dossierTabs" aria-label="地址档案四个部分">
      <button class="active" data-view="identity"><b>01</b><span>地址身份<small>旧名 → 今名</small></span></button>
      <button data-view="timeline"><b>02</b><span>发生过什么<small>按时间排列</small></span></button>
      <button data-view="atlas"><b>03</b><span>古今位置<small>原图 + 当代地图</small></span></button>
      <button data-view="sources"><b>04</b><span>证据来源<small>逐条可打开</small></span></button>
    </nav>
    <section class="view-panel" id="viewPanel"></section>
  </main>

  <div class="progress" id="progress" aria-live="polite"><div><span class="spinner"></span><p class="kicker">EVIDENCE COMPILER</p><h2 id="progressTitle">正在核对地址</h2><p id="progressText">先解析旧今路名，再连接事件、建筑和来源。</p><div class="progress-line"><i id="progressBar"></i></div></div></div>
  <div class="modal-backdrop" id="modalBackdrop"></div><aside class="modal" id="modal" aria-hidden="true"><button class="modal-close" id="modalClose" aria-label="关闭">×</button><div id="modalBody"></div></aside>
  <div class="toast" id="toast"></div>
</div>`;

const state: {lang: Lang; view: View; candidate: Candidate | null; result: InvestigationResult | null; map: MapLibreMap | null; jobId: string} = {lang:"zh", view:"identity", candidate:null, result:null, map:null, jobId:""};
const $ = <T extends HTMLElement>(id:string) => document.getElementById(id) as T;
const esc = (v:unknown) => String(v ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]!));
const api = async (path:string, options?:RequestInit) => { const r=await fetch(path, options); const data=await r.json(); if(!r.ok) throw new Error(data.error||"Request failed"); return data; };
const toast = (text:string) => { $("toast").textContent=text; $("toast").classList.add("open"); setTimeout(()=>$("toast").classList.remove("open"),2400); };

const ui = {
  zh: {
    homeTitle:"一条地址，<br>四个可核查答案。", homeLead:"它过去叫什么？这里发生过什么？今天在哪里？每个答案由哪条上海图书馆记录支撑？",
    addressLabel:"上海旧址、路名或门牌", eraLabel:"约略年代（可选）", resolve:"建立地址档案 →", examples:"先看一个完整案例",
    officialRecords:"条官方快照记录", demoRecords:"条演示数据", every:"逐条", sourceReturn:"返回原始来源",
    archiveTitle:"先看见史料，<br>再阅读解释。", archiveCopy:"原图来自 Princeton University Library / AGSL。历史地图只用于辨认街道结构，不制造精确门牌。", archiveLink:"打开原图记录 ↗",
    tabs:[["地址身份","旧名 → 今名"],["发生过什么","按时间排列"],["古今位置","原图 + 当代地图"],["证据来源","逐条可打开"]],
    tabAria:"地址档案四个部分", closeAria:"关闭", progressTitle:"正在核对地址", progressText:"先解析旧今路名，再连接事件、建筑和来源。",
  },
  en: {
    homeTitle:"One address,<br>four verifiable answers.", homeLead:"What was it called? What happened here? Where is it today? Which Shanghai Library record supports each answer?",
    addressLabel:"Historic Shanghai site, road, or house number", eraLabel:"Approximate period (optional)", resolve:"Build address dossier →", examples:"Start with a reviewed case",
    officialRecords:"official snapshot records", demoRecords:"demo records", every:"Every item", sourceReturn:"links back to its original source",
    archiveTitle:"See the source first,<br>then read the interpretation.", archiveCopy:"The original map comes from Princeton University Library / AGSL. It is used to identify street patterns, not to fabricate exact house-number locations.", archiveLink:"Open original map record ↗",
    tabs:[["Address identity","Old name → current name"],["What happened","In chronological order"],["Then and now","Original map + modern map"],["Evidence sources","Open every record"]],
    tabAria:"Four sections of the address dossier", closeAria:"Close", progressTitle:"Verifying the address", progressText:"Resolving historic and current road names, then linking events, buildings, and sources.",
  },
} as const;

const englishTerms: Record<string,string> = {
  "霞飞路（今淮海中路一带）":"Avenue Joffre (now Huaihai Middle Road)", "霞飞路":"Avenue Joffre", "淮海中路":"Huaihai Middle Road",
  "西江路":"Xijiang Road", "宝昌路":"Baochang Road", "泰山路":"Taishan Road", "林森中路":"Linsen Middle Road",
  "南京路 · 南京东路商业段":"Nanking Road · East Nanjing Road commercial section", "南京路 · 南京西路段":"Nanking Road · West Nanjing Road section",
  "南京东路":"East Nanjing Road", "南京西路":"West Nanjing Road", "南京路":"Nanking Road",
  "外滩 · 中山东一路沿线":"The Bund · Zhongshan East No. 1 Road", "外滩":"The Bund", "中山东一路":"Zhongshan East No. 1 Road", "中山东二路":"Zhongshan East No. 2 Road",
  "武康路历史街区":"Wukang Road Historic District", "武康路":"Wukang Road", "福开森路":"Route Ferguson",
  "衡山路 · 原贝当路":"Hengshan Road · formerly Avenue Pétain", "衡山路":"Hengshan Road", "贝当路":"Avenue Pétain",
  "南京西路 · 原静安寺路":"West Nanjing Road · formerly Bubbling Well Road", "静安寺路":"Bubbling Well Road",
  "四川北路 · 原北四川路":"North Sichuan Road · formerly North Szechuen Road", "四川北路":"North Sichuan Road", "北四川路":"North Szechuen Road",
  "福州路文化街":"Fuzhou Road Cultural Street", "福州路":"Fuzhou Road", "多伦路 · 原窦乐安路":"Duolun Road · formerly Darroch Road", "多伦路":"Duolun Road", "窦乐安路":"Darroch Road",
  "山阴路 · 原施高塔路":"Shanyin Road · formerly Scott Road", "山阴路":"Shanyin Road", "施高塔路":"Scott Road",
  "康健书局创办":"Founding of Kangjian Bookstore", "国泰电影院":"Cathay Theatre", "刘海粟近作展览会":"Liu Haisu Recent Works Exhibition",
  "霞飞路尚贤堂":"Shangxian Hall, Avenue Joffre", "上海地名志·道路实体":"Shanghai Gazetteer · Road Authority Records",
  "上海市第一百货商店":"Shanghai No. 1 Department Store", "上海第一食品商店":"Shanghai First Food Store", "和平饭店北楼":"Peace Hotel North Building", "外滩天文台":"Bund Observatory",
  "德利那齐宅":"Former Residence of D. L. Nazzi", "武康路210号住宅":"Residence at 210 Wukang Road", "集雅公寓":"Georgia Apartments", "国际礼拜堂":"Shanghai Community Church",
  "静安别墅":"Jing'an Villas", "国际饭店":"Park Hotel", "大桥大楼":"Bridge House", "北川公寓":"North Sichuan Apartments", "外文书店":"Foreign Languages Bookstore",
  "鸿德堂":"Hongde Church", "永安里":"Yong'an Lane", "恒丰里":"Hengfeng Lane", "积善里":"Jishan Lane",
  "上海市历史文化事件知识库":"Shanghai Historical and Cultural Events Knowledge Base", "上海优秀历史建筑":"Shanghai Heritage Architecture", "上海图书馆":"Shanghai Library", "公开辅助来源":"Public supplementary source", "开放数据":"Open data",
  "旧路名精确命中；历史事件资料中明确出现“霞飞路（今淮海中路）”。":"Exact match on the historic road name; historical event records explicitly identify Avenue Joffre as today's Huaihai Middle Road.",
  "“百货公司”等商业语境更接近南京东路，仍允许切换候选。":"Commercial context such as “department store” points more strongly to East Nanjing Road; other candidates remain available.",
  "南京路存在东西分段，需要结合门牌或建筑进一步确认。":"Nanking Road has eastern and western sections; a house number or building is needed for confirmation.", "公共历史地标精确命中。":"Exact match on a public historic landmark.",
  "现代路名精确命中，并可关联历史建筑。":"Exact match on the modern road name, with related historic buildings.", "上海图书馆地名志道路实体精确命中。":"Exact match in the Shanghai Library road authority records.",
  "康健书局创办于1934年，设址霞飞路（今淮海中路）436号，至1950年存在。":"Kangjian Bookstore was founded in 1934 at 436 Avenue Joffre (now Huaihai Middle Road) and operated until 1950.",
  "上海优秀历史建筑，位于淮海中路870号。":"A listed Shanghai heritage building at 870 Huaihai Middle Road.",
  "1927年刘海粟在霞飞路尚贤堂举办近作展览会，相关报道见《时报》和《上海画报》。":"In 1927, Liu Haisu held an exhibition of recent work at Shangxian Hall on Avenue Joffre, documented by The China Times and Shanghai Pictorial.",
  "北楼建于1929年，原名华懋饭店，位于中山东一路20号。":"The north building was completed in 1929 as the Cathay Hotel at 20 Zhongshan East No. 1 Road.",
  "外滩历史陈列室与外滩天文台，位于中山东二路1号甲。":"The Bund History Museum and Bund Observatory are at 1A Zhongshan East No. 2 Road.",
};

const exampleEnglish: Record<string,{address:string;era:string;label:string}> = {
  "霞飞路436号":{address:"436 Avenue Joffre",era:"1930s",label:"436 Avenue Joffre"},
  "外滩20号":{address:"20 The Bund",era:"1930s",label:"20 The Bund"},
  "南京路百货公司":{address:"Nanking Road department store",era:"1940s",label:"Nanking Road retail"},
};
const hasHan = (value:string) => /[\u3400-\u9fff]/.test(value);
function enData(value:unknown, fallback="Source record"): string {
  const raw=String(value??""); if(!raw||!hasHan(raw))return raw;
  if(englishTerms[raw])return englishTerms[raw];
  const year=raw.match(/^(\d{4})年$/); if(year)return year[1];
  const range=raw.match(/^(\d{4})—(\d{4})年$/); if(range)return `${range[1]}–${range[2]}`;
  if(raw==="年代待考")return "Date under review";
  const address=raw.match(/^(.+?)(\d+(?:[—–-]\d+)?)号(?:乙|甲)?$/); if(address)return `${address[2]} ${enData(address[1],"Shanghai road")}`;
  const summary=raw.match(/^已围绕(.+?)建立 (\d+) 个时空节点和 (\d+) 条可核查主张(?:，时间线覆盖 (\d{4})—(\d{4}) 年)?。$/);
  if(summary)return `Built ${summary[2]} spatiotemporal nodes and ${summary[3]} verifiable claims around ${enData(summary[1],"this address")}${summary[4]?`, covering ${summary[4]}–${summary[5]}`:""}.`;
  const identified=raw.match(/^已识别(.+?)，但目前没有足够的直接来源形成确定结论。$/); if(identified)return `${enData(identified[1],"This address")} has been identified, but there is not yet enough direct evidence for a firm conclusion.`;
  const roadRelation=raw.match(/^上海图书馆道路实体记录(.+?)与(.+?)的(?:旧今|历史)关联。$/); if(roadRelation)return `Shanghai Library road authority records link ${enData(roadRelation[1],"the historic road")} with ${enData(roadRelation[2],"its current name")}.`;
  const located=raw.match(/^(.+?)位于(.+?)，可作为该地点历史空间的实物线索。$/); if(located)return `${enData(located[1],"The building")} is located at ${enData(located[2],"this address")} and provides physical evidence of the site's historical setting.`;
  const eventClaim=raw.match(/^(.+?)，(.+?)与(.+?)形成可核查的地点—事件关系。$/); if(eventClaim)return `${enData(eventClaim[2],"The recorded event")} has a verifiable place–event relationship with ${enData(eventClaim[3],"this place")} (${enData(eventClaim[1],"date under review")}).`;
  const synthesis=raw.match(/^围绕(.+?)，至少有 (\d+) 条独立来源把同一地点连接到不同年代的事件或建筑。$/); if(synthesis)return `At least ${synthesis[2]} independent sources connect ${enData(synthesis[1],"this place")} to events or buildings from different periods.`;
  return fallback;
}
const dataText = (value:unknown, englishValue?:unknown, fallback?:string) => state.lang==="en" ? enData(englishValue||value,fallback) : String(value??"");
const inputForApi = (value:string) => Object.entries(exampleEnglish).find(([,v])=>v.address===value||v.label===value)?.[0]||value;
const eraForApi = (value:string) => value.replace(/^(\d{4})s$/, "$1年代");

function setLanguage() {
  const en=state.lang==="en";
  const c=en?ui.en:ui.zh;
  document.documentElement.lang=en?"en":"zh-CN";
  $("langBtn").textContent=en?"ZH":"EN";
  $("langBtn").setAttribute("aria-label",en?"Switch to Chinese":"Switch to English");
  $("brandMark").textContent=en?"CL":"文"; $("brandName").textContent=en?"ContextLens":"文脉镜 ContextLens";
  $("serviceText").textContent=en?"Official Shanghai Library data":"上海图书馆官方数据";
  $("methodBtn").textContent=en?"Method":"方法";
  $("backBtn").textContent=en?"← New search":"← 新建调查";
  $("printBtn").textContent=en?"Print / save PDF":"打印 / 保存 PDF";
  $("downloadBtn").textContent=en?"Download evidence":"下载证据档案";
  $("homeTitle").innerHTML=c.homeTitle; $("homeLead").textContent=c.homeLead; $("addressLabel").textContent=c.addressLabel; $("eraLabel").textContent=c.eraLabel; $("resolveBtn").textContent=c.resolve;
  $("examplesLabel").textContent=c.examples; $("examples").setAttribute("aria-label",en?"Reviewed examples":"经过人工检查的示例"); $("officialRecordsLabel").textContent=c.officialRecords; $("demoRecordsLabel").textContent=c.demoRecords; $("sourceEveryLabel").textContent=c.every; $("sourceReturnLabel").textContent=c.sourceReturn;
  $("archiveTitle").innerHTML=c.archiveTitle; $("archiveCopy").textContent=c.archiveCopy; $("archiveLink").textContent=c.archiveLink; $("dossierTabs").setAttribute("aria-label",c.tabAria); $("modalClose").setAttribute("aria-label",c.closeAria);
  document.querySelectorAll<HTMLButtonElement>(".dossier-tabs button").forEach((button,index)=>{const span=button.querySelector("span"),small=button.querySelector("small");if(span&&small){span.firstChild!.textContent=c.tabs[index][0];small.textContent=c.tabs[index][1];}});
  document.querySelectorAll<HTMLButtonElement>("[data-address]").forEach(button=>{const zh=button.dataset.address||"";button.textContent=en?(exampleEnglish[zh]?.label||enData(zh,"Reviewed example")):zh;});
  document.querySelectorAll<HTMLButtonElement>(".candidate[data-zh-name]").forEach(button=>{const name=button.querySelector("b"),reason=button.querySelector("small");if(name)name.textContent=en?enData(button.dataset.zhName,"Shanghai address"):(button.dataset.zhName||"");if(reason)reason.textContent=en?enData(button.dataset.zhReason,"Candidate selected from the Shanghai Library road authority records."):(button.dataset.zhReason||"");});
  const addressInput=$("addressInput") as HTMLInputElement, eraInput=$("eraInput") as HTMLInputElement;
  const matchingExample=Object.entries(exampleEnglish).find(([zh,v])=>addressInput.value===zh||addressInput.value===v.address);
  if(matchingExample){addressInput.value=en?matchingExample[1].address:matchingExample[0];eraInput.value=en?matchingExample[1].era:eraForApi(eraInput.value);}
  if(!state.result){$("progressTitle").textContent=c.progressTitle;$("progressText").textContent=c.progressText;} else {$("placeTitle").textContent=dataText(state.result.candidate.display_name,undefined,"Shanghai address");$("placeSummary").textContent=dataText(state.result.summary,undefined,"A verified address dossier based on the available source records.");renderView();}
  $("toast").classList.remove("open"); $("toast").textContent="";
  if($("modal").classList.contains("open"))closeModal();
}

function openModal(html:string){ $("modalBody").innerHTML=html; $("modal").classList.add("open"); $("modalBackdrop").classList.add("open"); $("modal").setAttribute("aria-hidden","false"); }
function closeModal(){ $("modal").classList.remove("open"); $("modalBackdrop").classList.remove("open"); $("modal").setAttribute("aria-hidden","true"); }
function showProgress(){ $("progressBar").style.width="10%"; $("progress").classList.add("open"); }
function hideProgress(){ $("progress").classList.remove("open"); }

async function resolveAddress(address:string, era:string){
  if(!address.trim()){toast(state.lang==="en"?"Please enter an address.":"请输入地址");return;}
  showProgress();
  try{
    const apiAddress=inputForApi(address), apiEra=eraForApi(era);
    const data=await api("/api/place/resolve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({address:apiAddress,era_hint:apiEra,allow_live:true,language:state.lang})});
    hideProgress();
    if(!data.candidates?.length){ $("candidateBox").classList.add("open"); $("candidateMessage").textContent=state.lang==="en"?"No verifiable place was found. Add a road, house number, or period.":(data.guidance||"没有找到可确认的地点。请补充路名、门牌或年代。"); $("candidateList").innerHTML=""; return; }
    if(data.candidates.length===1){ await investigate(apiAddress,apiEra,data.candidates[0]); return; }
    $("candidateBox").classList.add("open"); $("candidateMessage").textContent=state.lang==="en"?"This input may refer to more than one place. Please confirm:":"这个输入可能对应多个地点，请确认：";
    $("candidateList").innerHTML=data.candidates.map((c:Candidate)=>`<button class="candidate" data-id="${esc(c.candidate_id)}" data-zh-name="${esc(c.display_name)}" data-zh-reason="${esc(c.match_reason)}"><span><b>${esc(dataText(c.display_name,undefined,"Shanghai address"))}</b><small>${esc(dataText(c.match_reason,undefined,"Candidate selected from the Shanghai Library road authority records."))}</small></span><strong>${Math.round(c.confidence*100)}%</strong></button>`).join("");
    $("candidateList").querySelectorAll<HTMLButtonElement>(".candidate").forEach((btn,i)=>btn.onclick=()=>investigate(apiAddress,apiEra,data.candidates[i]));
  }catch(e){hideProgress();toast(state.lang==="en"?"Address resolution failed.":(e instanceof Error?e.message:"地址解析失败"));}
}

async function investigate(address:string,era:string,candidate:Candidate){
  state.candidate=candidate; showProgress(); $("progressTitle").textContent=state.lang==="en"?"Building the address dossier":"正在建立地址档案"; $("progressText").textContent=state.lang==="en"?"Keeping only place-specific records that link back to a source.":"只保留与地点直接相关且可返回来源的记录。";
  try{
    const job=await api("/api/investigations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({address,era_hint:era,candidate,allow_live:true,language:state.lang})}); state.jobId=job.id;
    // Hosted investigations finish in one request; the local server keeps its progress API.
    if(job.status==="complete" && job.result){state.result=job.result;hideProgress();openDossier();return;}
    for(let i=0;i<80;i++){
      const current=await api(`/api/investigations/${job.id}`); $("progressBar").style.width=`${Math.max(18,current.progress||i*2)}%`; if(current.message&&state.lang==="zh") $("progressText").textContent=current.message;
      if(current.status==="complete"){state.result=current.result;hideProgress();openDossier();return;} if(current.status==="failed") throw new Error(current.error||"调查失败"); await new Promise(r=>setTimeout(r,180));
    }
    throw new Error("调查超时");
  }catch(e){hideProgress();toast(state.lang==="en"?"The investigation could not be completed.":(e instanceof Error?e.message:"调查失败"));}
}

function openDossier(){
  if(!state.result)return; $("candidateBox").classList.remove("open"); $("home").hidden=true; $("dossier").hidden=false; state.view="identity";
  $("placeTitle").textContent=dataText(state.result.candidate.display_name,undefined,"Shanghai address"); $("placeSummary").textContent=dataText(state.result.summary,undefined,"A verified address dossier based on the available source records.");
  document.querySelectorAll<HTMLButtonElement>(".dossier-tabs button").forEach(b=>b.classList.toggle("active",b.dataset.view===state.view)); renderView(); window.scrollTo({top:0,behavior:"smooth"});
}

function renderView(){
  if(!state.result)return; if(state.map){state.map.remove();state.map=null;}
  const panel=$("viewPanel");
  if(state.view==="identity") panel.innerHTML=identityView();
  if(state.view==="timeline") panel.innerHTML=timelineView();
  if(state.view==="atlas"){panel.innerHTML=atlasView(); void initMap();}
  if(state.view==="sources") panel.innerHTML=sourcesView();
  wirePanel();
}

function identityView(){
  const r=state.result!, periods=r.candidate.name_periods||[], en=state.lang==="en"; const direct=r.claims?.filter((c:any)=>c.support_level==="direct")||[];
  return `<div class="identity-layout"><article class="answer-card hero-answer"><p class="answer-label">ANSWER 01 · ADDRESS IDENTITY</p><h2>${esc(dataText(r.candidate.historical_names?.[0]||r.candidate.canonical_name,undefined,"Historic road name"))} <span>→</span> ${esc(dataText(r.candidate.modern_names?.[0]||r.candidate.canonical_name,undefined,"Current road name"))}</h2><p>${esc(dataText(r.candidate.match_reason,undefined,"Matched against Shanghai Library road authority records."))}</p><div class="confidence"><span>${en?"Address resolution confidence":"地址解析可信度"}</span><b>${Math.round(r.candidate.confidence*100)}%</b></div></article><section class="name-ladder"><h3>${en?"How this road acquired its current name":"这条路如何变成今天的名字"}</h3>${periods.length?periods.map((p:any,i:number)=>`<div class="name-step"><b>${String(i+1).padStart(2,"0")}</b><span><strong>${esc(dataText(p.name,p.name_en,"Historic road name"))}</strong><small>${p.from_year||(en?"Date under review":"年代待考")}${p.to_year?`—${p.to_year}`:(en?"—present":"—至今")}</small></span></div>`).join(""):`<div class="empty">${en?"The official records do not yet provide a complete renaming sequence.":"官方记录暂未提供完整更名序列。"}</div>`}</section><aside class="audit-card"><p class="answer-label">WHAT WE CAN SAY</p><h3>${direct.length} ${en?"direct claims":"条直接主张"}</h3>${direct.slice(0,3).map((c:any)=>`<button class="claim-link" data-evidence="${esc(c.evidence_ids?.[0]||"")}">${esc(dataText(c.text,c.text_en,"Verified claim from the linked source record."))}<span>${en?"View evidence":"查看证据"} ↗</span></button>`).join("")}<p class="boundary">${en?"Nothing unsupported by a source is filled in as a story.":"没有来源支撑的内容不会补写为故事。"}</p></aside></div>`;
}

function timelineView(){
  const r=state.result!, timeline=r.timeline||[], en=state.lang==="en";
  return `<div class="section-intro"><p class="answer-label">ANSWER 02 · WHAT HAPPENED HERE</p><h2>${timeline.length} ${en?"verifiable place nodes":"个可核查地点节点"}</h2><p>${en?'Ordered by dates in the records; items marked “date under review” are not forced into a definite timeline.':'按资料中的年代排列；“年代待考”不会被强行放进确定时间线。'}</p></div><div class="timeline-list">${timeline.length?timeline.map((item:any,i:number)=>`<article class="timeline-card"><time>${esc(dataText(item.time_label||item.date||"年代待考",item.time_label_en,en?"Date under review":"年代待考"))}</time><div><span class="type">${esc(en?(item.feature_type||item.type)==="building"?"Building":"Event":(item.feature_type||item.type||"地点记录"))}</span><h3>${esc(dataText(item.title,item.title_en,"Source record"))}</h3><p>${esc(dataText(item.description||item.address||"",item.description_en,"Address recorded in the source."))}</p><button data-evidence="${esc(item.feature_id||item.evidence_id||"")}">${en?"View original evidence":"查看原始证据"} →</button></div><b>${String(i+1).padStart(2,"0")}</b></article>`).join(""):`<div class="empty">${en?"There are not enough dated nodes for this address.":"当前地址没有足够的时间节点。"}</div>`}</div>${questionBlock()}`;
}

function atlasView(){
  const maps=state.result!.experience?.historical_maps||[], en=state.lang==="en"; const active=maps.find((m:HistoricalMapLayer)=>m.map_id==="princeton-1943")||maps[0];
  return `<div class="section-intro"><p class="answer-label">ANSWER 03 · THEN AND NOW</p><h2>${en?"Read the historical original beside today's location.":"历史原图与今天的位置，并排阅读。"}</h2><p>${en?"An unfinished georeferencing is not presented as a precise overlay. The source map is on the left; today's location is on the right.":"我们不再把未完成配准的原图伪装成精确叠加。左侧看史料，右侧负责今天的定位。"}</p></div><div class="atlas-grid"><figure class="archive-map"><div class="map-label"><b>${esc(active?.year||1943)}</b><span>${en?"Historical original":"历史原图"}</span></div><img src="${esc(active?.image_url)}" alt="${esc(dataText(active?.title,(active as any)?.title_en,"Historical Shanghai map"))}"><figcaption><strong>${esc(dataText(active?.title,(active as any)?.title_en,"Historical Shanghai map"))}</strong><span>${esc(dataText(active?.provider,undefined,"Archive provider"))} · ${esc(active?.license)}</span><a href="${esc(active?.source_url)}" target="_blank" rel="noopener noreferrer">${en?"Open collection record":"打开馆藏记录"} ↗</a></figcaption></figure><section class="modern-map"><div class="map-label"><b>${new Date().getFullYear()}</b><span>${en?"Present-day location":"当代定位"}</span></div><div id="modernMap"></div><div class="map-fail" id="mapFail"><b>${en?"Online basemap unavailable":"在线底图暂不可用"}</b><span>${en?"The address coordinates and evidence remain available. Try the basemap again later.":"地址坐标和证据仍保留；请稍后重试底图。"}</span></div></section></div><div class="map-boundary"><b>${en?"Limits of use":"使用边界"}</b><span>${en?"The historical original has georeferencing error and cannot prove an exact house-number location. The modern map is from OpenFreeMap / OpenStreetMap.":"历史原图存在配准误差，不能据此声称精确门牌位置。现代地图来自 OpenFreeMap / OpenStreetMap。"}</span></div>`;
}

function sourcesView(){
  const evidence=state.result!.evidence||[], en=state.lang==="en";
    return `<div class="section-intro source-intro"><div><p class="answer-label">ANSWER 04 · SOURCE RECEIPT</p><h2>${evidence.length} ${en?"evidence records, each linked to its source.":"条证据，每条都能回到来源。"}</h2><p>${en?"Official records and public supplementary sources are identified separately; collection size is never presented as the number of matches.":"官方记录与辅助公开来源分开标识；查询规模不冒充本次命中数量。"}</p></div><div class="source-score"><b>${state.result!.quality?.source_count||0}</b><span>${en?"openable sources":"可打开来源"}</span></div></div><div class="source-table"><div class="source-row source-head"><span>${en?"Record":"记录"}</span><span>${en?"Dataset / period":"数据集 / 年代"}</span><span>${en?"Source status":"来源状态"}</span><span></span></div>${evidence.map((e:any)=>`<article class="source-row"><span><b>${esc(dataText(e.source_title||e.title,e.source_title_en||e.title_en,"Shanghai Library source record"))}</b><small>${esc(dataText(e.description||e.snippet||"",e.description_en||e.snippet_en,"Original Chinese source record; use the source passport to open the full record."))}</small></span><span>${esc(dataText(e.dataset_label||e.dataset||e.source_title||"开放数据",e.dataset_label_en||e.dataset_en,"Open data"))}<small>${esc(dataText(e.time_label||e.date||"年代待考",e.time_label_en,"Date under review"))}</small></span><span><i></i>${en?(e.source_mode==="live_api"?"Live official API":e.source_mode==="reviewed_official_snapshot"?"Reviewed official snapshot":"Public supplementary source"):(e.source_mode==="live_api"?"实时官方接口":e.source_mode==="reviewed_official_snapshot"?"已核验官方快照":"公开辅助来源")}</span><button data-evidence="${esc(e.evidence_id||e.record_id)}">${en?"Source passport":"来源护照"} →</button></article>`).join("")}</div>`;
}

function questionBlock(){const en=state.lang==="en";return `<section class="questions"><div><p class="answer-label">THREE USEFUL QUESTIONS</p><h2>${en?"Questions come from this dossier,<br>not from generic chat.":"问题由当前档案决定，<br>不是泛泛聊天。"}</h2></div><div><button data-question="names"><b>01</b><span>${en?"Why did this road change names?":"这条路为什么改名？"}<small>${en?"Uses only road identity and dated names":"只使用道路身份和名称年代回答"}</small></span></button><button data-question="event"><b>02</b><span>${en?"What happened at this address?":"这个门牌发生过什么？"}<small>${en?"Uses only direct place-event evidence":"只使用直接地点事件回答"}</small></span></button><button data-question="limits"><b>03</b><span>${en?"What remains unknown?":"哪些内容仍然不知道？"}<small>${en?"Shows gaps in time, space, and sources":"显示时间、空间和来源空白"}</small></span></button></div></section>`;}

function wirePanel(){
  $("viewPanel").querySelectorAll<HTMLButtonElement>("[data-evidence]").forEach(b=>b.onclick=()=>openEvidence(b.dataset.evidence||""));
  $("viewPanel").querySelectorAll<HTMLButtonElement>("[data-question]").forEach(b=>b.onclick=()=>answerQuestion(b.dataset.question||""));
}

function openEvidence(id:string){
  const r=state.result!, en=state.lang==="en"; const e=(r.evidence||[]).find((x:any)=>x.evidence_id===id||x.record_id===id)||(r.evidence||[])[0]; if(!e){toast(en?"No matching evidence was found.":"没有找到对应证据");return;}
  const lineage=e.lineage||{}, status=en?(e.source_mode==="live_api"?"Live official API":e.source_mode==="reviewed_official_snapshot"?"Reviewed official snapshot":"Public supplementary source"):(e.source_mode==="live_api"?"实时官方接口":e.source_mode==="reviewed_official_snapshot"?"已核验官方快照":"公开辅助来源"); openModal(`<p class="answer-label">SOURCE PASSPORT</p><h2>${esc(dataText(e.source_title||e.title,e.source_title_en||e.title_en,"Shanghai Library source record"))}</h2><p class="modal-lead">${esc(dataText(e.description||e.snippet||"",e.description_en||e.snippet_en,"Original Chinese source record; open the source below for the full record."))}</p><dl><dt>${en?"Source status":"来源状态"}</dt><dd>${status}</dd><dt>${en?"Data provider":"数据提供方"}</dt><dd>${esc(dataText(lineage.provider||e.provider||"上海图书馆",undefined,"Shanghai Library"))}</dd><dt>${en?"Dataset":"数据集"}</dt><dd>${esc(dataText(e.dataset_label||e.dataset||lineage.dataset||e.source_title||"开放数据",e.dataset_label_en||e.dataset_en,"Open data"))}</dd><dt>${en?"Period":"年代"}</dt><dd>${esc(dataText(e.time_label||e.date||"年代待考",e.time_label_en,"Date under review"))}</dd><dt>${en?"Evidence ID":"证据编号"}</dt><dd>${esc(e.evidence_id||e.record_id)}</dd><dt>${en?"Normalization":"标准化"}</dt><dd>${esc(lineage.normalization||"ContextLens place investigation v1")}</dd></dl><a class="primary modal-link" href="${esc(e.source_uri||lineage.official_uri||"#")}" target="_blank" rel="noopener noreferrer">${en?"Open original source":"打开原始来源"} ↗</a>`);
}

function answerQuestion(kind:string){
  const r=state.result!, en=state.lang==="en", direct=(r.claims||[]).filter((c:any)=>c.support_level==="direct"); let title="",body="";
  if(kind==="names"){title=en?"Why did this road change names?":"这条路为什么改名？"; const names=(r.candidate.name_periods||[]).map((p:any)=>dataText(p.name,p.name_en,"Historic road name")).join(" → ")||(en?"No complete sequence is available":"尚无完整序列"); body=en?`Official road authority records show this name sequence: ${names}. The changes are verifiable facts; political or institutional causes are not inferred without a direct source.`:`官方道路实体记录显示名称经历：${names}。名称变化是可核查事实；具体政治或制度原因若无直接来源，不在本档案中推断。`;}
  if(kind==="event"){title=en?"What happened at this address?":"这个门牌发生过什么？"; body=dataText(direct[0]?.text||r.finding,direct[0]?.text_en||(r as any).finding_en,"The linked source record provides the directly supported place event.");}
  if(kind==="limits"){title=en?"What remains unknown?":"哪些内容仍然不知道？"; body=en?`Current spatial precision: ${r.quality?.uncertainty==="bounded"?"source coordinates available":"road extent or approximate location"}. ${(r.timeline||[]).some((x:any)=>!x.start_year&&!x.date)?"Some nodes still have dates under review.":"All current nodes include a date clue."} The original map is not used to prove an exact house number.`:`当前空间精度：${r.quality?.uncertainty==="bounded"?"来源坐标可用":"道路范围或近似位置"}。${(r.timeline||[]).some((x:any)=>!x.start_year&&!x.date)?"部分节点年代待考。":"现有节点均有年代线索。"} 原图不用于证明精确门牌。`;}
  openModal(`<p class="answer-label">GROUNDED ANSWER</p><h2>${esc(title)}</h2><p class="modal-lead">${esc(body)}</p><p class="boundary">${en?'This answer uses only records in the current address dossier. Open “Evidence sources” to verify each item.':'回答只使用当前地址档案中的记录；点击“证据来源”可逐条复核。'}</p>`);
}

async function initMap(){
  const container=document.getElementById("modernMap"); if(!container||!state.result)return;
  try{const maplibre=await import("maplibre-gl"); const center=state.result.map?.center||[121.4737,31.2304]; state.map=new maplibre.Map({container,style:"https://tiles.openfreemap.org/styles/liberty",center,zoom:14,attributionControl:{compact:true}}); state.map.on("load",()=>{const fc=state.result!.feature_collection; state.map!.addSource("evidence",{type:"geojson",data:fc}); state.map!.addLayer({id:"evidence-points",type:"circle",source:"evidence",paint:{"circle-radius":8,"circle-color":"#b64b38","circle-stroke-width":3,"circle-stroke-color":"#fffaf0"}}); if(state.result!.map?.bounds?.length===4){const b=state.result!.map.bounds;state.map!.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:70,maxZoom:15});}}); state.map.on("error",()=>$("mapFail").classList.add("open"));}
  catch{$("mapFail").classList.add("open");}
}

function downloadEvidence(){if(!state.result)return;const blob=new Blob([JSON.stringify(state.result,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`ContextLens-${state.result.candidate.canonical_name}-evidence.json`;a.click();URL.revokeObjectURL(a.href);}

$("searchForm").addEventListener("submit",e=>{e.preventDefault();void resolveAddress(($("addressInput") as HTMLInputElement).value,($("eraInput") as HTMLInputElement).value);});
document.querySelectorAll<HTMLButtonElement>("[data-address]").forEach(b=>b.onclick=()=>{const zh=b.dataset.address||"", display=state.lang==="en"?(exampleEnglish[zh]?.address||enData(zh,"Reviewed Shanghai address")):zh, era=state.lang==="en"?(exampleEnglish[zh]?.era||b.dataset.era||""):(b.dataset.era||"");($("addressInput") as HTMLInputElement).value=display;($("eraInput") as HTMLInputElement).value=era;void resolveAddress(display,era);});
document.querySelectorAll<HTMLButtonElement>(".dossier-tabs button").forEach(b=>b.onclick=()=>{state.view=b.dataset.view as View;document.querySelectorAll(".dossier-tabs button").forEach(x=>x.classList.toggle("active",x===b));renderView();});
$("backBtn").onclick=()=>{$("dossier").hidden=true;$("home").hidden=false;if(state.map){state.map.remove();state.map=null;}};
$("brandBtn").onclick=()=>$("backBtn").click(); $("langBtn").onclick=()=>{state.lang=state.lang==="zh"?"en":"zh";setLanguage();};
$("methodBtn").onclick=()=>openModal(state.lang==="en"?`<p class="answer-label">PRODUCT METHOD</p><h2>One address, four answers.</h2><ol class="method-list"><li><b>Address identity</b><span>Separate historic road name, house number, and period while preserving ambiguity.</span></li><li><b>Place events</b><span>Link only events and buildings that directly name this place.</span></li><li><b>Then and now</b><span>Place the historical original beside the modern map without fabricating a precise overlay.</span></li><li><b>Source passport</b><span>Return the provider, dataset, URI, and normalization record for every claim.</span></li></ol>`:`<p class="answer-label">PRODUCT METHOD</p><h2>一个地址，四个答案。</h2><ol class="method-list"><li><b>地址身份</b><span>拆分旧路名、门牌与年代，并保留歧义。</span></li><li><b>地点事件</b><span>只连接直接出现该地点的事件和建筑。</span></li><li><b>古今位置</b><span>历史原图与现代地图并排，不伪造精确叠加。</span></li><li><b>来源护照</b><span>每条主张返回提供方、数据集、URI与标准化记录。</span></li></ol>`);
$("printBtn").onclick=()=>window.print(); $("downloadBtn").onclick=downloadEvidence; $("modalClose").onclick=closeModal; $("modalBackdrop").onclick=closeModal;
$("heroArchiveImg").addEventListener("error",()=>document.querySelector(".archive-hero")?.classList.add("image-failed"));
fetch("/api/health").then(r=>r.json()).then(h=>{$("officialCount").textContent=String(h.official_records||0);$("statusDot").classList.toggle("ok",h.ok&&!h.demo_seed_active);}).catch(()=>$("serviceText").textContent=state.lang==="en"?"Evidence service offline":"证据服务离线");
