// CME end-of-day downloads for the ctd raw store, run as a browser bookmarklet.
// `ctd bookmarklet` builds it, filling CONFIG from src/ctd/reference/data/cme_products.toml.
//
// Click it on any cmegroup.com tab (the Daily Bulletin page works best). It asks for the trade
// date, then saves each file exactly as CME serves it to the Downloads folder, named
// ctd_<asof>_<source>_<name>. `ctd ingest` (or `ctd fetch`) moves them into the store.
// Settlements that aren't Final yet are not saved, so a later Final file isn't blocked.
(async () => {
  const CONFIG = /*CONFIG*/null;
  if (!/(^|\.)cmegroup\.com$/.test(location.hostname)) {
    alert("ctd: open any cmegroup.com page first, then click the bookmark.");
    return;
  }
  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const prevWeekday = (d) => {
    d = new Date(d);
    do { d.setDate(d.getDate() - 1); } while (d.getDay() === 0 || d.getDay() === 6);
    return d;
  };
  const asof = prompt("ctd: trade date to download (YYYY-MM-DD)", iso(prevWeekday(new Date())));
  if (!asof) return;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(asof)) { alert("ctd: use YYYY-MM-DD"); return; }
  const [y, m, d] = asof.split("-");
  const mdy = `${m}/${d}/${y}`;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const save = (bytes, type, name) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([bytes], { type }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  };
  const report = [];

  for (const p of CONFIG.futures) {
    const url = `/CmeWS/mvc/Settlements/Futures/Settlements/${p.id}/FUT` +
      `?strategy=DEFAULT&tradeDate=${encodeURIComponent(mdy)}&pageSize=500`;
    try {
      const r = await fetch(url, { headers: { Accept: "application/json" }, credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const bytes = await r.arrayBuffer();
      const j = JSON.parse(new TextDecoder().decode(bytes));
      if (j.tradeDate !== mdy) throw new Error(`file is for ${j.tradeDate}`);
      if (!j.settlements || !j.settlements.length) throw new Error("no settlements in file");
      if (j.reportType !== "Final") throw new Error(`settlements are "${j.reportType}", not Final yet; try later`);
      save(bytes, "application/json", `ctd_${asof}_${p.source}_${p.code}.json`);
      report.push(`OK      ${p.code}`);
    } catch (e) {
      report.push(`FAILED  ${p.code}: ${e.message}`);
    }
    await sleep(700);
  }

  for (const b of CONFIG.bulletins) {
    const link = [...document.querySelectorAll("a[href]")]
      .find((a) => a.href.includes(b.link_match) && /\.pdf/i.test(a.href));
    const url = link ? link.href : b.url;
    try {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status} from ${url}`);
      const bytes = await r.arrayBuffer();
      if (new TextDecoder().decode(bytes.slice(0, 5)) !== "%PDF-") throw new Error(`not a PDF: ${url}`);
      const modified = r.headers.get("Last-Modified");
      const when = modified ? new Date(modified).toLocaleString() : "unknown";
      if (modified && iso(new Date(modified)) < asof) {
        throw new Error(`last updated ${when}, before ${asof}: not published yet`);
      }
      const ok = confirm(
        `ctd: ${b.name} was last updated ${when}.\n\n` +
        `CME replaces this file with each new bulletin. Save it as the bulletin for ${asof}?\n` +
        `(Yes if it was updated after ${asof}'s close and before the next trading day's close.)`);
      if (!ok) throw new Error("skipped");
      save(bytes, "application/pdf", `ctd_${asof}_${b.source}_${b.name}.pdf`);
      report.push(`OK      ${b.name} (last updated ${when})`);
    } catch (e) {
      report.push(`FAILED  ${b.name}: ${e.message}`);
    }
  }

  alert(`ctd downloads for ${asof}\n\n${report.join("\n")}\n\n` +
    `Files are in your Downloads folder. Next: run "ctd ingest" (or "ctd fetch").`);
})();
