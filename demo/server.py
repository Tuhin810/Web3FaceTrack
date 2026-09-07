"""Local demo server -- for recording a video of the pipeline. Not a deliverable.

See demo/README.md: TASK.md forbids a hosted frontend, and this is not one. It binds to
localhost, ships no auth because it is never exposed, and calls exactly the same
functions the CLI does -- it visualises the pipeline rather than reimplementing it.

    .venv/bin/python demo/server.py [--port 8000] [--network local]
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS: dict[str, dict] = {}
NETWORK = "local"
ANCHOR = False


# --- pipeline, stage by stage, so the page can show progress ----------------------


def _emit(run: dict, stage: str, status: str, **data) -> None:
    for s in run["stages"]:
        if s["id"] == stage:
            s["status"] = status
            s.update(data)
            return
    run["stages"].append({"id": stage, "status": status, **data})


def _annotate(image_bytes: bytes, faces) -> str:
    """Draw detection boxes; return a data URI for the page."""
    arr = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    for f in faces:
        x1, y1, x2, y2 = f.bbox
        cv2.rectangle(arr, (x1, y1), (x2, y2), (0, 220, 90), 3)
        cv2.putText(arr, f"{f.det_score:.2f}", (x1, max(18, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 90), 2)
    h, w = arr.shape[:2]
    if max(h, w) > 520:
        scale = 520 / max(h, w)
        arr = cv2.resize(arr, (int(w * scale), int(h * scale)))
    _, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def run_pipeline(run_id: str, image_bytes: bytes, provider: str) -> None:
    run = RUNS[run_id]
    subject = f"demo_{run_id[:8]}"
    tmp = REPO_ROOT / "out" / f".demo_{run_id[:8]}.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(image_bytes)

    try:
        from facechain.config import get_settings
        from facechain.consent import check_consent, enroll, purge
        from facechain.evidence import (
            MatchInfo,
            QueryInfo,
            SearchInfo,
            build_evidence,
            evidence_hash,
            new_run_id,
            phash,
            record_id_for,
            sha256_bytes,
            sha256_file,
            sha256_text,
            write_evidence,
        )
        from facechain.face import MATCH_THRESHOLD, detect_faces, select_primary
        from facechain.matcher import find_matches
        from facechain.status import Status

        settings = get_settings()

        # --- stage 1: detect ---------------------------------------------------
        _emit(run, "detect", "running")
        faces = detect_faces(image_bytes)
        if not faces:
            _emit(run, "detect", "failed", detail="No face detected in this image.")
            run["status"] = "NO_FACE"
            run["done"] = True
            return
        primary = select_primary(faces)
        _emit(run, "detect", "ok",
              detail=f"{len(faces)} face(s); primary det_score {primary.det_score:.3f}",
              image=_annotate(image_bytes, faces),
              facts=[["faces found", str(len(faces))],
                     ["detection score", f"{primary.det_score:.3f}"],
                     ["bounding box", str(primary.bbox)],
                     ["embedding", f"{primary.vector.shape[0]}-d, L2-normalised"],
                     ["model", primary.model]])

        # --- stage 2: consent --------------------------------------------------
        _emit(run, "consent", "running")
        enroll(subject, tmp, "Demo run: the operator confirmed they may use this photo.",
               display_name=subject, overwrite=True, settings=settings)
        check = check_consent(subject, tmp, settings=settings)
        _emit(run, "consent", "ok",
              detail=f"Gate passed (self-similarity {check.similarity:+.4f})",
              facts=[["subject", subject],
                     ["gate", "runs before any upload or search"],
                     ["stored", "consent record + encoding only; no photograph"]])

        # --- stage 3: search ---------------------------------------------------
        _emit(run, "search", "running")
        hosted = "offline-replay"
        if provider == "serpapi":
            from facechain.hosting import upload_query_image
            h = upload_query_image(image_bytes, settings=settings)
            hosted = h.url
            from facechain.search.serpapi_lens import SerpApiLensProvider
            prov = SerpApiLensProvider(settings=settings)
        else:
            from facechain.search.offline import OfflineProvider
            prov = OfflineProvider()
        candidates, raw = prov.search_by_image(hosted)
        raw_bytes = json.dumps(raw, indent=2, ensure_ascii=False).encode()
        _emit(run, "search", "ok",
              detail=f"{len(candidates)} candidates from {prov.name}",
              facts=[["provider", prov.name],
                     ["hosted query", hosted],
                     ["candidates", str(len(candidates))],
                     ["raw response", f"{len(raw_bytes):,} bytes, dumped verbatim"]],
              candidates=[{"url": c.page_url, "title": (c.title or "")[:80]}
                          for c in candidates[:12]])

        # --- stage 4: re-verify ------------------------------------------------
        _emit(run, "verify_faces", "running")
        matches, stats = find_matches(candidates, str(tmp), settings.match_threshold,
                                      settings.max_candidates)
        _emit(run, "verify_faces", "ok" if matches else "nomatch",
              detail=(f"{stats.candidates_matched} of {stats.candidates_fetched} fetched "
                      f"pages confirmed"),
              facts=[["returned", str(stats.candidates_returned)],
                     ["fetched", str(stats.candidates_fetched)],
                     ["confirmed", str(stats.candidates_matched)],
                     ["threshold", f"{MATCH_THRESHOLD}"]],
              matches=[{"url": m.page_url, "score": round(m.similarity, 4),
                        "image": m.matched_image_url, "title": m.page_title or ""}
                       for m in matches])

        # --- stage 5: evidence -------------------------------------------------
        _emit(run, "evidence", "running")
        best = matches[0] if matches else None
        evidence = build_evidence(
            run_id=new_run_id(), subject_id=subject,
            query=QueryInfo(sha256_file(tmp), phash(tmp), primary.model, primary.det_score),
            search=SearchInfo(prov.name, hosted, stats.candidates_returned,
                              stats.candidates_fetched, stats.candidates_matched,
                              sha256_bytes(raw_bytes)),
            match=None if best is None else MatchInfo(
                best.page_url, best.page_title, sha256_text(best.page_text_excerpt),
                best.matched_image_url, best.matched_image_sha256, best.similarity,
                settings.match_threshold, best.fetched_at),
        )
        run_dir = settings.out_dir / evidence["run_id"]
        write_evidence(run_dir, evidence)
        ehash = evidence_hash(evidence)
        facts = [["evidence hash", ehash], ["canonical bytes", "sorted keys, no whitespace"]]
        if best is not None:
            facts.append(["record id", record_id_for(evidence)])
        _emit(run, "evidence", "ok",
              detail="Canonical JSON hashed with keccak256",
              facts=facts, run_dir=str(run_dir))

        # --- stage 6: anchor + verify ------------------------------------------
        if best is None:
            _emit(run, "anchor", "skipped", detail="Nothing to anchor without a match.")
            run["status"] = Status.NO_MATCH.value
        elif not ANCHOR:
            _emit(run, "anchor", "skipped",
                  detail="Anchoring disabled (start with --anchor and a running chain).")
            run["status"] = Status.MATCHED_NOT_ANCHORED.value
        else:
            _emit(run, "anchor", "running")
            from facechain.chain.anchor import anchor as do_anchor
            from facechain.chain.verify import verify_report
            res = do_anchor(NETWORK, evidence, settings=settings)
            rep = verify_report(NETWORK, evidence, settings=settings)
            _emit(run, "anchor", "ok" if rep.verified else "failed",
                  detail="VERIFIED on-chain" if rep.verified else "verification failed",
                  facts=[["tx hash", res.tx_hash], ["block", str(res.block_number)],
                         ["submitter", res.submitter],
                         ["on-chain hash", rep.on_chain_hash or "-"]])
            run["status"] = Status.MATCHED_AND_ANCHORED.value
        run["done"] = True

    except Exception as exc:  # noqa: BLE001 -- a demo must show the error, not vanish
        run["error"] = f"{type(exc).__name__}: {exc}"
        run["trace"] = traceback.format_exc()[-1200:]
        run["done"] = True
    finally:
        # Never leave a biometric template or the uploaded photo behind after a demo.
        with contextlib.suppress(Exception):
            purge(subject)
        tmp.unlink(missing_ok=True)


# --- HTTP -------------------------------------------------------------------------

STAGES = [
    ("detect", "1 · Detect &amp; encode face"),
    ("consent", "2 · Consent gate"),
    ("search", "3 · Reverse-image search"),
    ("verify_faces", "4 · Face re-verification"),
    ("evidence", "5 · Canonical evidence"),
    ("anchor", "6 · Anchor &amp; verify on-chain"),
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path)
        if path.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path.path == "/api/status":
            rid = parse_qs(path.query).get("run", [""])[0]
            return self._send(200, json.dumps(RUNS.get(rid, {"error": "unknown run"})))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            return self._send(404, json.dumps({"error": "not found"}))
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        image = base64.b64decode(payload["image"].split(",", 1)[-1])
        provider = payload.get("provider", "offline")

        rid = uuid.uuid4().hex
        RUNS[rid] = {"stages": [{"id": s, "status": "pending"} for s, _ in STAGES],
                     "done": False, "status": None}
        threading.Thread(target=run_pipeline, args=(rid, image, provider),
                         daemon=True).start()
        return self._send(200, json.dumps({"run": rid}))


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>FaceChain Verify — demo</title><style>
*{box-sizing:border-box} body{margin:0;font:15px/1.5 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif;
background:#0b0f14;color:#dbe4ee}
.wrap{max-width:1080px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.4px}
.sub{color:#8797ab;margin:0 0 26px;font-size:14px}
.panel{background:#121821;border:1px solid #1f2a37;border-radius:12px;padding:20px;margin-bottom:18px}
#drop{border:2px dashed #2b3a4d;border-radius:12px;padding:38px;text-align:center;cursor:pointer;
transition:.15s;background:#0e141c}
#drop:hover,#drop.over{border-color:#22c55e;background:#101a16}
#drop input{display:none}
.row{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-top:14px}
button{background:#22c55e;color:#04210f;border:0;border-radius:8px;padding:11px 20px;font-weight:600;
font-size:14px;cursor:pointer}
button:disabled{background:#2b3a4d;color:#6b7c91;cursor:not-allowed}
select{background:#0e141c;color:#dbe4ee;border:1px solid #2b3a4d;border-radius:8px;padding:10px}
label.ck{display:flex;gap:9px;align-items:flex-start;color:#9fb0c4;font-size:13.5px;line-height:1.45;
max-width:640px;margin-top:16px}
.stage{border:1px solid #1f2a37;border-radius:10px;margin-bottom:11px;overflow:hidden;background:#121821}
.head{display:flex;align-items:center;gap:11px;padding:13px 16px;font-weight:600;font-size:14.5px}
.dot{width:9px;height:9px;border-radius:50%;background:#3b4a5e;flex:none}
.pending .dot{background:#3b4a5e}
.running .dot{background:#eab308;animation:p 1s infinite}
.ok .dot{background:#22c55e} .nomatch .dot{background:#eab308}
.failed .dot{background:#ef4444} .skipped .dot{background:#4b5563}
@keyframes p{50%{opacity:.3}}
.detail{margin-left:auto;color:#8797ab;font-weight:400;font-size:13px;text-align:right}
.body{padding:0 16px 16px;display:none} .body.show{display:block}
table{width:100%;border-collapse:collapse;font-size:13px}
td{padding:5px 0;vertical-align:top;border-bottom:1px solid #18212c}
td:first-child{color:#8797ab;width:170px}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;word-break:break-all}
img.shot{max-width:100%;border-radius:8px;margin:10px 0;border:1px solid #1f2a37}
.cand{font-size:12.5px;padding:5px 0;border-bottom:1px solid #18212c;color:#8797ab}
.match{background:#0f2318;border:1px solid #1e5b38;border-radius:8px;padding:12px;margin-top:10px}
.score{color:#22c55e;font-weight:700}
.err{background:#2a1215;border:1px solid #7f1d1d;color:#fca5a5;padding:14px;border-radius:8px}
.note{color:#6b7c91;font-size:12.5px;margin-top:22px;line-height:1.6}
a{color:#60a5fa}
</style></head><body><div class="wrap">
<h1>FaceChain Verify</h1>
<p class="sub">Consent-scoped face identification with tamper-evident, on-chain evidence.
Local demo — every stage below runs the real pipeline.</p>

<div class="panel">
  <div id="drop"><input type="file" id="file" accept="image/*">
    <div id="dz"><strong>Drop a photo here</strong><div style="color:#6b7c91;font-size:13px;margin-top:6px">
    or click to choose</div></div></div>
  <label class="ck"><input type="checkbox" id="consent">
    <span>This is my own photograph, or I have the subject's explicit permission to run
    face identification on it. The pipeline enrols the face to pass its own consent gate,
    then deletes the encoding when the run finishes.</span></label>
  <div class="row">
    <select id="provider">
      <option value="offline">Offline replay (no keys, no network)</option>
      <option value="serpapi">Live search — SerpAPI Google Lens</option>
    </select>
    <button id="go" disabled>Run pipeline</button>
  </div>
</div>

<div id="stages"></div>
<div id="err"></div>
<p class="note">Not part of the deliverable — <code>TASK.md</code> §1 specifies a CLI with
no hosted frontend. This page exists to record a demonstration; it calls the same
functions <code>facechain</code> does.</p>
</div>
<script>
const STAGES=__STAGES__;
let img=null;
const $=id=>document.getElementById(id);
function ready(){ $('go').disabled = !(img && $('consent').checked); }
$('consent').onchange=ready;
$('drop').onclick=()=>$('file').click();
$('drop').ondragover=e=>{e.preventDefault();$('drop').classList.add('over')};
$('drop').ondragleave=()=>$('drop').classList.remove('over');
$('drop').ondrop=e=>{e.preventDefault();$('drop').classList.remove('over');load(e.dataTransfer.files[0])};
$('file').onchange=e=>load(e.target.files[0]);
function load(f){ if(!f)return; const r=new FileReader();
  r.onload=()=>{img=r.result;
    $('dz').innerHTML='<img class="shot" style="max-height:230px" src="'+img+'">'+
      '<div style="color:#6b7c91;font-size:13px;margin-top:8px">'+f.name+' — click to change</div>';
    ready();}; r.readAsDataURL(f); }

$('go').onclick=async()=>{
  $('go').disabled=true; $('err').innerHTML='';
  $('stages').innerHTML=STAGES.map(([id,label])=>
    `<div class="stage pending" id="s-${id}"><div class="head"><span class="dot"></span>
     <span>${label}</span><span class="detail" id="d-${id}"></span></div>
     <div class="body" id="b-${id}"></div></div>`).join('');
  const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({image:img,provider:$('provider').value})});
  const {run}=await r.json(); poll(run);
};

async function poll(run){
  const r=await fetch('/api/status?run='+run); const s=await r.json();
  (s.stages||[]).forEach(st=>{
    const el=$('s-'+st.id); if(!el)return;
    el.className='stage '+(st.status||'pending');
    $('d-'+st.id).textContent=st.detail||'';
    const b=$('b-'+st.id); let h='';
    if(st.image) h+=`<img class="shot" src="${st.image}">`;
    if(st.facts) h+='<table>'+st.facts.map(([k,v])=>
      `<tr><td>${k}</td><td class="mono">${v}</td></tr>`).join('')+'</table>';
    if(st.candidates) h+='<div style="margin-top:10px;color:#8797ab;font-size:12px">'+
      'candidates returned by the provider (first 12):</div>'+
      st.candidates.map(c=>`<div class="cand">${c.url}</div>`).join('');
    if(st.matches&&st.matches.length) h+=st.matches.map(m=>
      `<div class="match"><div class="score">confirmed · similarity ${m.score}</div>
       <div class="mono" style="margin-top:6px">${m.url}</div>
       <div style="color:#8797ab;font-size:12.5px;margin-top:4px">${m.title}</div></div>`).join('');
    if(st.status==='nomatch') h+=`<div style="color:#eab308;font-size:13px;margin-top:8px">
      No candidate passed face re-verification. This is a valid outcome, not a failure —
      reverse-image search returns visually similar pages, and re-verification is what
      refuses to confirm them.</div>`;
    if(h){b.innerHTML=h;b.classList.add('show');}
  });
  if(s.error) $('err').innerHTML=`<div class="err"><strong>${s.error}</strong>
    <pre class="mono" style="white-space:pre-wrap;margin:8px 0 0">${s.trace||''}</pre></div>`;
  if(!s.done) setTimeout(()=>poll(run),400); else $('go').disabled=false;
}
</script></body></html>"""

PAGE = PAGE.replace("__STAGES__", json.dumps(STAGES))


def main() -> int:
    global NETWORK, ANCHOR
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--network", default="local")
    ap.add_argument("--anchor", action="store_true",
                    help="anchor and verify on-chain (needs a running chain + PRIVATE_KEY)")
    args = ap.parse_args()
    NETWORK, ANCHOR = args.network, args.anchor

    print(f"demo server: http://127.0.0.1:{args.port}")
    print(f"  anchoring: {'on, network=' + NETWORK if ANCHOR else 'off'}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
