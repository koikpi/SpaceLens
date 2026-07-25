"use client";

import { useMemo, useState } from "react";

type Node = {
  name: string;
  size: number;
  color: string;
  type?: string;
  children?: Node[];
};

const roots: Node[] = [
  {
    name: "C:",
    size: 512,
    color: "#5d7cff",
    children: [
      {
        name: "Users",
        size: 214,
        color: "#5678f5",
        children: [
          { name: "Videos", size: 83, color: "#8d63ff", type: "MP4" },
          { name: "Downloads", size: 61, color: "#e46696", type: "ZIP" },
          { name: "Documents", size: 39, color: "#46b9ae", type: "DOCX" },
          { name: "AppData", size: 31, color: "#dd8d44", type: "DATA" },
        ],
      },
      { name: "Windows", size: 96, color: "#4e9be6", type: "SYS" },
      { name: "Program Files", size: 72, color: "#45b77c", type: "APP" },
      { name: "Games", size: 58, color: "#ef9c47", type: "GAME" },
      { name: "Other", size: 28, color: "#6d7a8d", type: "OTHER" },
    ],
  },
  {
    name: "D:",
    size: 1024,
    color: "#9b64ff",
    children: [
      { name: "Media", size: 376, color: "#8d63ff", type: "MKV" },
      { name: "Projects", size: 244, color: "#42b7a8", type: "SOURCE" },
      { name: "Archives", size: 160, color: "#e46696", type: "ZIP" },
      { name: "Photos", size: 132, color: "#e2a442", type: "JPG" },
      { name: "Backup", size: 112, color: "#557cf1", type: "BAK" },
    ],
  },
  {
    name: "E:",
    size: 2048,
    color: "#37ae83",
    children: [
      { name: "Backup 2025", size: 742, color: "#557cf1", type: "BAK" },
      { name: "Footage", size: 612, color: "#8d63ff", type: "MOV" },
      { name: "Assets", size: 394, color: "#e2a442", type: "PSD" },
      { name: "VMs", size: 300, color: "#4e9be6", type: "VHDX" },
    ],
  },
];

const formats = [
  ["视频", "1.08 TB", 36, "#8d63ff"],
  ["压缩包", "624 GB", 21, "#e46696"],
  ["系统文件", "442 GB", 15, "#4e9be6"],
  ["图片", "328 GB", 11, "#e2a442"],
  ["应用", "286 GB", 10, "#45b77c"],
  ["其他", "207 GB", 7, "#68768a"],
];

function fmt(n: number) {
  return n >= 1024 ? `${(n / 1024).toFixed(2)} TB` : `${n} GB`;
}

function Treemap({ nodes, onOpen }: { nodes: Node[]; onOpen: (n: Node) => void }) {
  const total = nodes.reduce((a, n) => a + n.size, 0);
  return (
    <div className="treemap" role="list" aria-label="磁盘占用矩形树图">
      {nodes.map((node, index) => {
        const ratio = node.size / total;
        return (
          <button
            className="tile"
            style={{
              background: `linear-gradient(145deg, ${node.color}, color-mix(in srgb, ${node.color} 68%, #07101d))`,
              flexBasis: `calc(${Math.max(ratio * 100, 20)}% - 4px)`,
              flexGrow: node.size,
              minHeight: ratio > 0.3 ? 188 : 112,
              animationDelay: `${index * 45}ms`,
            }}
            key={node.name}
            onClick={() => onOpen(node)}
          >
            <span className="tile-name">{node.name}</span>
            <span className="tile-size">{fmt(node.size)}</span>
            <span className="tile-type">{node.children ? `${node.children.length} 个项目` : node.type}</span>
          </button>
        );
      })}
    </div>
  );
}

