#!/usr/bin/env python3
"""
Servidor FastAPI para o Pipeline OCR de Documentos Históricos
"""
import asyncio, json, os, re, shutil, signal, time, uuid
from datetime import date
from pathlib import Path
from typing import Optional

import fitz
import psutil
import anthropic
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# ── configuração ─────────────────────────────────────────────────────────────
API_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")
BASE_DIR     = Path(__file__).parent
JOBS_DIR     = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)
MODEL        = "claude-haiku-4-5"
MAX_TOKENS   = 8192

# ── limites do beta (2026-07-10) ─────────────────────────────────────────────
MAX_UPLOAD_MB       = 25
MAX_PAGINAS_DOC     = 10
MAX_PAGINAS_DIA     = 10
USO_DIARIO_PATH     = BASE_DIR / "uso_diario.json"

# ── codigos de convite (2026-07-11) ──────────────────────────────────────────
CODIGOS_CONVITE_PATH = BASE_DIR / "codigos_convite.json"
CODIGOS_ADMIN_PATH   = BASE_DIR / "codigos_admin.json"

def _carregar_codigos(path):
    try:
        return set(c.strip().upper() for c in json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return set()

CODIGOS_CONVITE = _carregar_codigos(CODIGOS_CONVITE_PATH)
CODIGOS_ADMIN   = _carregar_codigos(CODIGOS_ADMIN_PATH)

# ── travas anti-loop (2026-07-11) ────────────────────────────────────────────
# Mitigação para o loop de geração anômalo observado em 2026-07-10 (backlog 6.1).
# Teto de tokens por bloco é aplicado via SURYA_MAX_TOKENS_BLOCK_CEILING no
# ocr-start.sh (variável de ambiente lida pela biblioteca surya). O timeout
# abaixo é a rede de segurança: mata TODOS os processos descendentes do
# surya_ocr (usando psutil, nao apenas o grupo de processos, porque o
# llama-server filho pode nascer em sessao/grupo proprio e sobreviver a um
# killpg simples, como confirmado em teste em 2026-07-11).
SURYA_TIMEOUT_POR_PAGINA_S = 120
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

# ── controle de uso diario, por codigo de convite (2026-07-11) ──────────────
def _carregar_uso_diario() -> dict:
    hoje = date.today().isoformat()
    if USO_DIARIO_PATH.exists():
        try:
            dados = json.loads(USO_DIARIO_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            dados = {}
    else:
        dados = {}
    if dados.get("data") != hoje:
        dados = {"data": hoje, "por_codigo": {}}
    dados.setdefault("por_codigo", {})
    return dados

def _salvar_uso_diario(dados: dict):
    USO_DIARIO_PATH.write_text(json.dumps(dados, ensure_ascii=False))

def paginas_usadas_hoje(codigo: str) -> int:
    dados = _carregar_uso_diario()
    return dados["por_codigo"].get(codigo, 0)

def registrar_uso(codigo: str, n_paginas: int):
    dados = _carregar_uso_diario()
    dados["por_codigo"][codigo] = dados["por_codigo"].get(codigo, 0) + n_paginas
    _salvar_uso_diario(dados)
# ─────────────────────────────────────────────────────────────────────────────

# ── instrumentacao por job (2026-07-12) ──────────────────────────────────────
INSTRUMENTACAO_PATH = BASE_DIR / "instrumentacao.jsonl"
TETO_TOKENS_BLOCO = int(os.environ.get("SURYA_MAX_TOKENS_BLOCK_CEILING", 3000))

def registrar_instrumentacao(dados: dict):
    with open(INSTRUMENTACAO_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(dados, ensure_ascii=False) + "\n")

class TimeoutAntiLoop(RuntimeError):
    """Levantada quando o timeout anti-loop mata o subprocesso do Surya."""
    pass
# ─────────────────────────────────────────────────────────────────────────────

def _matar_arvore_processos(pid: int):
    """
    Mata o processo e TODOS os seus descendentes (recursivo), usando psutil.
    Nao confia em grupo de processos (killpg), porque o llama-server filho
    pode nascer em sessao propria e sobreviver a isso (confirmado em teste
    em 2026-07-11). Ignora processos que ja tenham morrido nesse meio tempo.
    """
    try:
        pai = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    filhos = pai.children(recursive=True)
    for proc in filhos + [pai]:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(filhos + [pai], timeout=5)

async def _rodar_surya_com_timeout(pdf_path: Path, surya_out: Path, n_paginas_esperadas: int):
    """
    Roda o surya_ocr como subprocesso, com timeout proporcional ao numero de
    paginas. Se estourar, mata a arvore de processos inteira (surya_ocr +
    llama-server filho, mesmo que este tenha nascido em sessao propria).
    Mitigacao para o loop de geracao anomalo (backlog 6.1).
    """
    timeout_s = max(SURYA_TIMEOUT_POR_PAGINA_S, n_paginas_esperadas * SURYA_TIMEOUT_POR_PAGINA_S)

    proc = await asyncio.create_subprocess_exec(
        "surya_ocr", str(pdf_path), "--output_dir", str(surya_out),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        _matar_arvore_processos(proc.pid)
        raise TimeoutAntiLoop(
            f"Tempo limite de processamento excedido ({timeout_s}s para "
            f"{n_paginas_esperadas} página(s)). O documento pode ter causado "
            f"um problema no OCR. Tente novamente ou avise o suporte."
        )

    if proc.returncode != 0:
        raise RuntimeError("Surya OCR falhou")

async def processar_job(job_id: str, pdf_path: Path, ano: int, tipo: str, codigo: str, eh_admin: bool):
    job_dir = JOBS_DIR / job_id
    perfil = selecionar_perfil(ano)

    tempo_inicio = time.time()
    n_paginas_esperadas = None
    n_paginas = None
    duracao_ocr_s = None
    duracao_correcao_s = None
    tokens_in_total = 0
    tokens_out_total = 0
    custo_usd = 0.0
    timeout_disparou = False
    max_proximidade_teto = 0.0
    erro_msg = None

    try:
        # etapa 1: OCR com Surya
        surya_out = job_dir / "surya"
        results_path = surya_out / pdf_path.stem / "results.json"

        doc_tmp = fitz.open(str(pdf_path))
        n_paginas_esperadas = doc_tmp.page_count
        doc_tmp.close()

        if not results_path.exists():
            atualizar_status(job_dir, "processando", 10,
                             f"Rodando OCR para {n_paginas_esperadas} página(s) (pode demorar alguns minutos)...")
            await _rodar_surya_com_timeout(pdf_path, surya_out, n_paginas_esperadas)

            for f in surya_out.rglob("results.json"):
                results_path = f
                break
        else:
            atualizar_status(job_dir, "processando", 10, "Usando OCR já processado...")

        duracao_ocr_s = round(time.time() - tempo_inicio, 2)

        if not results_path.exists():
            raise RuntimeError("results.json não encontrado após OCR")

        with open(results_path) as f:
            data = json.load(f)
        pages_surya = list(data.values())[0]

        # estimativa aproximada de proximidade ao teto de tokens por bloco
        for page_surya in pages_surya:
            for b in page_surya["blocks"]:
                tokens_estimados = len(b.get("html", "")) // 4
                proximidade = tokens_estimados / TETO_TOKENS_BLOCO
                if proximidade > max_proximidade_teto:
                    max_proximidade_teto = proximidade

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
            tokens_in_total  += resp.usage.input_tokens
            tokens_out_total += resp.usage.output_tokens
            resultado = resp.content[0].text
            resultado = pos_correcao(resultado, perfil, tipo)
            textos.append(resultado)

        custo_usd = (tokens_in_total * 1.00 + tokens_out_total * 5.00) / 1_000_000
        duracao_correcao_s = round(time.time() - tempo_inicio - (duracao_ocr_s or 0), 2)

        # etapa 4: salva resultado
        atualizar_status(job_dir, "processando", 95, "Gerando arquivo final...")
        saida = "\n\n".join(textos)
        (job_dir / "resultado.txt").write_text(saida, encoding="utf-8")
        atualizar_status(job_dir, "concluido", 100, f"{n_paginas} páginas transcritas.")

    except Exception as e:
        erro_msg = str(e)
        timeout_disparou = isinstance(e, TimeoutAntiLoop)
        atualizar_status(job_dir, "erro", 0, str(e))

    finally:
        duracao_total_s = round(time.time() - tempo_inicio, 2)
        registrar_instrumentacao({
            "timestamp": tempo_inicio,
            "job_id": job_id,
            "codigo": "admin" if eh_admin else codigo,
            "n_paginas": n_paginas_esperadas,
            "ano": ano,
            "perfil": perfil,
            "duracao_ocr_s": duracao_ocr_s,
            "duracao_correcao_s": duracao_correcao_s,
            "duracao_total_s": duracao_total_s,
            "tokens_in": tokens_in_total,
            "tokens_out": tokens_out_total,
            "custo_usd": round(custo_usd, 5),
            "timeout_disparou": timeout_disparou,
            "max_proximidade_teto_tokens": round(max_proximidade_teto, 2),
            "erro": erro_msg,
        })

# ── static files (logo, etc) ────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ── rotas ─────────────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload(
    request: Request,
    arquivo: UploadFile = File(...),
    ano: int = Form(...),
    tipo: str = Form("livro"),
    codigo: str = Form(...)
):
    if not API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY não configurada no servidor")
    if not arquivo.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Apenas arquivos PDF são aceitos")

    codigo_norm = codigo.strip().upper()
    eh_admin = codigo_norm in CODIGOS_ADMIN
    eh_valido = eh_admin or codigo_norm in CODIGOS_CONVITE

    if not eh_valido:
        raise HTTPException(403, "Código de convite inválido. Verifique o código recebido e tente novamente.")

    content = await arquivo.read()

    tamanho_mb = len(content) / (1024 * 1024)
    if tamanho_mb > MAX_UPLOAD_MB:
        raise HTTPException(
            400,
            f"Arquivo de {tamanho_mb:.1f} MB excede o limite do beta ({MAX_UPLOAD_MB} MB)."
        )

    try:
        doc_check = fitz.open(stream=content, filetype="pdf")
        n_paginas_doc = doc_check.page_count
        doc_check.close()
    except Exception:
        raise HTTPException(400, "Não foi possível ler o PDF enviado (arquivo corrompido?).")

    if n_paginas_doc > MAX_PAGINAS_DOC:
        raise HTTPException(
            400,
            f"Documento com {n_paginas_doc} páginas excede o limite do beta "
            f"({MAX_PAGINAS_DOC} páginas por documento)."
        )

    if not eh_admin:
        ja_usadas = paginas_usadas_hoje(codigo_norm)
        if ja_usadas + n_paginas_doc > MAX_PAGINAS_DIA:
            restantes = max(0, MAX_PAGINAS_DIA - ja_usadas)
            raise HTTPException(
                429,
                f"Limite diário do beta atingido: {ja_usadas}/{MAX_PAGINAS_DIA} páginas já usadas hoje. "
                f"Restam {restantes} página(s). Tente novamente amanhã."
            )

    job_id  = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()

    pdf_path = job_dir / arquivo.filename
    pdf_path.write_bytes(content)

    if not eh_admin:
        registrar_uso(codigo_norm, n_paginas_doc)

    atualizar_status(job_dir, "iniciando", 0, "Job criado, aguardando início...")
    asyncio.create_task(processar_job(job_id, pdf_path, ano, tipo, codigo_norm, eh_admin))

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

@app.get("/comece", response_class=HTMLResponse)
async def comece():
    return (BASE_DIR / "static" / "comece.html").read_text(encoding="utf-8")

@app.get("/privacidade", response_class=HTMLResponse)
async def privacidade():
    return (BASE_DIR / "static" / "privacidade.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
