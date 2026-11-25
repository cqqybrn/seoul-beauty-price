import fs from 'node:fs';
import path from 'node:path';

export const procedures = [
  {id:'botox', name:'肉毒素', ko:'보톡스', en:'BOTOX', detail:'抚平细纹 · 咬肌轮廓管理', unit:'注射单位(U) / 部位', compareRule:'区分韩国与进口品牌 · 核对单位数', glyph:'✳'},
  {id:'filler', name:'玻尿酸', ko:'필러', en:'FILLER', detail:'容积填充 · 唇部与面部塑形', unit:'毫升（cc）', compareRule:'区分韩国与进口品牌 · 按 cc 算单价', glyph:'◒'},
  {id:'ulthera', name:'美版超声刀', ko:'울쎄라', en:'ULTHERA', detail:'聚焦超声深层提拉 · 独立设备', unit:'发（shot）', compareRule:'认准美版设备 · 按发数算单价', glyph:'⌁'},
  {id:'thermage', name:'热玛吉', ko:'써마지', en:'THERMAGE', detail:'单极射频紧肤 · 区分面部与眼部头', unit:'发（shot）', compareRule:'区分 FLX 治疗头部位与总发数', glyph:'☼'},
  {id:'shurink', name:'舒立可超声提拉', ko:'슈링크', en:'SHURINK', detail:'韩版超声提拉 · 不与美版混比', unit:'发（shot）', compareRule:'韩版独立设备 · 按发数算单价', glyph:'≋'},
  {id:'rejuran', name:'丽珠兰', ko:'리쥬란', en:'REJURAN', detail:'多核苷酸肌肤修护 · 黑盒/白盒/蓝盒', unit:'毫升（cc）', compareRule:'区分 Healer/HB/眼部型号与毫升数', glyph:'❋'},
  {id:'skinbooster', name:'水光', ko:'물광주사', en:'SKIN BOOSTER', detail:'深层补水与复合动能素管理', unit:'毫升（cc）', compareRule:'区分基础水光与复合配方容量', glyph:'◈'},
  {id:'pico', name:'皮秒', ko:'피코', en:'PICO LASER', detail:'色素净肤与蜂巢毛孔点阵管理', unit:'次（session）', compareRule:'区分 PicoSure/PicoWay 设备与全脸范围', glyph:'✦'},
  {id:'inmode', name:'InMode 射频', ko:'인모드', en:'INMODE', detail:'FX 溶脂塑形与 FORMA 紧致双模式', unit:'次 / 部位', compareRule:'区分单模式/双模式及施术部位', glyph:'◎'},
  {id:'potenza', name:'黄金微针', ko:'포텐자', en:'POTENZA', detail:'微针射频毛孔紧致 · 核对导入探头', unit:'次（session）', compareRule:'核对是否含独立探头及导入药水', glyph:'⁙'},
];

export type Offer = {
  id:number; procedure_id:string; brand_id:string|null; tier:string; quantity:number|null;
  unit:string|null; sessions:number; is_bundle:number; price_from:number; vat:string;
  unit_price_krw:number|null; price_krw:number; coupon_price_krw:number|null;
  source:string; observed_date:string; clinic_id:number; clinic_name:string; address:string;
  conditions:string[]; extra_fees:string[]; url:string; label:string;
  history?:{date:string;price_krw:number}[];
  option_name?:string; event_title?:string; option_name_zh?:string|null; event_title_zh?:string|null; clinic_name_zh?:string|null;
};

export type Catalog = {
  report_preview?:boolean;
  raw_options?:{option_name_zh?:string|null;event_title_zh?:string|null;clinic_name_zh?:string|null;id:number;option_name:string;sessions_raw:string;price_krw:number;coupon_price_krw:number|null;vat:string;event_id:number;event_title:string;source:string;url:string;observed_date:string;clinic_id:number;clinic_name:string;address:string}[];
  mode:'live'|'empty'; generated_at:string|null; offers:Offer[];
  clinics:{name_zh?:string|null;id:number;name:string;address:string;registered:boolean|null; urls:string[]}[];
  rate:{krw_cny:number;date:string}|null; stale_sources:Record<string,string>;
  bucket_stats?:{bucket_key:string;n:number;p5:number;p25:number;median:number;p75:number}[];
  report:{date:string; sections:{title:string; entries:{id:number;note:string;price_krw:number;clinic_name:string;clinic_name_zh?:string|null}[]}[]}|null;
};
const file = process.env.SITE_DATA_PATH || path.resolve('src/data/generated.json');
export const catalog:Catalog = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file,'utf8')) : {
  mode:'empty', generated_at:null, offers:[], clinics:[], rate:null, stale_sources:{}, report:null,
};

