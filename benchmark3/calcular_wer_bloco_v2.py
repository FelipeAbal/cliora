import json, re, sys
import jiwer

def limpar_cabecalhos_conhecidos(texto, obra):
    # Ajuste pontual de medicao (Opcao A). Nao substitui a correcao definitiva
    # no pipeline.py (regex _remover_cabecalhos), que segue pendente (ver backlog).
    if obra == "caramuru":
        texto = re.sub(r'POEMA EPICO\.?\s*CANTO\s*I\.?\s*\d*\.?', ' ', texto)
    return texto

def clean_reference(text):
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_hypothesis(text, obra):
    text = limpar_cabecalhos_conhecidos(text, obra)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

if len(sys.argv) != 3:
    print("Uso: python3 calcular_wer_bloco_v2.py <obra> <backend: cpu|vulkan>")
    sys.exit(1)

obra, backend = sys.argv[1], sys.argv[2]
pasta = f"{obra}_{backend}"

with open(f"gabarito_{obra}.txt", encoding="utf-8") as f:
    ref = clean_reference(f.read())

with open(f"output/{pasta}/progresso.json", encoding="utf-8") as f:
    progresso = json.load(f)

textos = [progresso[f"pagina_{i}"]["texto"] for i in range(1, 6)]
hyp = clean_hypothesis(" ".join(textos), obra)

wer = jiwer.wer(ref, hyp)
n_words = len(ref.split())
print(f"{obra} ({backend}): {n_words} palavras (ref) | WER {wer*100:.1f}%")
