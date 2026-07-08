#!/usr/bin/env python3
import json, os, sys, time, re
import anthropic

API_KEY       = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL         = "claude-haiku-4-5"
PAYLOAD_DIR   = "checkpoints"
OUTPUT_DIR    = "output/corrigido"
PROGRESS_FILE = "checkpoints/haiku_progress.json"
MAX_RETRIES   = 3
PAGINAS       = [1, 2, 3, 4, 5]

PROMPT = """Voce e um assistente especializado em transcricao de documentos historicos em portugues.

Voce recebera dois textos extraidos da mesma pagina de um documento historico digitalizado (seculo XIX, ortografia pre-reforma de 1911):
- SURYA: extraido pelo OCR Surya 2 (melhor leitura de caracteres, mas pode perder trechos ou modernizar a ortografia)
- EMBUTIDO: extraido do OCR original do PDF (qualidade inferior, mas captura o conteudo completo da pagina)

Produza o texto corrigido seguindo RIGOROSAMENTE estas regras:

1. USE o SURYA como base principal.
2. USE o EMBUTIDO apenas para detectar conteudo que o Surya omitiu.
3. CORRIJA erros obvios de reconhecimento de caractere em contexto claro:
   - confusoes h/b (ex: "hem">"bem", "hosso">"nosso", "hom">"bom")
   - confusoes h/n (ex: "hosso">"nosso")
   - confusoes rn/m (ex: "entramem">"entrarem")
   - confusoes f/t, i/a em contexto claro
   - s duplo espurio (ex: "desseje">"deseje")
4. PRESERVE a ortografia historica EXATAMENTE:
   - NAO adicione acentos ausentes: "tambem" permanece "tambem", "ultima" permanece "ultima"
   - NAO remova circunflexos historicos: "for" com circunflexo permanece "for"; "foram" com circunflexo permanece; "stao", "area" com circunflexo permanecem
   - NAO altere grafias historicas: "assi", "stado", "elle", "della", "officio", "Officiaes", "fidalgo", "spaço", "scripto", "specialmente"
   - NAO converta ortografia arcaica para moderna em nenhuma circunstancia
   - Grafias com ff, ss, tt duplos sao ortografia de epoca: "officio", "Officiaes", "attento" - NAO altere
5. Se o EMBUTIDO tiver palavras ausentes no SURYA que facam sentido no contexto, RESTAURE-AS marcando: [RESTAURADO: texto restaurado]
6. Se nao conseguir determinar algo com seguranca, marque: [INCERTO: trecho]
7. NUNCA invente conteudo ausente nos dois textos.
8. Retorne APENAS o texto corrigido, sem explicacoes, cabecalhos, labels nem comentarios.

SURYA:
{surya}

EMBUTIDO:
{embutido}"""

CIRCUNFLEXOS = [
    (r"\bfor\b(?=\s+provido|\s+possivel|\s+necessario|\s+commettido|\s+acordado|\s+vencida|\s+do\s+feito|\s+posta|\s+caso)", "fôr"),
    (r"\bforem\b(?=\s+feriados|\s+presentes|\s+concordes|\s+absentes|\s+em\b|\s+de\b|\s+dous|\s+tres|\s+conformes)", "fôrem"),
]

def pos_correcao(texto):
    for padrao, substituto in CIRCUNFLEXOS:
        texto = re.sub(padrao, substituto, texto)
    return texto

def surya_para_texto(blocos):
    partes = []
    for b in blocos:
        if b["label"] in ("Text", "SectionHeader", "Footnote"):
            partes.append("[" + b["label"] + "] " + b["texto"])
    return "\n\n".join(partes)

def carregar_progresso():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}

def salvar_progresso(p):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)

def chamar_haiku(client, surya_texto, embutido_texto):
    prompt = PROMPT.format(surya=surya_texto, embutido=embutido_texto)
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )
            return resp.content[0].text, resp.usage.input_tokens, resp.usage.output_tokens
        except Exception as e:
            print("  Tentativa " + str(tentativa) + "/" + str(MAX_RETRIES) + " falhou: " + str(e))
            if tentativa < MAX_RETRIES:
                time.sleep(5 * tentativa)
            else:
                raise

if not API_KEY:
    print("ERRO: defina ANTHROPIC_API_KEY antes de rodar.")
    sys.exit(1)

os.makedirs(OUTPUT_DIR, exist_ok=True)
client    = anthropic.Anthropic(api_key=API_KEY)
progresso = carregar_progresso()

custo_total_usd  = 0.0
tokens_in_total  = 0
tokens_out_total = 0

print("Modelo: " + MODEL)
print("Paginas: " + str(PAGINAS))
print()

for n in PAGINAS:
    chave = "pagina_" + str(n)
    if chave in progresso:
        print("Pagina " + str(n) + ": ja processada, pulando.")
        custo_total_usd += progresso[chave].get("custo_usd", 0)
        continue

    payload_path = os.path.join(PAYLOAD_DIR, "pagina_" + str(n) + "_payload.json")
    if not os.path.exists(payload_path):
        print("Pagina " + str(n) + ": payload nao encontrado, pulando.")
        continue

    with open(payload_path, encoding="utf-8") as f:
        payload = json.load(f)

    surya_texto    = surya_para_texto(payload["surya_blocos"])
    embutido_texto = payload["embutido_raw"]
    print("Pagina " + str(n) + ": processando...")

    try:
        resultado, tok_in, tok_out = chamar_haiku(client, surya_texto, embutido_texto)
    except Exception as e:
        print("  FALHOU: " + str(e))
        salvar_progresso(progresso)
        sys.exit(1)

    resultado = pos_correcao(resultado)

    out_path = os.path.join(OUTPUT_DIR, "pagina_" + str(n) + "_haiku.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(resultado)

    custo_usd        = (tok_in * 1.00 + tok_out * 5.00) / 1_000_000
    custo_total_usd += custo_usd
    tokens_in_total += tok_in
    tokens_out_total += tok_out

    progresso[chave] = {
        "tokens_in":  tok_in,
        "tokens_out": tok_out,
        "custo_usd":  custo_usd,
        "arquivo":    out_path
    }
    salvar_progresso(progresso)
    print("  OK " + str(tok_in) + "in/" + str(tok_out) + "out | $" + f"{custo_usd:.5f}" + " | " + out_path)
    time.sleep(0.5)

print()
print("=" * 50)
print("TOTAL tokens entrada: " + str(tokens_in_total))
print("TOTAL tokens saida:   " + str(tokens_out_total))
print("CUSTO TOTAL:  $" + f"{custo_total_usd:.5f}" + " = R$" + f"{custo_total_usd*5.75:.4f}")
print("Projecao 500 pag: R$" + f"{custo_total_usd*5.75*100:.2f}")
