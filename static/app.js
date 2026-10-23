const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
let currentView = "overview";
let reportFilter = "all";
let toastTimer;

function toast(message) {
  const el = $("#toast"); el.textContent = message; el.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(()=>el.classList.remove("show"), 3500);
}
async function api(path, options={}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(()=>({detail:"Unexpected server response"}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}
function esc(v="") { return String(v).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function iconFor(item) {
  const s = `${item.category||""} ${item.item_name||""}`.toLowerCase();
  if (/headphone|earbud|phone|laptop|electronic|charger|watch/.test(s)) return "🎧";
  if (/bag|backpack|purse/.test(s)) return "🎒";
  if (/key/.test(s)) return "🔑";
  if (/book|notebook|pen/.test(s)) return "📚";
  if (/bottle/.test(s)) return "🧴";
  if (/wallet/.test(s)) return "👛";
  return "📦";
}
function thumb(item) {
  return `<div class="item-thumb">${item.image_path ? `<img src="${esc(item.image_path)}" alt="Item photo">` : iconFor(item)}</div>`;
}
function dateFmt(v) {
  if (!v) return "Date not provided";
  try { return new Date(v+"T00:00:00").toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"}); } catch { return v; }
}
function locationLine(item) {
  return [item.location, item.event_date && dateFmt(item.event_date)].filter(Boolean).join(" · ") || "Location and date not provided";
}
function reportRow(item) {
  return `<article class="report-row">${thumb(item)}<div class="report-main"><b>${esc(item.item_name)}</b><small>${esc(locationLine(item))}</small></div><span class="type-pill ${item.report_type==="lost"?"type-lost":"type-found"}">${item.report_type==="lost"?"LOST":"FOUND"}</span><span class="report-date">${esc(dateFmt((item.created_at||"").slice(0,10)))}</span></article>`;
}
async function loadOverview() {
  const [lost, found, matches] = await Promise.all([
    api("/api/items?report_type=lost"), api("/api/items?report_type=found"), api("/api/matches")
  ]);
  $("#lostStat").textContent = lost.length;
  $("#foundStat").textContent = found.length;
  $("#possibleStat").textContent = matches.filter(m=>!["rejected","verified"].includes(m.status)).length;
  $("#matchCount").textContent = matches.length;
  const all = [...lost,...found].sort((a,b)=>(b.created_at||"").localeCompare(a.created_at||"")).slice(0,5);
  $("#recentReports").innerHTML = all.length ? all.map(reportRow).join("") : `<div class="empty-state">No reports yet. Create the first lost or found report.</div>`;
}
async function loadReports() {
  const [lost, found] = await Promise.all([api("/api/items?report_type=lost"), api("/api/items?report_type=found")]);
  let all = [...lost,...found].sort((a,b)=>(b.created_at||"").localeCompare(a.created_at||""));
  if (reportFilter!=="all") all = all.filter(x=>x.report_type===reportFilter);
  $("#allReports").innerHTML = all.length ? all.map(reportRow).join("") : `<div class="empty-state">No active reports in this view.</div>`;
}
async function loadMatches() {
  const matches = await api("/api/matches");
  $("#matchCount").textContent = matches.length;
  if (!matches.length) {
    $("#matchesList").innerHTML = `<div class="empty-state">No candidate matches yet.<br><br>Reports stay active. A new found-item upload triggers a fresh comparison against older lost reports.</div>`;
    return;
  }
  $("#matchesList").innerHTML = matches.map(m=>{
    const score = m.score == null ? "—" : `${Number(m.score).toFixed(1)}%`;
    const signals = (m.signals||[]).map(s=>`<span class="signal">${esc(s.name.replaceAll("_"," "))}: ${Math.round(s.similarity*100)}%</span>`).join("");
    const state = m.status==="verification_pending" ? "Verification pending" : m.status==="needs_review" ? "Needs review" : m.status==="rejected" ? "Rejected" : m.status==="verified" ? "Verified" : "Candidate only";
    return `<article class="match-card">
      <div class="match-card-top"><b>Possible item match</b><span class="score">${score} <small>match score</small></span></div>
      <div class="match-pair">
        <div class="match-side">${m.lost_image?`<div class="item-thumb"><img src="${esc(m.lost_image)}" alt=""></div>`:`<div class="item-thumb">🔎</div>`}<b>Lost: ${esc(m.lost_name)}</b><small>${esc(m.lost_location||"Location unknown")}</small></div>
        <div class="match-side">${m.found_image?`<div class="item-thumb"><img src="${esc(m.found_image)}" alt=""></div>`:`<div class="item-thumb">📦</div>`}<b>Found: ${esc(m.found_name)}</b><small>${esc(m.found_location||"Location unknown")}</small></div>
      </div>
      <div class="signal-row">${signals || `<span class="signal">No comparable attributes</span>`}</div>
      <div class="match-actions"><small>Status: ${esc(state)} · Score is not ownership proof</small>${["rejected","verified"].includes(m.status)?"":`<button class="button button-dark" onclick="startVerification('${esc(m.id)}')">Verify ownership →</button>`}</div>
    </article>`;
  }).join("");
}
async function refreshAll() {
  try { await Promise.all([loadOverview(), loadReports(), loadMatches()]); }
  catch(e) { toast(e.message); }
}
function go(view) {
  currentView = view;
  $$(".view").forEach(v=>v.classList.add("hidden"));
  $(`#${view}View`).classList.remove("hidden");
  $$(".nav-item").forEach(n=>n.classList.toggle("active", n.dataset.view===view));
  $("#pageTitle").textContent = ({overview:"Overview",report:"Report an item",matches:"Possible matches",reports:"Active reports"})[view];
  if(view==="overview") loadOverview().catch(e=>toast(e.message));
  if(view==="matches") loadMatches().catch(e=>toast(e.message));
  if(view==="reports") loadReports().catch(e=>toast(e.message));
  window.scrollTo({top:0,behavior:"smooth"});
}
$$("[data-view]").forEach(b=>b.addEventListener("click",()=>go(b.dataset.view)));
$$("[data-go]").forEach(b=>b.addEventListener("click",()=>go(b.dataset.go)));
$$(".filter").forEach(b=>b.addEventListener("click",()=>{$$(".filter").forEach(x=>x.classList.remove("active"));b.classList.add("active");reportFilter=b.dataset.filter;loadReports().catch(e=>toast(e.message));}));
$("#refreshMatches").addEventListener("click",()=>api("/api/recheck",{method:"POST"}).then(()=>loadMatches()).then(()=>toast("Matching refreshed.")).catch(e=>toast(e.message)));
$$('input[name="report_type"]').forEach(r=>r.addEventListener("change",()=>{
  $("#dateLabel").textContent = r.value==="found" ? "Date found" : "Date lost";
}));
$("#image").addEventListener("change",()=>{
  const file=$("#image").files[0], preview=$("#imagePreview");
  if(!file){preview.classList.add("hidden");preview.innerHTML="";return;}
  if(file.size>8*1024*1024){toast("Image must be 8 MB or smaller.");$("#image").value="";return;}
  const url=URL.createObjectURL(file);
  preview.innerHTML=`<img src="${url}" alt="Preview"><span>${esc(file.name)}<br><small>Stored with report; AI analysis is not connected.</small></span><button type="button" class="text-button" id="removeImage">Remove</button>`;
  preview.classList.remove("hidden");
  $("#removeImage").addEventListener("click",()=>{$("#image").value="";preview.classList.add("hidden");preview.innerHTML="";});
});
$("#noFeature").addEventListener("change", e=>{
  if(e.target.checked){$$(".feature-type").forEach(c=>c.checked=false);$("#special_description").value="";}
});
$$(".feature-type").forEach(c=>c.addEventListener("change",()=>{if(c.checked)$("#noFeature").checked=false;}));
$("#special_description").addEventListener("input",()=>{if($("#special_description").value.trim())$("#noFeature").checked=false;});

$("#itemForm").addEventListener("submit", async e=>{
  e.preventDefault();
  const form = e.currentTarget;
  if (form.dataset.submitting === "true") return;
  form.dataset.submitting = "true";
  const btn=$("#submitBtn"); btn.disabled=true; btn.textContent="Saving report…";
  try {
    const fd=new FormData(form);
    const description=$("#special_description").value.trim();
    const selected=$$(".feature-type:checked").map(x=>x.value);
    const features = description ? [{feature_type:selected[0]||"other",description,owner_confirmed:true}] : [];
    fd.set("special_features",JSON.stringify(features));
    fd.set("feature_recall",$("#noFeature").checked?"unknown":(features.length?"remembered":"unknown"));
    const result=await api("/api/items",{method:"POST",body:fd});
    form.reset(); $("#imagePreview").classList.add("hidden"); $("#imagePreview").innerHTML="";
    toast(result.message || "Report saved.");
    await refreshAll(); go("reports");
  } catch(err) { toast(err.message); }
  finally { form.dataset.submitting = "false"; btn.disabled=false; btn.innerHTML='Submit report <span>→</span>'; }
});

window.startVerification = async (matchId)=>{
  try {
    const v=await api(`/api/matches/${matchId}/request-verification`,{method:"POST"});
    openVerificationModal(v.id);
    await loadMatches();
  } catch(e){toast(e.message);}
};
function openVerificationModal(verificationId){
  const root=$("#modalRoot");
  root.innerHTML=`<div class="modal-backdrop"><div class="modal">
    <h3>Ownership verification</h3>
    <p>This starts a verification case. It does not authorize the item to be returned. In this demo, a reviewer records a decision; production must enforce staff login and permissions.</p>
    <label for="vEvidence">Evidence type</label><select id="vEvidence"><option value="">Choose evidence</option><option>Private feature description</option><option>Serial number</option><option>Purchase proof</option><option>Other credible evidence</option></select>
    <label for="vNotes">Reviewer notes</label><textarea id="vNotes" rows="3" placeholder="Record what was checked. Avoid storing unnecessary sensitive data."></textarea>
    <label for="vReviewer">Reviewer name / ID</label><input id="vReviewer" placeholder="Authorized reviewer">
    <div class="modal-actions"><button class="button button-outline" id="cancelV">Cancel</button><button class="button button-dark" id="saveV">Save decision</button></div>
  </div></div>`;
  $("#cancelV").onclick=()=>root.innerHTML="";
  $("#saveV").onclick=async()=>{
    const evidence=$("#vEvidence").value, notes=$("#vNotes").value, reviewer=$("#vReviewer").value;
    if(!evidence||!reviewer.trim()){toast("Select evidence and enter reviewer name.");return;}
    const status=window.confirm("Confirm ownership is sufficiently verified and item return is authorized? Choose Cancel if more review is needed.")?"verified":"needs_review";
    try {
      await api(`/api/verifications/${verificationId}/decision`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status,evidence_type:evidence,notes,reviewer})});
      root.innerHTML="";toast(status==="verified"?"Verification recorded. Reports resolved.":"Sent for further review.");
      await refreshAll();
    } catch(err){toast(err.message);}
  };
}
const eventDateInput = $("#event_date");
if (eventDateInput) eventDateInput.max = new Date().toISOString().slice(0, 10);

api("/api/health").then(()=>{ $("#apiStatus").textContent="API connected";$(".api-status").classList.add("ok"); }).catch(()=>{ $("#apiStatus").textContent="API offline"; });
refreshAll();
