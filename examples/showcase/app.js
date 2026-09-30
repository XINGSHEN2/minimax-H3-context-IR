const $=selector=>document.querySelector(selector);
const GROUP_ORDER=['raw','local_ir','official_ir'],GROUP_LABELS={raw:'Raw',local_ir:'本地 IR',official_ir:'官方 IR'};
function node(tag,text){const element=document.createElement(tag);if(text!==undefined)element.textContent=text;return element}
function normalizedTitle(title){return title.replace(/^Case\s*\d+\s*[·・:\-]?\s*/i,'')}
async function textFile(path){if(!path)return '暂无 Prompt';try{const response=await fetch(path);if(!response.ok)throw Error();return await response.text()}catch{return '读取失败'}}
function groupMap(groups){const localKey=Object.keys(groups).find(key=>key!=='raw'&&key!=='official_ir');return{raw:groups.raw,local_ir:groups[localKey],official_ir:groups.official_ir}}
function renderAssets(item){
 const section=node('section');section.className='asset-section';section.append(node('h3','参考素材'));const gallery=node('div');gallery.className='assets';
 for(const asset of item.assets||[]){const card=node('div');card.className='asset-card';const media=node(asset.type==='video'?'video':'img');media.src=asset.src;if(asset.type==='video'){media.controls=true;media.preload='metadata';media.muted=true;media.playsInline=true}else{media.alt=asset.label;media.loading='lazy'}const link=node('a',asset.label);link.href=asset.src;link.target='_blank';link.rel='noopener';card.append(media,link);gallery.append(card)}
 if(!gallery.children.length)gallery.append(node('p','未提供参考素材。'));section.append(gallery);return section
}
function renderResult(group,key){
 const card=node('article');card.className='result-card';const head=node('div');head.className='card-head';head.append(node('h3',GROUP_LABELS[key]));const badge=node('span',group?.status==='ready'?'已完成':'缺失');badge.className='badge';head.append(badge);card.append(head);
 if(group?.video){const video=node('video');video.controls=true;video.muted=true;video.playsInline=true;video.preload='metadata';video.src=group.video;card.append(video)}else{const missing=node('div','未提供');missing.className='missing';card.append(missing)}
 if(group?.size)card.append(node('p',group.size));
 if(group?.prompt){const details=node('details'),pre=node('pre','加载中…');details.append(node('summary','查看 Prompt'),pre);card.append(details);textFile(group.prompt).then(text=>{pre.textContent=text})}else card.append(node('p','未提供独立 Prompt。'));
 return card
}
function renderCase(item,index){
 const number=String(index+1).padStart(2,'0'),section=node('section');section.className='case-section';section.id=`case-${number}`;
 const heading=node('div');heading.className='case-heading';const numberNode=node('span',number);numberNode.className='case-number';const copy=node('div'),title=node('h2',`Case ${index+1}`);title.style.fontSize='clamp(17px,1.8vw,22px)';copy.append(node('p',item.category),title);if(item.description)copy.append(node('div',item.description));heading.append(numberNode,copy);section.append(heading,renderAssets(item));
 const variant=item.variants[Object.keys(item.variants)[0]],groups=groupMap(variant.groups),grid=node('section');grid.className='result-grid';for(const key of GROUP_ORDER)grid.append(renderResult(groups[key],key));section.append(grid);return section
}
async function init(){
 const response=await fetch('cases.json', {cache: 'no-store'});if(!response.ok)throw Error('案例清单读取失败');const data=await response.json(),container=$('#cases'),nav=$('#caseNav');let ready=0,total=0;
 data.cases.forEach((item,index)=>{const number=String(index+1).padStart(2,'0');container.append(renderCase(item,index));const link=node('a',number);link.href=`#case-${number}`;link.title=normalizedTitle(item.title);nav.append(link);const variant=item.variants[Object.keys(item.variants)[0]];for(const group of Object.values(groupMap(variant.groups))){total+=1;if(group?.status==='ready')ready+=1}});
 $('#availability').textContent=`${data.cases.length} 个案例 · ${ready}/${total} 个视频可用`
}
init().catch(error=>{$('#availability').textContent=error.message});