export default function Home() {
  const [root, setRoot] = useState(roots[0]);
  const [path, setPath] = useState<Node[]>([roots[0]]);
  const [scanning, setScanning] = useState(false);
  const [search, setSearch] = useState("");
  const visible = useMemo(() => {
    const nodes = root.children ?? [root];
    return search ? nodes.filter((n) => n.name.toLowerCase().includes(search.toLowerCase())) : nodes;
  }, [root, search]);

  const open = (node: Node) => {
    if (!node.children) return;
    setRoot(node);
    setPath((p) => [...p, node]);
  };

  const jump = (index: number) => {
    const next = path.slice(0, index + 1);
    setPath(next);
    setRoot(next[next.length - 1]);
  };

  const scan = () => {
    setScanning(true);
    window.setTimeout(() => setScanning(false), 2200);
  };

  return (
    <main>
      <header>
        <div className="brand"><span className="brand-mark">S</span><div><b>SpaceLens</b><small>磁盘空间分析器</small></div></div>
        <div className="head-actions">
          <label className="search"><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索文件或文件夹…" /></label>
          <button className="scan-button" onClick={scan}><span className={scanning ? "spin" : ""}>↻</span>{scanning ? "正在扫描…" : "重新扫描"}</button>
        </div>
      </header>

      <section className="drive-strip">
        <div className="drive-title"><span className="eyebrow">存储空间</span><h1>所有磁盘</h1><p>上次扫描：今天 13:42 · 3,284,291 个文件</p></div>
        {roots.map((drive, i) => {
          const used = [76, 62, 48][i];
          return <button className={`drive ${path[0].name === drive.name ? "active" : ""}`} key={drive.name} onClick={() => { setRoot(drive); setPath([drive]); }}>
            <span className="drive-icon">▰</span><span className="drive-copy"><b>本地磁盘 ({drive.name})</b><small>{fmt(drive.size * used / 100)} / {fmt(drive.size)}</small><i><em style={{ width: `${used}%` }} /></i></span><strong>{used}%</strong>
          </button>;
        })}
      </section>

      <section className="workspace">
        <div className="main-panel">
          <div className="panel-head">
            <nav className="crumbs"><button onClick={() => jump(0)}>所有磁盘</button>{path.map((n, i) => <span key={`${n.name}-${i}`}>› <button onClick={() => jump(i)}>{n.name}</button></span>)}</nav>
            <div className="view-actions"><button className="selected">▦ 矩形图</button><button>☷ 列表</button></div>
          </div>
          <div className="summary"><div><span>{root.name} 已用空间</span><strong>{fmt(root.size * .76)}</strong></div><div><span>当前目录</span><strong>{fmt(visible.reduce((a, n) => a + n.size, 0))}</strong></div><div><span>项目</span><strong>{visible.length.toLocaleString()}</strong></div><small><i />矩形面积代表文件大小 · 点击文件夹深入查看</small></div>
          {visible.length ? <Treemap nodes={visible} onOpen={open} /> : <div className="empty">没有找到匹配的项目</div>}
        </div>

        <aside>
          <section className="side-card types"><div className="card-head"><div><span className="eyebrow">空间构成</span><h2>文件类型</h2></div><button>查看全部 →</button></div>
            <div className="donut"><div><strong>2.96</strong><span>TB 已用</span></div></div>
            <div className="legend">{formats.map(([name, size, pct, color]) => <div key={name as string}><i style={{ background: color }} /><span>{name}</span><b>{size}</b><small>{pct}%</small></div>)}</div>
          </section>
          <section className="side-card duplicates"><div className="card-head"><div><span className="eyebrow">可释放空间</span><h2>重复文件</h2></div><span className="badge">发现 1,284 组</span></div>
            <div className="reclaim"><div><strong>86.4 GB</strong><span>潜在可释放空间</span></div><button>开始清理</button></div>
            {[["film_final_v2.mp4","8.4 GB","3 份副本"],["archive_2025.zip","4.7 GB","2 份副本"],["photos_backup","3.2 GB","4 份副本"]].map((f) => <div className="file-row" key={f[0]}><span className="file-icon">◇</span><div><b>{f[0]}</b><small>{f[2]}</small></div><strong>{f[1]}</strong></div>)}
          </section>
        </aside>
      </section>
      {scanning && <div className="scan-progress"><span /><div><b>正在分析磁盘…</b><small>已扫描 2,481,903 个文件</small></div><strong>74%</strong></div>}
    </main>
  );
}
