#!/usr/bin/env python3
"""
Servidor FastAPI para o Pipeline OCR de Documentos Históricos
"""
import asyncio, json, os, re, shutil, time, uuid
from pathlib import Path
from typing import Optional

import fitz
import anthropic
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# ── configuração ─────────────────────────────────────────────────────────────
API_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")
BASE_DIR     = Path(__file__).parent
JOBS_DIR     = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)
MODEL        = "claude-haiku-4-5"
MAX_TOKENS   = 8192
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Pipeline OCR — Documentos Históricos")

# ── prompts (mesmos do pipeline.py) ──────────────────────────────────────────
PROMPTS = {
    "pre1911": """Voce e um assistente especializado em transcricao de documentos historicos em portugues.

Voce recebera dois textos extraidos da mesma pagina de um documento historico digitalizado (ortografia pre-reforma de 1911):
- SURYA: extraido pelo OCR Surya 2 (melhor leitura de caracteres, mas pode perder trechos ou modernizar a ortografia)
- EMBUTIDO: extraido do OCR original do PDF (qualidade inferior, mas captura o conteudo completo da pagina)

Produza o texto corrigido seguindo RIGOROSAMENTE estas regras:
1. USE o SURYA como base principal.
2. USE o EMBUTIDO apenas para detectar conteudo que o Surya omitiu.
3. CORRIJA erros obvios de reconhecimento de caractere em contexto claro:
   - confusoes h/b, h/n, rn/m, s duplo espurio
   - S LONGO: se encontrar palavras com "f" que nao facam sentido, corrija para "s". Ex: "cafos">"casos", "foube">"soube", "sidelissimo">"fidelissimo".
4. PRESERVE a ortografia historica EXATAMENTE. NAO modernize.
5. POESIA: preserve numeracao romana das estrofes, reconstitua palavras hifenizadas, ignore cabecalhos correntes.
6. Se o EMBUTIDO tiver conteudo ausente no SURYA, RESTAURE-O.
7. NUNCA adicione anotacoes como [initials], [ilegivel] etc.
8. Retorne APENAS o texto corrigido.

SURYA:
{surya}

EMBUTIDO:
{embutido}""",

    "pos1911": """Voce e um assistente especializado em transcricao de documentos em portugues.

Voce recebera dois textos extraidos da mesma pagina de um documento digitalizado:
- SURYA: extraido pelo OCR Surya 2
- EMBUTIDO: extraido do OCR original do PDF

Produza o texto corrigido seguindo RIGOROSAMENTE estas regras:
1. USE o SURYA como base principal.
2. USE o EMBUTIDO apenas para detectar conteudo que o Surya omitiu.
3. CORRIJA erros de reconhecimento de caractere.
4. PRESERVE nomes proprios, titulos e citacoes em linguas estrangeiras.
5. Se o EMBUTIDO tiver conteudo ausente no SURYA, RESTAURE-O.
6. NUNCA adicione anotacoes como [initials], [ilegivel] etc.
7. Retorne APENAS o texto corrigido.

SURYA:
{surya}

EMBUTIDO:
{embutido}"""
}

CIRCUNFLEXOS = [
    (r"\bfor\b(?=\s+(?:provido|possivel|necessario|commettido|acordado|do\s+feito|mais|sempre|bem))", "fôr"),
    (r"\bforem\b(?=\s+(?:feriados|presentes|concordes|chamados|diferentes|iguaes))", "fôrem"),
]

def selecionar_perfil(ano: int) -> str:
    return "pre1911" if ano < 1911 else "pos1911"

def pos_correcao(texto: str, perfil: str, tipo: str) -> str:
    if perfil == "pre1911":
        for p, s in CIRCUNFLEXOS:
            texto = re.sub(p, s, texto)
    if tipo == "juridico":
        linhas = texto.split("\n")
        resultado = []
        for linha in linhas:
            s = linha.strip()
            if re.match(r"^[\d\s]{10,}$", s): continue
            if re.match(r"^Extr\s*[\d\.]+\s*\d", s): continue
            if re.match(r"^\d{1,3}$", s): continue
            if re.match(r"^[A-Za-z]\.?$", s): continue
            resultado.append(linha)
        texto = re.sub(r"\n{3,}", "\n\n", "\n".join(resultado)).strip()
    return texto

def surya_para_texto(blocos: list) -> str:
    return "\n\n".join(
        "[" + b["label"] + "] " + b["texto"]
        for b in blocos
        if b["label"] in ("Text", "SectionHeader", "Footnote")
    )

