#!/usr/bin/env python3
"""
Pipeline OCR para Documentos Históricos em Português
Uso: python3 pipeline.py <arquivo.pdf ou arquivo.jpg> [--seculo XVI|XVII|XVIII|XIX|XX]
"""
import argparse, json, os, re, sys, time
import fitz  # pymupdf
import anthropic

# ── configuração ─────────────────────────────────────────────────────────────
MODEL         = "claude-haiku-4-5"
MAX_TOKENS    = 8192
MAX_RETRIES   = 3
# ─────────────────────────────────────────────────────────────────────────────

PROMPTS = {
    "pre1911": """Voce e um assistente especializado em transcricao de documentos historicos em portugues.

Voce recebera dois textos extraidos da mesma pagina de um documento historico digitalizado (ortografia pre-reforma de 1911):
- SURYA: extraido pelo OCR Surya 2 (melhor leitura de caracteres, mas pode perder trechos ou modernizar a ortografia)
- EMBUTIDO: extraido do OCR original do PDF (qualidade inferior, mas captura o conteudo completo da pagina)

Produza o texto corrigido seguindo RIGOROSAMENTE estas regras:

1. USE o SURYA como base principal.
2. USE o EMBUTIDO apenas para detectar conteudo que o Surya omitiu.
3. CORRIJA erros obvios de reconhecimento de caractere em contexto claro:
   - confusoes h/b ("hem">"bem", "hosso">"nosso", "hom">"bom")
   - confusoes h/n ("hosso">"nosso")
   - confusoes rn/m ("entramem">"entrarem")
   - s duplo espurio ("desseje">"deseje")
4. PRESERVE a ortografia historica EXATAMENTE:
   - NAO adicione acentos ausentes: "tambem" permanece "tambem"
   - NAO remova circunflexos historicos: "for" com circunflexo permanece "for"
   - NAO altere grafias historicas: "assi", "stado", "elle", "della", "officio", "Officiaes"
   - NAO converta ortografia arcaica para moderna em nenhuma circunstancia
   - Grafias com ff, ss, tt duplos sao ortografia de epoca: NAO altere
5. Se o EMBUTIDO tiver palavras ausentes no SURYA que facam sentido, RESTAURE-AS.
6. Se nao conseguir determinar algo com seguranca, marque: [INCERTO: trecho]
7. NUNCA invente conteudo ausente nos dois textos.
8. NUNCA adicione anotacoes editoriais, colchetes explicativos, ou comentarios proprios
   ao texto (ex: "[initials]", "[ilegivel]", "[sic]" proprio - so preserve [sic] se ja estiver no original).
9. Retorne APENAS o texto corrigido, sem explicacoes nem comentarios.

SURYA:
{surya}

EMBUTIDO:
{embutido}""",

    "pos1911": """Voce e um assistente especializado em transcricao de documentos em portugues do seculo XX.

Voce recebera dois textos extraidos da mesma pagina de um documento digitalizado:
- SURYA: extraido pelo OCR Surya 2 (melhor leitura de caracteres, mas pode perder trechos)
- EMBUTIDO: extraido do OCR original do PDF (qualidade inferior, mas captura o conteudo completo)

Produza o texto corrigido seguindo RIGOROSAMENTE estas regras:

1. USE o SURYA como base principal.
2. USE o EMBUTIDO apenas para detectar conteudo que o Surya omitiu.
3. CORRIJA erros de reconhecimento de caractere: letras trocadas, palavras partidas, hifenizacao incorreta.
4. NORMALIZE para ortografia moderna brasileira quando o OCR errar (ex: "pharmacia">"farmácia" se for erro de OCR, nao palavra intencional do autor).
5. PRESERVE nomes proprios, titulos, citacoes em linguas estrangeiras exatamente como estao.
6. Se o EMBUTIDO tiver conteudo ausente no SURYA, RESTAURE-O.
7. Se nao conseguir determinar algo, marque: [INCERTO: trecho]
8. NUNCA invente conteudo ausente nos dois textos.
9. Retorne APENAS o texto corrigido, sem explicacoes nem comentarios.

SURYA:
{surya}

EMBUTIDO:
{embutido}"""
}