export const tierNames:Record<string,string> = {import:'进口品牌', domestic:'韩国品牌', single:'专用设备 / 型号', unknown:'品牌待确认'};
export const conditionNames:Record<string,string> = {first_visit:'仅限初诊',weekday_only:'仅限工作日',time_limited:'限时',designated_doctor:'指定医生',korean_only:'仅限韩国人',foreigner_ok:'外国人适用',student_only:'学生限定',app_pay_only:'App 支付',review_required:'需评价'};
export const unitNames:Record<string,string> = {shot:'发', unit:'注射单位', cc:'毫升（cc）', session:'次', area:'部位', vial:'瓶'};
export const krw = (n:number) => '₩'+new Intl.NumberFormat('zh-CN',{maximumFractionDigits:0}).format(Math.round(n));
export const cny = (n:number) => catalog.rate ? '≈ ¥'+new Intl.NumberFormat('zh-CN',{maximumFractionDigits:0}).format(n*catalog.rate.krw_cny) : '人民币汇率待更新';
export const cnyUnit = (n:number) => {
  if (!catalog.rate) return '人民币汇率待更新';
  const val = n * catalog.rate.krw_cny;
  const digits = val < 20 ? 1 : 0;
  return '≈ ¥' + new Intl.NumberFormat('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(val);
};
export const tenThousandKrwCny = () => catalog.rate ? new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(10000 * catalog.rate.krw_cny) : null;

export const sourceNames:Record<string,string>={yeoshin:'女神门票',babitalk:'Babitalk（芭比通）'};
export const brandNames:Record<string,string>={botulax:'Botulax',nabota:'娜保塔 Nabota',liztox:'Liztox',meditoxin:'Meditoxin',coretox:'Coretox',wondertox:'Wondertox',allergan:'保妥适 Allergan',xeomin:'西马 Xeomin',dysport:'吉适 Dysport',neuramis:'纽拉美斯',elravie:'Elravie',yvoire:'伊婉',atier:'Atier',juvederm:'乔雅登',restylane:'瑞蓝',belotero:'保柔缇',ulthera:'Ulthera 美版超声刀',thermage:'Thermage 热玛吉',shurink:'Shurink 舒立可',healer:'丽珠兰 Healer',hb:'丽珠兰 HB',eye:'丽珠兰眼部型',s:'丽珠兰 S 型',picosure:'蜂巢皮秒 PicoSure',picoway:'超皮秒 PicoWay',picoplus:'PicoPlus',inmode:'InMode',potenza:'Potenza 黄金微针'};
const SEOUL_AREAS:Record<string,string>={'강남구':'江南区','서초구':'瑞草区','마포구':'麻浦区','송파구':'松坡区','종로구':'钟路区','중구':'中区','영등포구':'永登浦区','강서구':'江西区','관악구':'冠岳区','노원구':'芦原区','은평구':'恩平区','성동구':'城东区','용산구':'龙山区','강동구':'江东区','광진구':'广津区','동작구':'铜雀区','서대문구':'西大门区','동대문구':'东大门区','성북구':'城北区','강북구':'江北区','도봉구':'道峰区','양천구':'阳川区','구로구':'九老区','금천구':'衿川区','중랑구':'中浪区'};
export const shortAreaName=(address:string)=>Object.entries(SEOUL_AREAS).find(([ko])=>address.includes(ko))?.[1]||'首尔其他区';
export const areaName=(address:string)=>'首尔 · '+(Object.entries(SEOUL_AREAS).find(([ko])=>address.includes(ko))?.[1]||'地区待确认');
export const consumerTitle=(o:Offer)=>o.option_name_zh||`${procedures.find(p=>p.id===o.procedure_id)?.name||'医美项目'} · ${o.quantity??'规格待翻译'}${o.quantity?unitNames[o.unit||'']:''}`;
export const clinicTitle=(o:{clinic_name_zh?:string|null;clinic_name:string})=>o.clinic_name_zh||'机构中文参考名待补充';
export const offerGroup=(o:Offer)=>o.is_bundle?'bundle':o.label==='anomaly_low'?'anomaly':o.conditions.length?'conditional':o.unit_price_krw===null?'unranked':'default';
export const specText=(o:Offer)=>`${o.quantity!==null?`${o.quantity} ${unitNames[o.unit||'']||''} / 次`:'剂量需向医院确认'} · 共 ${o.sessions} 次`;
export const trustedSample=(o:Offer)=>!o.is_bundle&&!o.price_from&&!o.conditions.length&&!o.extra_fees.length&&o.unit_price_krw!==null&&o.tier!=='unknown'&&o.label!=='anomaly_low';

export const categoryQueries:Record<string,string>={botox:'肉毒|保妥适|보톡스',filler:'玻尿酸|필러',ulthera:'美版超声刀|울쎄라|ulthera',thermage:'热玛吉|써마지|thermage',shurink:'舒立可|슈링크|shurink',rejuran:'丽珠兰|리쥬란|rejuran',skinbooster:'水光|물광',pico:'皮秒|피코|pico',inmode:'inmode|인모드',potenza:'黄金微针|포텐자|potenza'};
export const detectProcedure=(text:string)=>{
  const lower = text.toLowerCase();
  for (const p of procedures) {
    const terms = (categoryQueries[p.id] || '').split('|').filter(Boolean);
    if (terms.some(t => lower.includes(t.toLowerCase()))) return p;
  }
  return null;
};
