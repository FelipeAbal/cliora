import json, re, sys
import jiwer

def clean_reference(text):
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_hypothesis(text):
    text = re.sub(r'\s+', ' ', text).strip()
    return text

if len(sys.argv) != 3:
    print("Uso: python3 calcular_wer_bloco.py <obra> <backend: cpu|vulkan>")
    sys.exit(1)

obra, backend = sys.argv[1], sys.argv[2]
pasta = f"{obra}_{backend}"

with open(f"gabarito_{obra}.txt", encoding="utf-8") as f:
    ref = clean_reference(f.read())

with open(f"output/{pasta}/progresso.json", encoding="utf-8") as f:
    progresso = json.load(f)

textos = [progresso[f"pagina_{i}"]["texto"] for i in range(1, 6)]
hyp = clean_hypothesis(" ".join(textos))

wer = jiwer.wer(ref, hyp)
n_words = len(ref.split())
print(f"{obra} ({backend}): {n_words} palavras (ref) | WER {wer*100:.1f}%")