CIRCUNFLEXOS = [
    (r"\bfor\b(?=\s+(?:provido|possivel|necessario|commettido|acordado|vencida|do\s+feito|posta|caso|mais|sempre|bem|mal|justo))", "fôr"),
    (r"\bforem\b(?=\s+(?:feriados|presentes|concordes|absentes|em\b|de\b|dous|tres|conformes|chamados|diferentes|iguaes))", "fôrem"),
]



def _limpar_juridico(texto):
    linhas = texto.split("\n")
    resultado = []
    for linha in linhas:
        s = linha.strip()
        if re.match(r"^[\d\s]{10,}$", s): continue          # carimbo numerico
        if re.match(r"^Extr\s*[\d\.]+\s*\d", s): continue  # cabecalho corrente processo
        if re.match(r"^\d{1,3}$", s): continue               # numero de pagina solto
        if re.match(r"^[A-Za-z]\.?$", s): continue           # inicial solta
        resultado.append(linha)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(resultado)).strip()

def _corrigir_s_longo(texto):
    padroes = [
        (r"\bcafo\b", "caso"), (r"\bcafos\b", "casos"),
        (r"\bfoube\b", "soube"), (r"\bsidelissimo\b", "fidelissimo"),
        (r"\bsidelifsimo\b", "fidelissimo"), (r"\bfempre\b", "sempre"),
        (r"\bfendo\b", "sendo"), (r"\bfomente\b", "somente"),
        (r"\bfómente\b", "sómente"), (r"\baffim\b", "assim"),
        (r"\bneffe\b", "nesse"), (r"\bneffa\b", "nessa"),
        (r"\beffe\b", "esse"), (r"\beffa\b", "essa"),
        (r"\biffo\b", "isso"),
    ]
    for p, s in padroes:
        texto = re.sub(p, s, texto, flags=re.IGNORECASE)
    return texto

def _corrigir_artigos_colados(texto):
    texto = re.sub(r"\banão\b", "a náo", texto)
    texto = re.sub(r"\boleme\b", "o leme", texto)
    texto = re.sub(r"\bavéla\b", "a véla", texto)
    return texto

def _remover_cabecalhos(texto):
    texto = re.sub(r"\n[A-ZÁÉÍÓÚÀÂÊÔÃÕÜÇ][A-ZÁÉÍÓÚÀÂÊÔÃÕÜÇ\s\.\,]+\s+[IVX]+\.\s+\d+\s*\n", "\n", texto)
    return texto

def selecionar_perfil(ano):
    """Seleciona perfil ortografico pelo ano do documento."""
    try:
        return "pre1911" if int(ano) < 1911 else "pos1911"
    except (ValueError, TypeError):
        return "pre1911"

def jpg_para_pdf(jpg_path, output_dir):
    print("ERRO: apenas arquivos PDF são aceitos.")
    print("  Converta seus JPGs para PDF antes de usar o pipeline.")
    print("  Mac: arraste as imagens para o Preview e exporte como PDF.")
    print("  Linux: img2pdf *.jpg -o documento.pdf")
    import sys; sys.exit(1)

