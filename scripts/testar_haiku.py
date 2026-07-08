#!/usr/bin/env python3
import json, os, sys, time
import anthropic

API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL      = "claude-haiku-4-5"
PAYLOAD    = "checkpoints/pagina_1_payload.json"
OUTPUT     = "output/corrigido/pagina_1_haiku.txt"

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
   - Grafias com ff, ss, tt duplos sao ortografia de epoca: "officio", "Officiaes", "attento" — NAO altere
5. Se o EMBUTIDO tiver palavras ausentes no SURYA que facam sentido no contexto, RESTAURE-AS marcando: [RESTAURADO: texto restaurado]
6. Se nao conseguir determinar algo com seguranca, marque: [INCERTO: trecho]
7. NUNCA invente conteudo ausente nos dois textos.
8. Retorne APENAS o texto corrigido, sem explicacoes, cabecalhos, labels nem comentarios.

SURYA:
{surya}

EMBUTIDO:
{embutido}"""

def surya_para_texto(blocos):
    partes = []
    for b in blocos:
        if b["label"] in ("Text", "SectionHeader", "Footnote"):
            partes.append(f"[{b['label']}] {b['texto']}")
    return "\n\n".join(partes)

if not API_KEY:
    print("ERRO: defina ANTHROPIC_API_KEY antes de rodar.")
    sys.exit(1)

with open(PAYLOAD, encoding="utf-8") as f:
    payload = json.load(f)

surya_texto    = surya_para_texto(payload["surya_blocos"])
embutido_texto = payload["embutido_raw"]
prompt         = PROMPT.format(surya=surya_texto, embutido=embutido_texto)

print(f"Modelo: {MODEL}")
print(f"Tokens entrada estimados: ~{len(prompt)//4}")

client   = anthropic.Anthropic(api_key=API_KEY)
response = client.messages.create(
    model=MODEL,
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}]
)

resultado = response.content[0].text
tokens_in  = response.usage.input_tokens
tokens_out = response.usage.output_tokens
custo_usd  = (tokens_in * 1.00 + tokens_out * 5.00) / 1_000_000
custo_brl  = custo_usd * 5.75

print(f"Tokens entrada reais: {tokens_in}")
print(f"Tokens saida reais:   {tokens_out}")
print(f"Custo real:           ${custo_usd:.5f} = R${custo_brl:.4f}")

os.makedirs("output/corrigido", exist_ok=True)
with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(resultado)
print(f"Salvo em {OUTPUT}")