def atualizar_status(job_dir: Path, status: str, progresso: int, mensagem: str = ""):
    estado = {
        "status": status,
        "progresso": progresso,
        "mensagem": mensagem,
        "atualizado": time.time()
    }
    (job_dir / "status.json").write_text(json.dumps(estado, ensure_ascii=False))

async def processar_job(job_id: str, pdf_path: Path, ano: int, tipo: str):
    job_dir = JOBS_DIR / job_id
    perfil = selecionar_perfil(ano)

    try:
        # etapa 1: OCR com Surya
        atualizar_status(job_dir, "processando", 10, "Rodando OCR (pode demorar alguns minutos)...")
        surya_out = job_dir / "surya"
        results_path = surya_out / pdf_path.stem / "results.json"

        if not results_path.exists():
            proc = await asyncio.create_subprocess_exec(
                "surya_ocr", str(pdf_path), "--output_dir", str(surya_out),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError("Surya OCR falhou")
            # busca results.json em qualquer subpasta
            for f in surya_out.rglob("results.json"):
                results_path = f
                break

        if not results_path.exists():
            raise RuntimeError("results.json não encontrado após OCR")

        with open(results_path) as f:
            data = json.load(f)
        pages_surya = list(data.values())[0]

        # etapa 2: extrai embutido
        atualizar_status(job_dir, "processando", 30, "Extraindo texto embutido...")
        doc = fitz.open(str(pdf_path))
        n_paginas = len(pages_surya)

        # etapa 3: corrige com Haiku
        client = anthropic.Anthropic(api_key=API_KEY)
        textos = []

        for i, (page_surya, page_fitz) in enumerate(zip(pages_surya, doc)):
            progresso = 30 + int((i / n_paginas) * 60)
            atualizar_status(job_dir, "processando", progresso,
                             f"Corrigindo página {i+1} de {n_paginas}...")

            blocos = []
            for b in page_surya["blocks"]:
                if b["label"] in ("Text", "SectionHeader", "Footnote"):
                    txt = re.sub(r"<[^>]+>", " ", b["html"])
                    txt = re.sub(r"\s+", " ", txt).strip()
                    if txt:
                        blocos.append({"label": b["label"], "texto": txt})

            surya_txt   = surya_para_texto(blocos)
            embutido_txt = page_fitz.get_text("text").strip()
            prompt = PROMPTS[perfil].format(surya=surya_txt, embutido=embutido_txt)

            resp = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}]
            )
            resultado = resp.content[0].text
            resultado = pos_correcao(resultado, perfil, tipo)
            textos.append(resultado)

        # etapa 4: salva resultado
        atualizar_status(job_dir, "processando", 95, "Gerando arquivo final...")
        saida = "\n\n".join(textos)
        (job_dir / "resultado.txt").write_text(saida, encoding="utf-8")
        atualizar_status(job_dir, "concluido", 100, f"{n_paginas} páginas transcritas.")

    except Exception as e:
        atualizar_status(job_dir, "erro", 0, str(e))

# ── static files (logo, etc) ────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ── rotas ─────────────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload(
    arquivo: UploadFile = File(...),
    ano: int = Form(...),
    tipo: str = Form("livro")
):
    if not API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY não configurada no servidor")
    if not arquivo.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Apenas arquivos PDF são aceitos")

    job_id  = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()

    pdf_path = job_dir / arquivo.filename
    content  = await arquivo.read()
    pdf_path.write_bytes(content)

    atualizar_status(job_dir, "iniciando", 0, "Job criado, aguardando início...")
    asyncio.create_task(processar_job(job_id, pdf_path, ano, tipo))

    return {"job_id": job_id}

@app.get("/status/{job_id}")
async def status(job_id: str):
    status_file = JOBS_DIR / job_id / "status.json"
    if not status_file.exists():
        raise HTTPException(404, "Job não encontrado")
    return json.loads(status_file.read_text())

@app.get("/download/{job_id}")
async def download(job_id: str):
    resultado = JOBS_DIR / job_id / "resultado.txt"
    if not resultado.exists():
        raise HTTPException(404, "Resultado não disponível")
    return FileResponse(
        str(resultado),
        media_type="text/plain; charset=utf-8",
        filename=f"transcricao_{job_id}.txt"
    )

@app.get("/", response_class=HTMLResponse)
async def index():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
