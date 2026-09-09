const state={data:null,caseIndex:0,variant:'original',generation:0},$=s=>document.querySelector(s),videos=()=>[...document.querySelectorAll('#comparison video')];
async function textFile(path){if(!path)return '暂无 Prompt';try{const r=await fetch(path);if(!r.ok)throw Error();return await r.text()}catch{return '读取失败'}}
function node(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n}
async function render(){
 const generation=++state.generation,item=state.data.cases[state.caseIndex];
 if(!item.variants[state.variant])state.variant=Object.keys(item.variants)[0];
 const variant=item.variants[state.variant];$('#caseTitle').textContent=item.title;
 $('#caseNote').textContent=item.description||'';
 document.querySelectorAll('video').forEach(v=>v.pause());
 const gallery=$('#assets');gallery.replaceChildren();
 for(const asset of item.assets||[]){const card=node('div');card.className='asset-card';const media=node(asset.type==='video'?'video':'img');media.src=asset.src;if(asset.type==='video'){media.controls=true;media.preload='metadata';media.muted=true;media.playsInline=true}else{media.alt=asset.label;media.loading='lazy'}const link=node('a',asset.label);link.href=asset.src;link.target='_blank';link.rel='noopener';card.append(media,link);gallery.append(card)}
 $('#assetSection').hidden=!gallery.children.length;
 const tabs=$('.tabs');tabs.replaceChildren();
 for(const key of Object.keys(item.variants)){const button=node('button',item.variants[key].label||({vague:'模糊需求',detailed:'详细需求',original:'原始需求'})[key]||key);button.classList.toggle('active',key===state.variant);button.onclick=()=>{state.variant=key;render()};tabs.append(button)}
 tabs.hidden=Object.keys(item.variants).length===1;
 const entries=Object.entries(variant.groups);$('#availability').textContent=`${entries.filter(([,g])=>g.status==='ready').length}/${entries.length} 个视频可用`;
 const grid=$('#comparison');grid.replaceChildren();
 for(const [,group]of entries){
  const card=node('article');card.className='card';const head=node('div');head.className='card-head';head.append(node('h3',group.label));const badge=node('span',group.status==='ready'?'已完成':'缺失');badge.className='badge';head.append(badge);card.append(head);
  if(group.video){const video=node('video');video.controls=true;video.muted=true;video.playsInline=true;video.preload='metadata';video.loop=$('#loopAll').checked;video.src=group.video;card.append(video)}else{const missing=node('div','未提供');missing.className='missing';card.append(missing)}
  if(group.duration_seconds){const info=node('p',`${group.size} · 实际 ${group.duration_seconds} 秒`);info.style.cssText='padding:8px 16px;color:#98a2b3';card.append(info)}
  const details=node('details'),pre=node('pre','加载中…');details.append(node('summary','查看 Prompt'),pre);if(group.prompt)card.append(details);else card.append(node('p','参考成片仅供效果对照；未提供独立 Prompt。'));
  const links=node('div');links.className='links';for(const [path,label]of [[group.context_ir,'Context-IR'],[group.content_plan,'内容计划'],[group.request,'请求参数'],[group.video,'打开视频']])if(path){const a=node('a',label);a.href=path;a.target='_blank';a.rel='noopener';links.append(a)}card.append(links);grid.append(card);
  textFile(group.prompt).then(text=>{if(generation===state.generation)pre.textContent=text});
 }
}
function selectCategory(){const select=$('#caseSelect');select.replaceChildren();state.data.cases.forEach((c,i)=>{if(c.category===$('#categorySelect').value)select.add(new Option(c.title,i))});state.caseIndex=Number(select.value);render()}
async function init(){
 const response=await fetch('cases.json');if(!response.ok)throw Error('案例清单读取失败');state.data=await response.json();
 for(const c of state.data.cases)c.category=c.category||'原有 A/B 测试案例';
 const categories=[...new Set(state.data.cases.map(c=>c.category))];categories.sort((a,b)=>a.localeCompare(b,'zh-CN'));
 categories.forEach(c=>$('#categorySelect').add(new Option(c,c)));$('#categorySelect').value=state.data.default_category||categories[0];
 $('#categorySelect').onchange=selectCategory;$('#caseSelect').onchange=()=>{state.caseIndex=Number($('#caseSelect').value);render()};
 const play=v=>v.play().catch(()=>{});$('#playAll').onclick=()=>videos().forEach(play);$('#pauseAll').onclick=()=>videos().forEach(v=>v.pause());$('#restartAll').onclick=()=>videos().forEach(v=>{v.currentTime=0;play(v)});$('#loopAll').onchange=e=>videos().forEach(v=>v.loop=e.target.checked);selectCategory();
}init().catch(error=>{$('#availability').textContent=error.message});
