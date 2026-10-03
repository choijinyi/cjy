"""로컬 웹 대시보드 (http://127.0.0.1:8080). 표준 라이브러리 http.server만 사용한다."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("dashboard")

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CJY 비트코인 채굴기</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--fg:#1d1d1f;--muted:#6b6b70;--accent:#e8890c;--ok:#1f8a4c;--bad:#c0392b;--line:#e4e2dd}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--fg:#ececf0;--muted:#9a9aa3;--line:#2c2c33}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Malgun Gothic",sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px;word-break:break-all}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.label{color:var(--muted);font-size:13px}.value{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}
.ok{color:var(--ok)}.bad{color:var(--bad)}.accent{color:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:6px 4px;border-bottom:1px solid var(--line)}
td.hash{font-family:ui-monospace,monospace;font-size:12px;word-break:break-all}
pre{margin:0;max-height:260px;overflow:auto;font-size:12px;white-space:pre-wrap}
.note{font-size:13px;color:var(--muted)}h2{font-size:16px;margin:0 0 8px}section{margin-bottom:16px}
</style></head><body><main>
<h1>CJY 비트코인 채굴기</h1>
<p class="sub" id="sub">불러오는 중…</p>
<div class="grid">
 <div class="card"><div class="label">연결 상태</div><div class="value" id="conn">-</div></div>
 <div class="card"><div class="label">해시레이트</div><div class="value accent" id="rate">-</div></div>
 <div class="card"><div class="label">승인 / 거절 share</div><div class="value" id="shares">-</div></div>
 <div class="card"><div class="label">최고 share 난이도</div><div class="value" id="best">-</div></div>
 <div class="card"><div class="label">발견한 블록</div><div class="value" id="blocks">-</div></div>
 <div class="card"><div class="label">가동 시간</div><div class="value" id="uptime">-</div></div>
</div>
<section class="card"><h2>현실 점검</h2>
<p class="note">네트워크 난이도 <b id="netdiff">-</b> 기준, 현재 속도로 블록 하나를 찾는 데 걸리는 평균 시간은 <b id="eta">-</b>입니다.
CPU 채굴은 확률이 극히 낮은 복권에 가깝습니다. 학습·실험용으로 사용하시고, 전기요금을 꼭 고려하세요.</p></section>
<section class="card"><h2>최근 share</h2><table><thead><tr><th>시각</th><th>난이도</th><th>상태</th><th>해시</th></tr></thead><tbody id="tbl"></tbody></table></section>
<section class="card"><h2>로그</h2><pre id="log"></pre></section>
</main><script>
const $=id=>document.getElementById(id);
const fmt=n=>n>=1e12?(n/1e12).toFixed(2)+'T':n>=1e9?(n/1e9).toFixed(2)+'G':n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e3?(n/1e3).toFixed(2)+'k':Number(n).toPrecision(4);
const dur=s=>{const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h+'시간 '+m+'분'};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function tick(){try{const s=await (await fetch('/api/status')).json();
$('sub').textContent=`풀 ${s.pool} · ${s.user} · 워커 ${s.threads}개 · v${s.version}`;
$('conn').innerHTML=s.connected?'<span class="ok">연결됨</span>':'<span class="bad">재접속 중</span>';
$('rate').textContent=s.hashrate_text;$('shares').textContent=s.accepted+' / '+s.rejected;
$('best').textContent=fmt(s.best_share);$('blocks').textContent=s.blocks;$('uptime').textContent=dur(s.uptime);
$('netdiff').textContent=fmt(s.network_difficulty);$('eta').textContent=s.expected_block_time;
$('tbl').innerHTML=s.recent_shares.map(r=>`<tr><td>${esc(r.time)}</td><td>${fmt(r.difficulty)}</td><td>${esc(r.status)}${r.is_block?' 🎉':''}</td><td class="hash">${esc(r.hash)}</td></tr>`).join('')||'<tr><td colspan=4 class="note">아직 없음</td></tr>';
const lg=$('log');lg.textContent=s.log.join('\\n');lg.scrollTop=lg.scrollHeight;
}catch(e){$('conn').innerHTML='<span class="bad">채굴기 응답 없음</span>'}}
tick();setInterval(tick,2000);
</script></body></html>"""


def start_dashboard(miner, host="127.0.0.1", port=8080):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/status"):
                body = json.dumps(miner.status(), ensure_ascii=False).encode()
                ctype = "application/json; charset=utf-8"
            elif self.path in ("/", "/index.html"):
                body = PAGE.encode()
                ctype = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("대시보드: http://%s:%d", host, port)
    return server
