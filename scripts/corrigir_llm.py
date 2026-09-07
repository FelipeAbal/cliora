#!/usr/bin/env python3
import json, os, sys, time
from google import genai
from google.genai import types
from google.genai import types

API_KEY        = os.environ.get("GEMINI_API_KEY", "")
MODEL          = "gemini-2.5-flash-lite"
PAYLOAD_DIR    = "checkpoints"
OUTPUT_DIR     = "output/corrigido"
PROGRESS_FILE  = "checkpoints/llm_progress.json"
MAX_RETRIES    = 3
PAGINAS        = [1]

PROMPT = """Voce e um assistente especializado em transcricao de documentos historicos em portugues.

Voce recebera dois textos extraidos da mesma pagina de um documento historico digitalizado (seculo XIX, ortografia pre-reforma de 1911):
- SURYA: extraido pelo OCR Surya 2 (melhor leitura de caracteres, mas pode perder trechos ou modernizar a ortografia)
- EMBUTIDO: extraido do OCR original do PDF (qualidade inferior, mas captura o conteudo completo da pagina)

Produza o texto corrigido seguindo RIGOROSAMENTE estas regras:

1. USE o SURYA como base principal.
2. USE o EMBUTIDO apenas para detectar conteudo que o Surya omitiu.
3. CORRIJA erros obvios de reconhecimento de caractere em contexto claro:
   confusoes h/b (ex: "hem">"bem", "hosso">"nosso"), h/n, rn/m, f/t, i/a.
4. PRESERVE a ortografia historica EXATAMENTE:
   - NAO adicione acentos ausentes ("tambem" permanece "tambem", nao "tambem")
   - NAO remova circunflexos historicos ("for" com circunflexo permanece "for"; "stao", "area" com circunflexo)
   - NAO altere grafias historicas: "assi", "stado", "elle", "della", "officio", "Officiaes", "fidalgo"
   - NAO converta ortografia arcaica para moderna em nenhuma circunstancia
5. Se o EMBUTIDO tiver palavras ausentes no SURYA que facam sentido no contexto, RESTAURE-AS marcando: [RESTAURADO: texto restaurado]
6. Se nao conseguir determinar algo com seguranca, marque: [INCERTO: trecho]
7. NUNCA invente conteudo ausente nos dois textos.
8. Retorne APENAS o texto corrigido, sem explicacoes nem comentarios.

SURYA:
{surya}

EMBUTIDO:
{embutido}"""

def carregar_progresso():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}

def salvar_progresso(progresso):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progresso, f, ensure_ascii=False, indent=2)

def surya_para_texto(blocos):
    partes = []
    for b in blocos:
        if b["label"] in ("Text", "SectionHeader", "Footnote"):
            partes.append(f"[{b['label']}] {b['texto']}")
    return "\n\n".join(partes)

def chamar_gemini(client, surya_texto, embutido_texto):
    prompt = PROMPT.format(surya=surya_texto, embutido=embutido_texto)
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt
            )
            return response.text
        except Exception as e:
            print(f"  Tentativa {tentativa}/{MAX_RETRIES} falhou: {e}")
            if tentativa < MAX_RETRIES:
                time.sleep(5 * tentativa)
            else:
                raise

if not API_KEY:
    print("ERRO: defina GEMINI_API_KEY antes de rodar.")
    sys.exit(1)

os.makedirs(OUTPUT_DIR, exist_ok=True)
client = genai.Client(api_key=API_KEY)
progresso = carregar_progresso()

print(f"Modelo: {MODEL}")
print(f"Paginas a processar: {PAGINAS}\n")

for n in PAGINAS:
    chave = f"pagina_{n}"
    if chave in progresso:
        print(f"Pagina {n}: ja processada (checkpoint), pulando.")
        continue

    payload_path = os.path.join(PAYLOAD_DIR, f"pagina_{n}_payload.json")
    if not os.path.exists(payload_path):
        print(f"Pagina {n}: payload nao encontrado, pulando.")
        continue

    with open(payload_path, encoding="utf-8") as f:
        payload = json.load(f)

    surya_texto    = surya_para_texto(payload["surya_blocos"])
    embutido_texto = payload["embutido_raw"]
    n_tok_est      = (len(surya_texto) + len(embutido_texto)) // 4
    print(f"Pagina {n}: ~{n_tok_est} tokens entrada estimados...")

    try:
        resultado = chamar_gemini(client, surya_texto, embutido_texto)
    except Exception as e:
        print(f"  FALHOU: {e}")
        salvar_progresso(progresso)
        sys.exit(1)

    out_path = os.path.join(OUTPUT_DIR, f"pagina_{n}_corrigida.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(resultado)

    progresso[chave] = {"tokens_entrada_est": n_tok_est, "chars_saida": len(resultado), "arquivo": out_path}
    salvar_progresso(progresso)
    print(f"  OK Salvo em {out_path}")
    time.sleep(1)

print("\nConcluido.")
