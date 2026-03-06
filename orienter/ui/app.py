from __future__ import annotations

import html
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from orienter.ui.config import resolve_paths
from orienter.ui.schemas import RunCreate
from orienter.ui.service import RunManager

BASE_DIR = Path(__file__).resolve().parent
paths = resolve_paths()
manager = RunManager(paths)
app = FastAPI(title="Creality 220 Orientation Optimizer")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def layout(content: str) -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/><title>Creality 220 Orientation Optimizer</title><link rel='stylesheet' href='/static/styles.css'/></head><body><div class='layout'><aside class='sidebar'><h1>U-Wright Open Innovations</h1><h2>Creality 220 Orientation Optimizer</h2><nav><a href='/'>Dashboard</a><a href='/runs/new'>New Run</a><a href='/runs'>Runs</a><a href='/settings'>Settings</a></nav></aside><main class='content'>{content}</main></div><footer class='status-bar'>LOCAL MODE · NO CLOUD · PORT 8787</footer></body></html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    runs = manager.list_runs()[:5]
    cfg = manager.load_config()
    rows = "".join(
        f"<tr><td><a href='/runs/{r['id']}'>{r['id'][:8]}</a></td><td>{r['status']}</td><td>{r['created_at']}</td><td>{r['profile']}</td></tr>"
        for r in runs
    )
    content = f"<section class='panel'><h3>System Status</h3><div class='grid3'><div><span>Engine Mode</span><strong>{manager._engine_mode()}</strong></div><div><span>Profile</span><strong>{cfg['profile']}</strong></div><div><span>Last Run</span><strong>{runs[0]['created_at'] if runs else 'Never'}</strong></div></div></section><section class='panel'><h3>Recent Runs</h3><table><thead><tr><th>ID</th><th>Status</th><th>Created</th><th>Profile</th></tr></thead><tbody>{rows}</tbody></table></section>"
    return HTMLResponse(layout(content))


@app.get('/runs/new', response_class=HTMLResponse)
def new_run_page() -> HTMLResponse:
    options = ''.join(f"<option>{k}</option>" for k in manager.presets().keys())
    content = f"""<section class='panel'><h3>Start New Run</h3><form id='newrun' class='form-grid'>
<label>Input path <input name='input_path' required /></label><label>Output path <input name='output_path' required /></label><label>Profile <input name='profile' value='Creality_220_Generic' /></label>
<label>Top K <input type='number' name='top_k' value='5' /></label><label>Slice top N <input type='number' name='slice_top_n' value='12' /></label>
<label>Weight preset <select name='weight_preset'>{options}</select></label><label>Overhang angle <input type='number' name='overhang_angle' value='45' /></label><label><input type='checkbox' name='dry_run'/> Dry run</label>
<button type='button' onclick='startRun()'>Start Run</button></form></section>
<script>async function startRun(){{const f=document.getElementById('newrun'); const data={{input_path:f.input_path.value,output_path:f.output_path.value,profile:f.profile.value,top_k:parseInt(f.top_k.value,10),slice_top_n:parseInt(f.slice_top_n.value,10),weight_preset:f.weight_preset.value,overhang_angle:parseInt(f.overhang_angle.value,10),dry_run:f.dry_run.checked}}; const r=await fetch('/api/runs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}}).then(x=>x.json()); location.href='/runs/'+r.id;}}</script>"""
    return HTMLResponse(layout(content))


@app.get('/runs', response_class=HTMLResponse)
def runs_page(status: str | None = None, search: str | None = None) -> HTMLResponse:
    runs = manager.list_runs(status=status, search=search)
    rows = ''.join(f"<tr><td><a href='/runs/{r['id']}'>{r['id'][:8]}</a></td><td>{r['status']}</td><td>{html.escape(r['input_path'])}</td><td>{html.escape(r['output_path'])}</td><td>{r['last_heartbeat']}</td></tr>" for r in runs)
    content = f"<section class='panel'><h3>Run History</h3><form method='get' class='inline-form'><input name='search' value='{html.escape(search or '')}'/><input name='status' value='{html.escape(status or '')}' placeholder='status'/><button type='submit'>Filter</button></form><table><thead><tr><th>ID</th><th>Status</th><th>Input</th><th>Output</th><th>Heartbeat</th></tr></thead><tbody>{rows}</tbody></table></section>"
    return HTMLResponse(layout(content))