def extrair_payloads(pdf_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    # Surya OCR — pula se results.json ja existe
    surya_out = os.path.join(output_dir, "surya")
    nome_base_check = os.path.splitext(os.path.basename(pdf_path))[0]
    results_check = os.path.join(surya_out, nome_base_check, "results.json")
    # busca em subpastas tambem
    if not os.path.exists(results_check):
        for root, dirs, files in os.walk(surya_out):
            for f in files:
                if f == "results.json":
                    results_check = os.path.join(root, f)
                    break
    if os.path.exists(results_check):
        print("  Surya ja processado, usando results.json existente.")
    else:
        print("  Rodando Surya OCR...")
        ret = os.system(f'surya_ocr "{pdf_path}" --output_dir "{surya_out}"')
        if ret != 0:
            print("  ERRO: Surya falhou.")
            sys.exit(1)

    # localiza results.json
    nome_base = os.path.splitext(os.path.basename(pdf_path))[0]
    results_path = os.path.join(surya_out, nome_base, "results.json")
    if not os.path.exists(results_path):
        # tenta encontrar em qualquer subpasta
        for root, dirs, files in os.walk(surya_out):
            for f in files:
                if f == "results.json":
                    results_path = os.path.join(root, f)
                    break

    with open(results_path) as f:
        data = json.load(f)
    pages_surya = list(data.values())[0]

    # OCR embutido via pymupdf
    doc = fitz.open(pdf_path)
    payloads = []
    for i, (page_surya, page_fitz) in enumerate(zip(pages_surya, doc)):
        blocos = []
        for b in page_surya["blocks"]:
            if b["label"] in ("Text", "SectionHeader", "Footnote", "ListGroup"):
                texto = re.sub(r"<[^>]+>", " ", b["html"])
                texto = re.sub(r"\s+", " ", texto).strip()
                if texto:
                    blocos.append({"label": b["label"], "texto": texto})

        payload = {
            "pagina": i + 1,
            "surya_blocos": blocos,
            "embutido_raw": page_fitz.get_text("text").strip()
        }
        path = os.path.join(output_dir, f"pagina_{i+1}_payload.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        payloads.append(path)
        print(f"  Página {i+1}: {len(blocos)} blocos Surya extraídos")

    return payloads

def pre_processar_blocos(blocos, perfil):
    if perfil != "pre1911":
        return blocos
    resultado = []
    for b in blocos:
        b2 = dict(b)
        b2["texto"] = _corrigir_s_longo(b["texto"])
        resultado.append(b2)
    return resultado

def surya_para_texto(blocos):
    return "\n\n".join(
        "[" + b["label"] + "] " + b["texto"]
        for b in blocos
    )

def pos_correcao(texto, perfil, tipo=None):
    if perfil == "pre1911":
        texto = _corrigir_s_longo(texto)
        texto = _corrigir_artigos_colados(texto)
        texto = _remover_cabecalhos(texto)
        for padrao, substituto in CIRCUNFLEXOS:
            texto = re.sub(padrao, substituto, texto)
    if tipo == "juridico":
        texto = _limpar_juridico(texto)
    return texto

def corrigir_pagina(client, payload_path, perfil, progresso, progresso_path, tipo=None):
    with open(payload_path, encoding="utf-8") as f:
        payload = json.load(f)

    n = payload["pagina"]
    chave = f"pagina_{n}"

    if chave in progresso:
        print(f"  Página {n}: já processada (checkpoint), pulando.")
        return progresso[chave]["texto"]

    blocos_proc    = pre_processar_blocos(payload["surya_blocos"], perfil)
    surya_texto    = surya_para_texto(blocos_proc)
    embutido_texto = payload["embutido_raw"]
    prompt_template = PROMPTS[perfil]
    prompt = prompt_template.format(surya=surya_texto, embutido=embutido_texto)

    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}]
            )
            resultado = resp.content[0].text
            tok_in    = resp.usage.input_tokens
            tok_out   = resp.usage.output_tokens
            custo_usd = (tok_in * 1.00 + tok_out * 5.00) / 1_000_000
            print(f"  Página {n}: {tok_in}in/{tok_out}out tokens | ${custo_usd:.5f}")
            break
        except Exception as e:
            print(f"  Tentativa {tentativa}/{MAX_RETRIES} falhou: {e}")
            if tentativa < MAX_RETRIES:
                time.sleep(5 * tentativa)
            else:
                raise

    resultado = pos_correcao(resultado, perfil, tipo=tipo)

    progresso[chave] = {
        "tokens_in":  tok_in,
        "tokens_out": tok_out,
        "custo_usd":  custo_usd,
        "texto":      resultado
    }
    with open(progresso_path, "w") as f:
        json.dump(progresso, f, ensure_ascii=False, indent=2)

    time.sleep(0.5)
    return resultado

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline OCR para documentos históricos em português"
    )
    parser.add_argument("arquivo", help="PDF ou JPG de entrada")
    parser.add_argument(
        "--tipo",
        choices=["livro", "juridico", "periodico", "administrativo"],
        default=None,
        help="Tipo do documento (define tratamento de elementos estruturais)"
    )
    parser.add_argument(
        "--ano",
        default=None,
        help="Ano aproximado do documento, ex: 1879, 1978 (define perfil ortografico)"
    )
    args = parser.parse_args()

    # valida entrada
    if not os.path.exists(args.arquivo):
        print(f"ERRO: arquivo não encontrado: {args.arquivo}")
        sys.exit(1)

    # pergunta século se não informado
    ano = args.ano if hasattr(args, "ano") else None
    if not ano:
        print("\nQual o ano aproximado do documento? (ex: 1750, 1889, 1978)")
        ano = input("Ano: ").strip()
        if not ano.isdigit():
            print("Ano inválido. Use apenas números, ex: 1902")
            sys.exit(1)

    tipo = args.tipo if hasattr(args, "tipo") and args.tipo else None
    if not tipo:
        print("\nQual o tipo do documento?")
        print("  [1] Livro ou texto literário")
        print("  [2] Documento jurídico (processo, acórdão, lei, decreto)")
        print("  [3] Periódico (jornal, revista)")
        print("  [4] Documento administrativo (ofício, relatório, carta)")
        opcao_tipo = input("Opção: ").strip()
        mapa_tipo = {"1":"livro","2":"juridico","3":"periodico","4":"administrativo"}
        tipo = mapa_tipo.get(opcao_tipo, "livro")
        args.tipo = tipo
    print(f"Tipo: {tipo}")

    perfil = selecionar_perfil(ano)
    print(f"\nDocumento: {args.arquivo}")
    print(f"Século: {ano} | Perfil: {perfil}")

    # prepara diretórios de saída
    nome_base  = os.path.splitext(os.path.basename(args.arquivo))[0]
    output_dir = os.path.join("output", nome_base)
    os.makedirs(output_dir, exist_ok=True)

    # converte JPG para PDF se necessário
    arquivo = args.arquivo
    if arquivo.lower().endswith((".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp")):
        arquivo = jpg_para_pdf(arquivo, output_dir)

    # extrai payloads
    print("\n[1/3] Extraindo OCR...")
    payloads = extrair_payloads(arquivo, output_dir)

    # verifica API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("\nERRO: defina ANTHROPIC_API_KEY antes de rodar.")
        print("  export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # carrega progresso
    progresso_path = os.path.join(output_dir, "progresso.json")
    if os.path.exists(progresso_path):
        with open(progresso_path) as f:
            progresso = json.load(f)
    else:
        progresso = {}

    # corrige páginas
    print(f"\n[2/3] Corrigindo {len(payloads)} páginas com Haiku 4.5...")
    textos = []
    custo_total = 0.0
    for payload_path in payloads:
        texto = corrigir_pagina(client, payload_path, perfil, progresso, progresso_path, tipo=tipo)
        textos.append(texto)
        custo_total = sum(p.get("custo_usd", 0) for p in progresso.values() if isinstance(p, dict))

    # gera saída
    print(f"\n[3/3] Gerando saída...")
    saida_path = os.path.join(output_dir, nome_base + "_transcrito.txt")
    with open(saida_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(textos))

    print(f"\n{'='*50}")
    print(f"Concluído!")
    print(f"Arquivo: {saida_path}")
    print(f"Páginas: {len(textos)}")
    print(f"Custo total: ${custo_total:.5f} = R${custo_total*5.75:.4f}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
