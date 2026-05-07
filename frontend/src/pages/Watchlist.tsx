/**
 * Watchlist — live prices, sparklines, drag-to-reorder, inline alert creation.
 *
 * Wires to: GET    /api/watchlist
 *           POST   /api/watchlist/{symbol}
 *           DELETE /api/watchlist/{symbol}
 *           GET    /api/watchlist/prices
 *           POST   /api/watchlist/reorder
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { watchlistApi, api } from '../hooks/useApi';
import { useStore } from '../store';
import { PageHeader, EmptyState, CrossLinkBar } from '../components';
import { useToast } from '../components/Toast';
import { useFlashHighlight } from '../hooks/useFlashHighlight';

interface WatchlistItem {
  symbol: string;
  bid: number;
  ask: number;
  mid: number;
  change_pct: number;
  timestamp: number;
  history: number[];
}

const AVAILABLE_SYMBOLS = [
  'XAUUSD','EURUSD','GBPUSD','USDJPY','BTCUSD',
  'ETHUSD','USDCAD','AUDUSD','USDCHF','NZDUSD',
  'XAGUSD','US30','SPX500','NAS100','USOIL',
];

const ASSET_CLASS: Record<string,string> = {
  EURUSD:'Forex',GBPUSD:'Forex',USDJPY:'Forex',AUDUSD:'Forex',
  USDCAD:'Forex',USDCHF:'Forex',NZDUSD:'Forex',EURGBP:'Forex',
  XAUUSD:'Metals',XAGUSD:'Metals',
  BTCUSD:'Crypto',ETHUSD:'Crypto',
  US30:'Indices',SPX500:'Indices',NAS100:'Indices',GER40:'Indices',
  USOIL:'Commodities',UKOIL:'Commodities',
};

function getAssetClass(sym: string): string { return ASSET_CLASS[sym] ?? 'Other'; }

function formatPrice(symbol: string, price: number): string {
  if (symbol.includes('JPY')) return price.toFixed(2);
  if (['BTC','ETH','XAU','XAG','US30','SPX','NAS'].some(s => symbol.includes(s))) return price.toFixed(2);
  return price.toFixed(5);
}

const Sparkline: React.FC<{ history: number[] }> = ({ history }) => {
  if (history.length < 2) return (
    <svg width={60} height={32} className="block"><line x1={0} y1={16} x2={60} y2={16} stroke="#334155" strokeWidth={1.5}/></svg>
  );
  const last=history[history.length-1]!,first=history[0]!;
  const up=last>=first,color=up?'#4ade80':'#f87171';
  const min=Math.min(...history),max=Math.max(...history),range=max-min||1;
  const norm=history.map(p=>((p-min)/range)*28+2);
  const n=norm.length-1;
  const path=norm.map((y,i)=>`${i===0?'M':'L'}${(i/n)*60},${30-y}`).join(' ');
  return <svg width={60} height={32} className="block"><path d={path} fill="none" stroke={color} strokeWidth={1.5}/></svg>;
};

const InlineAlertModal: React.FC<{symbol:string;currentPrice:number;onClose:()=>void;onCreated:()=>void}> = ({symbol,currentPrice,onClose,onCreated}) => {
  const toast=useToast();
  const [price,setPrice]=useState(String(currentPrice.toFixed(4)));
  const [condition,setCond]=useState<'above'|'below'>('above');
  const [channel,setChannel]=useState<'email'|'discord'|'telegram'>('email');
  const [saving,setSaving]=useState(false);
  const handleCreate=async()=>{
    setSaving(true);
    try {
      await api.post('/alerts/',{symbol,condition,price:parseFloat(price),channels:[channel],message:`${symbol} ${condition} ${price}`});
      toast.success(`Alert set: ${symbol} ${condition} ${price}`);
      onCreated();onClose();
    } catch { toast.error('Failed to create alert.'); }
    finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div className="bg-terminal-surface border border-terminal-border rounded-xl p-6 w-80 flex flex-col gap-4" onClick={e=>e.stopPropagation()}>
        <div className="flex justify-between items-center">
          <span className="font-bold text-slate-100 text-sm">🔔 Alert — {symbol}</span>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-xl leading-none bg-transparent border-none cursor-pointer">×</button>
        </div>
        <div className="flex gap-2">
          {(['above','below'] as const).map(c=>(
            <button key={c} onClick={()=>setCond(c)} className={`flex-1 py-1.5 rounded-md text-xs font-semibold border cursor-pointer transition-all ${condition===c?'bg-blue-500/20 border-blue-500 text-blue-400':'bg-transparent border-terminal-border text-slate-500 hover:border-slate-500'}`}>
              {c==='above'?'▲ Above':'▼ Below'}
            </button>
          ))}
        </div>
        <input type="number" value={price} onChange={e=>setPrice(e.target.value)} step="0.0001"
          className="bg-terminal-bg border border-terminal-border rounded-md text-slate-100 text-sm px-3 py-2 font-mono outline-none focus:border-blue-500"/>
        <div className="flex gap-2">
          {(['email','discord','telegram'] as const).map(ch=>(
            <button key={ch} onClick={()=>setChannel(ch)} className={`flex-1 py-1.5 rounded-md text-xs font-semibold border cursor-pointer transition-all ${channel===ch?'bg-amber-500/10 border-amber-500 text-amber-400':'bg-transparent border-terminal-border text-slate-500 hover:border-slate-500'}`}>
              {ch}
            </button>
          ))}
        </div>
        <button onClick={handleCreate} disabled={saving||!price}
          className="py-2 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 border-none rounded-lg text-white text-sm font-bold cursor-pointer transition-colors">
          {saving?'Creating…':'Create Alert'}
        </button>
      </div>
    </div>
  );
};

const WatchlistRow: React.FC<{
  item:WatchlistItem;onRemove:(s:string)=>void;onAlert:(s:string,p:number)=>void;
  onDragStart:()=>void;onDragEnter:()=>void;onDragEnd:()=>void;
}> = ({item,onRemove,onAlert,onDragStart,onDragEnter,onDragEnd}) => {
  const flash=useFlashHighlight(item.mid);
  const spread=item.ask-item.bid;
  const spreadPips=item.symbol.includes('JPY')?spread*100:spread*10000;
  return (
    <div draggable onDragStart={onDragStart} onDragEnter={onDragEnter} onDragEnd={onDragEnd} onDragOver={e=>e.preventDefault()}
      className="flex items-center px-4 py-3 border-b border-terminal-border/60 hover:bg-terminal-raised/50 group transition-colors"
      style={{background:flash!=='transparent'?flash:undefined,transition:'background 0.4s ease'}}>
      <span className="text-terminal-border cursor-grab text-sm px-1.5 select-none mr-1 group-hover:text-slate-500">⠿</span>
      <Link to="/ai-chart" state={{symbol:item.symbol}}
        className="flex-1 flex items-center gap-2 font-bold text-slate-100 no-underline hover:text-neon-blue transition-colors min-w-0">
        <span className="truncate">{item.symbol}</span>
        <span className="text-2xs text-slate-500 bg-terminal-bg border border-terminal-border rounded px-1 py-0.5 shrink-0">{getAssetClass(item.symbol)}</span>
        <span className="text-slate-600 text-xs">↗</span>
      </Link>
      <span className="w-24 text-right text-red-400 text-sm font-semibold font-mono tabular-nums">{formatPrice(item.symbol,item.bid)}</span>
      <span className="w-24 text-right text-green-400 text-sm font-semibold font-mono tabular-nums">{formatPrice(item.symbol,item.ask)}</span>
      <span className="w-20 text-right text-slate-500 text-xs font-mono tabular-nums" title="Spread">{spreadPips.toFixed(1)}p</span>
      <span className="w-24 text-right text-slate-100 text-sm font-bold font-mono tabular-nums">{formatPrice(item.symbol,item.mid)}</span>
      <span className={`w-20 text-right text-sm font-semibold tabular-nums ${item.change_pct>=0?'text-green-400':'text-red-400'}`}>
        {item.change_pct>=0?'+':''}{item.change_pct.toFixed(2)}%
      </span>
      <span className="w-16 flex justify-center"><Sparkline history={item.history}/></span>
      <span className="w-36 flex items-center justify-center gap-1.5">
        <Link to="/trade" state={{signal:{symbol:item.symbol.slice(0,3)+'/'+item.symbol.slice(3)}}}
          className="bg-blue-500/15 border border-blue-500/35 rounded px-2 py-0.5 text-blue-400 text-xs font-bold no-underline hover:bg-blue-500/25 transition-colors" title={`Trade ${item.symbol}`}>⚡</Link>
        <button onClick={()=>onAlert(item.symbol,item.mid)}
          className="bg-transparent border-none text-amber-400 text-sm cursor-pointer px-0.5 hover:text-amber-300 transition-colors" title="Set alert">🔔</button>
        <button onClick={()=>onRemove(item.symbol)}
          className="bg-transparent border-none text-slate-600 hover:text-red-400 text-lg cursor-pointer leading-none px-1 transition-colors" title="Remove">×</button>
      </span>
    </div>
  );
};

const WatchlistPage: React.FC = () => {
  const storePrices=useStore(s=>s.prices);
  const toast=useToast();
  const [items,setItems]=useState<WatchlistItem[]>([]);
  const [loading,setLoading]=useState(true);
  const [addSymbol,setAddSymbol]=useState('');
  const [adding,setAdding]=useState(false);
  const [error,setError]=useState('');
  const [groupByAsset,setGroupByAsset]=useState(false);
  const [alertModal,setAlertModal]=useState<{symbol:string;price:number}|null>(null);
  const dragItem=useRef<number|null>(null);
  const dragOverItem=useRef<number|null>(null);
  const mountedRef=useRef(true);
  useEffect(()=>{mountedRef.current=true;return()=>{mountedRef.current=false;};},[]);

  const normalise=(item:Omit<WatchlistItem,'history'>&{history?:number[]}):WatchlistItem=>({...item,history:item.history??[]});

  const fetchWatchlist=useCallback(async()=>{
    try {
      const res=await watchlistApi.list() as {data:{items:Array<Omit<WatchlistItem,'history'>&{history?:number[]}>}};
      if(!mountedRef.current)return;
      if(res.data.items?.length)setItems(res.data.items.map(normalise));
    } catch { /* show empty */ }
    finally { if(mountedRef.current)setLoading(false); }
  },[]);

  useEffect(()=>{
    fetchWatchlist();
    const id=setInterval(async()=>{
      try {
        const res=await watchlistApi.prices() as {data:Array<Omit<WatchlistItem,'history'>&{history?:number[]}>};
        if(Array.isArray(res.data)&&res.data.length>0)setItems(res.data.map(normalise));
      } catch { /* keep existing */ }
    },5000);
    return()=>clearInterval(id);
  },[fetchWatchlist]);

  const enrichedItems:WatchlistItem[]=items.map(item=>{
    const slashKey=item.symbol.replace('XAUUSD','XAU/USD').replace('EURUSD','EUR/USD').replace('GBPUSD','GBP/USD').replace('USDJPY','USD/JPY').replace('BTCUSD','BTC/USD').replace('ETHUSD','ETH/USD');
    const tick=storePrices[slashKey]??storePrices[item.symbol];
    if(!tick)return item;
    return{...item,bid:tick.bid,ask:tick.ask,mid:tick.mid,change_pct:tick.change_pct,timestamp:tick.timestamp,history:[...item.history,tick.mid].slice(-60)};
  });

  const handleAdd=async()=>{
    const sym=addSymbol.trim().toUpperCase();
    if(!sym)return;
    setAdding(true);setError('');
    try {
      await watchlistApi.add(sym);
      setAddSymbol('');await fetchWatchlist();toast.success(`${sym} added.`);
    } catch(err:unknown){
      const status=(err as{response?:{status?:number}})?.response?.status;
      const msg=status===409?`${sym} already in watchlist`:`Failed to add ${sym}`;
      setError(msg);toast.error(msg);
    } finally{setAdding(false);}
  };

  const handleRemove=async(symbol:string)=>{
    try {
      await watchlistApi.remove(symbol);
      setItems(prev=>prev.filter(i=>i.symbol!==symbol));
      toast.success(`${symbol} removed.`);
    } catch(err:unknown){
      const msg=err instanceof Error?err.message:`Failed to remove ${symbol}.`;
      setError(msg);toast.error(msg);
    }
  };

  const handleDragStart=(index:number)=>{dragItem.current=index;};
  const handleDragEnter=(index:number)=>{dragOverItem.current=index;};
  const handleDragEnd=()=>{
    if(dragItem.current===null||dragOverItem.current===null)return;
    if(dragItem.current===dragOverItem.current)return;
    const reordered=[...items];
    const[moved]=reordered.splice(dragItem.current,1);
    reordered.splice(dragOverItem.current,0,moved!);
    setItems(reordered);dragItem.current=null;dragOverItem.current=null;
    watchlistApi.reorder?.(reordered.map(i=>i.symbol)).catch(()=>{});
  };

  const displayItems=groupByAsset?[...enrichedItems].sort((a,b)=>getAssetClass(a.symbol).localeCompare(getAssetClass(b.symbol))):enrichedItems;
  const groups=groupByAsset?Array.from(new Set(displayItems.map(i=>getAssetClass(i.symbol)))):['All'];

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      {alertModal&&<InlineAlertModal symbol={alertModal.symbol} currentPrice={alertModal.price} onClose={()=>setAlertModal(null)} onCreated={()=>setAlertModal(null)}/>}

      <PageHeader title="Watchlist" icon="👁️" subtitle="Live prices. Drag to reorder. Click symbol to open chart."
        breadcrumbs={[{label:'Dashboard',href:'/dashboard'},{label:'Watchlist'}]}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={()=>setGroupByAsset(g=>!g)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border cursor-pointer transition-all ${groupByAsset?'bg-violet-500/20 border-violet-500 text-violet-400':'bg-transparent border-violet-500/30 text-violet-400 hover:bg-violet-500/10'}`}>
              {groupByAsset?'⊞ Ungrouped':'⊟ Group by Asset'}
            </button>
            <Link to="/ai-chart" className="px-3 py-1.5 bg-blue-500/12 border border-blue-500/30 rounded-lg text-blue-400 text-xs font-semibold no-underline hover:bg-blue-500/20 transition-colors">📈 Charts</Link>
            <Link to="/alerts"   className="px-3 py-1.5 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400 text-xs font-semibold no-underline hover:bg-amber-500/20 transition-colors">🔔 Alerts</Link>
            <Link to="/trade"    className="px-3 py-1.5 bg-green-500/12 border border-green-500/30 rounded-lg text-green-400 text-xs font-semibold no-underline hover:bg-green-500/20 transition-colors">⚡ Trade</Link>
          </div>
        }/>

      {/* Add row */}
      <div className="flex items-center gap-3 mb-5">
        <select value={addSymbol} onChange={e=>setAddSymbol(e.target.value)}
          className="bg-terminal-raised border border-terminal-border rounded-lg text-slate-100 px-3 py-2 text-sm outline-none focus:border-blue-500 cursor-pointer">
          <option value="">Add symbol…</option>
          {AVAILABLE_SYMBOLS.filter(sym=>!items.find(i=>i.symbol===sym)).map(sym=><option key={sym} value={sym}>{sym}</option>)}
        </select>
        <button onClick={handleAdd} disabled={!addSymbol||adding}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 border-none rounded-lg text-white text-sm font-semibold cursor-pointer transition-colors">
          {adding?'…':'+ Add'}
        </button>
        {error&&<span className="text-red-400 text-sm">{error}</span>}
      </div>

      {loading?(
        <div className="bg-terminal-surface border border-terminal-border rounded-xl overflow-hidden">
          {Array.from({length:5}).map((_,i)=><div key={i} className="h-14 border-b border-terminal-border/60 animate-pulse bg-terminal-surface"/>)}
        </div>
      ):enrichedItems.length===0?(
        <EmptyState icon="👁" title="Your watchlist is empty"
          description="Track live prices for your favourite instruments. Use the dropdown above to add symbols."
          action={<div className="flex gap-2">
            <Link to="/ai-chart" className="px-4 py-2 bg-blue-600 rounded-lg text-white text-sm font-semibold no-underline hover:bg-blue-500 transition-colors">📈 Browse Charts</Link>
            <Link to="/signals"  className="px-4 py-2 bg-transparent border border-terminal-border rounded-lg text-slate-400 text-sm no-underline hover:border-slate-500 transition-colors">📡 Signals</Link>
          </div>}
          links={[{label:'📊 Portfolio',href:'/portfolio'},{label:'📓 Journal',href:'/journal'},{label:'⚡ Trade',href:'/trade'}]}/>
      ):(
        <div className="bg-terminal-surface border border-terminal-border rounded-xl overflow-hidden">
          {/* Header */}
          <div className="flex items-center px-4 py-2.5 border-b border-terminal-border bg-terminal-bg text-2xs font-semibold uppercase tracking-widest text-slate-500">
            <span className="w-5 mr-1"/>
            <span className="flex-1">Symbol</span>
            <span className="w-24 text-right">Bid</span>
            <span className="w-24 text-right">Ask</span>
            <span className="w-20 text-right">Spread</span>
            <span className="w-24 text-right">Mid</span>
            <span className="w-20 text-right">Change</span>
            <span className="w-16 text-center">Trend</span>
            <span className="w-36 text-center">Actions</span>
          </div>
          {groups.map(group=>{
            const groupItems=groupByAsset?displayItems.filter(i=>getAssetClass(i.symbol)===group):displayItems;
            return(
              <div key={group}>
                {groupByAsset&&<div className="px-4 py-1.5 bg-terminal-bg/80 border-b border-terminal-border/60 text-2xs font-bold text-slate-600 uppercase tracking-widest">{group} ({groupItems.length})</div>}
                {groupItems.map(item=>{
                  const globalIdx=displayItems.indexOf(item);
                  return(
                    <WatchlistRow key={item.symbol} item={item} onRemove={handleRemove}
                      onAlert={(sym,price)=>setAlertModal({symbol:sym,price})}
                      onDragStart={()=>handleDragStart(globalIdx)}
                      onDragEnter={()=>handleDragEnter(globalIdx)}
                      onDragEnd={handleDragEnd}/>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      {enrichedItems.length>0&&(
        <div className="flex items-center gap-3 mt-3 px-1 text-xs text-slate-600">
          <span>{enrichedItems.length} symbol{enrichedItems.length!==1?'s':''}</span>
          <span>·</span>
          <span className="text-green-500">{enrichedItems.filter(i=>i.change_pct>=0).length} up</span>
          <span>·</span>
          <span className="text-red-400">{enrichedItems.filter(i=>i.change_pct<0).length} down</span>
        </div>
      )}

      <CrossLinkBar title="Related" style={{marginTop:24}} links={[
        {label:'📊 Portfolio',    href:'/portfolio',  color:'#60a5fa'},
        {label:'📈 AI Charts',    href:'/ai-chart',   color:'#a78bfa'},
        {label:'📡 Signals',      href:'/signals',    color:'#34d399'},
        {label:'📓 Trade Journal',href:'/journal',    color:'#fbbf24'},
        {label:'🔔 Price Alerts', href:'/alerts',     color:'#f97316'},
        {label:'⚡ Trade',        href:'/trade',      color:'#4ade80'},
      ]}/>
    </div>
  );
};

export default WatchlistPage;