@app.get('/runs/{run_id}', response_class=HTMLResponse)
def run_detail_page(run_id: str) -> HTMLResponse:
    run = manager.run_detail(run_id)
    if not run:
        raise HTTPException(404)
    total = max(len(run['models']), 1)
    completed = sum(1 for m in run['models'] if m['status'] == 'COMPLETED')
    progress = int((completed / total) * 100)
    rows = ''.join(f"<tr><td>{html.escape(m['model_path'])}</td><td>{m.get('best_score','')}</td><td>{m['metrics_json'].get('support_filament_delta','')}</td><td>{m['metrics_json'].get('support_time_delta','')}</td><td>{m['metrics_json'].get('total_time','')}</td><td>{m['metrics_json'].get('z_height','')}</td><td>{m['metrics_json'].get('orientation_rank','')}</td></tr>" for m in run['models'])
    logs = manager.logs(run_id, tail=200)
    log_text = '\n'.join(f"[{l['ts']}] {l['level']} {l['message']}" for l in logs)
    content = f"<section class='panel'><h3>Run {run['id']}</h3><p>Status: <strong>{run['status']}</strong> · Last heartbeat: {run['last_heartbeat']}</p><div class='progress'><div style='width:{progress}%'></div></div><div class='inline-form'><button onclick=\"act('pause')\">Pause</button><button onclick=\"act('resume')\">Resume</button><button onclick=\"act('stop')\">Stop</button><a href='/api/runs/{run_id}/download/reports_csv'>Download CSV</a></div></section><section class='panel'><h3>Results</h3><table><thead><tr><th>Model</th><th>Best score</th><th>Support Δ filament</th><th>Support Δ time</th><th>Total time</th><th>Z height</th><th>Rank</th></tr></thead><tbody>{rows}</tbody></table></section><section class='panel'><h3>Log Tail</h3><pre id='logs'>{html.escape(log_text)}</pre></section><script>async function act(name){{await fetch(`/api/runs/{run_id}/${{name}}`,{{method:'POST'}});location.reload();}} async function poll(){{const logs=await fetch('/api/runs/{run_id}/logs?tail=200').then(r=>r.json()); document.getElementById('logs').textContent=logs.map(l=>`[${{l.ts}}] ${{l.level}} ${{l.message}}`).join('\\n');}} setInterval(poll,3000);</script>"
    return HTMLResponse(layout(content))


@app.get('/settings', response_class=HTMLResponse)
def settings_page() -> HTMLResponse:
    cfg = manager.load_config()
    content = f"<section class='panel'><h3>Settings</h3><p>Bed dimensions: <strong>{cfg['bed']['x']} x {cfg['bed']['y']}</strong> (locked: {cfg['bed']['locked']})</p><form id='cfg' class='form-grid'><label>Profile <input name='profile' value='{cfg['profile']}'/></label><label>Worker count <input type='number' name='worker_count' value='{cfg['worker_count']}'/></label><label>Cache enabled <input type='checkbox' name='cache_enabled' {'checked' if cfg['cache_enabled'] else ''}/></label><label>Weight support <input type='number' step='0.01' name='support' value='{cfg['weights']['support']}'/></label><label>Weight time <input type='number' step='0.01' name='time' value='{cfg['weights']['time']}'/></label><label>Weight height <input type='number' step='0.01' name='height' value='{cfg['weights']['height']}'/></label><button type='button' onclick='saveCfg()'>Save config</button></form></section><script>async function saveCfg(){{const f=document.getElementById('cfg');const data={{brand:'U-Wright Open Innovations',title:'Creality 220 Orientation Optimizer',profile:f.profile.value,bed:{{x:220,y:220,locked:true}},worker_count:parseInt(f.worker_count.value,10),cache_enabled:f.cache_enabled.checked,weights:{{support:parseFloat(f.support.value),time:parseFloat(f.time.value),height:parseFloat(f.height.value)}}}};await fetch('/api/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}});location.reload();}}</script>"
    return HTMLResponse(layout(content))


@app.get('/api/runs')
def api_runs(status: str | None = None, search: str | None = None) -> list[dict]:
    return manager.list_runs(status=status, search=search)


@app.post('/api/runs')
def api_create_run(payload: RunCreate) -> dict[str, str]:
    return {"id": manager.create_run(payload)}


@app.get('/api/runs/{run_id}')
def api_run_detail(run_id: str) -> dict:
    run = manager.run_detail(run_id)
    if not run:
        raise HTTPException(404)
    return run


@app.post('/api/runs/{run_id}/pause')
def api_pause(run_id: str) -> dict[str, str]:
    manager.pause(run_id)
    return {'status': 'ok'}


@app.post('/api/runs/{run_id}/resume')
def api_resume(run_id: str) -> dict[str, str]:
    manager.resume(run_id)
    return {'status': 'ok'}


@app.post('/api/runs/{run_id}/stop')
def api_stop(run_id: str) -> dict[str, str]:
    manager.stop(run_id)
    return {'status': 'ok'}


@app.get('/api/runs/{run_id}/logs')
def api_logs(run_id: str, tail: int = Query(200, ge=1, le=1000)) -> list[dict]:
    return manager.logs(run_id, tail=tail)


@app.get('/api/runs/{run_id}/download/{artifact}')
def api_download(run_id: str, artifact: str) -> FileResponse:
    run = manager.run_detail(run_id)
    if not run:
        raise HTTPException(404)
    if artifact == 'reports_csv':
        p = Path(run['output_path']) / 'reports' / 'results.csv'
    elif artifact == 'reports_json':
        files = sorted((Path(run['output_path']) / 'reports').glob('*.json'))
        if not files:
            raise HTTPException(404)
        p = files[0]
    else:
        raise HTTPException(404)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(str(p), filename=p.name)


@app.get('/api/config')
def api_get_config() -> dict:
    return manager.load_config()


@app.post('/api/config')
def api_set_config(payload: dict) -> JSONResponse:
    manager.save_config(payload)
    return JSONResponse({'status': 'ok'})


@app.get('/runs/new/legacy')
def legacy_redirect(request: Request) -> RedirectResponse:  # compatibility
    return RedirectResponse('/runs/new', status_code=307)


def run_ui(host: str = '127.0.0.1', port: int = 8787, reload: bool = False) -> None:
    uvicorn.run('orienter.ui.app:app', host=host, port=port, reload=reload)
