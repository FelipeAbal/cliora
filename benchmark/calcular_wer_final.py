import json, re, sys
import jiwer

PAGE_NUMBERS = [11, 25, 241, 373, 412]

def clean_reference(text):
    text = re.sub(r'<noinclude>.*?</noinclude>', '', text, flags=re.DOTALL)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r'\{\{.*?\}\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_hypothesis(text):
    text = re.sub(r'\s+', ' ', text).strip()
    return text

if len(sys.argv) != 2:
    print("Uso: python3 calcular_wer_final.py <nome_pasta_output>")
    sys.exit(1)

pasta = sys.argv[1]
with open(f'output/{pasta}/progresso.json', encoding='utf-8') as f:
    progresso = json.load(f)

total_ref_words = 0
total_errors = 0.0
print(f"{'Página':<10}{'Palavras (ref)':<16}{'WER':<10}")
for i, pagenum in enumerate(PAGE_NUMBERS):
    with open(f'gabarito_{pagenum}.txt', encoding='utf-8') as f:
        ref = clean_reference(f.read())
    hyp = clean_hypothesis(progresso[f'pagina_{i+1}']['texto'])
    wer = jiwer.wer(ref, hyp)
    n_words = len(ref.split())
    total_ref_words += n_words
    total_errors += wer * n_words
    print(f"{pagenum:<10}{n_words:<16}{wer*100:.1f}%")

print(f"\nWER agregado (5 páginas, pós-Haiku, {pasta}): {total_errors/total_ref_words*100:.1f}%")
