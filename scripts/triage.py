#!/usr/bin/env python3
import json, re
import fitz

PDF_PATH     = "input/Teste.pdf"
RESULTS_PATH = "output/surya/Teste/results.json"
THRESHOLD_LOSS = 0.10
THRESHOLD_GAIN = 0.25

def real_words(text):
    return re.findall(r'[a-záéíóúàâêôãõüç]{3,}', text.lower())

doc = fitz.open(PDF_PATH)
embedded_per_page = [real_words(page.get_text("text")) for page in doc]

with open(RESULTS_PATH) as f:
    pages_surya = list(json.load(f).values())[0]

def surya_words(blocks):
    texts = [re.sub(r'<[^>]+>', ' ', b['html'])
             for b in blocks if b['label'] in ('Text', 'SectionHeader', 'Footnote')]
    return real_words(' '.join(texts))

print(f"\n{'Pag':<5} {'Embutido':>10} {'Surya':>8} {'Delta':>8}  {'Status'}")
print("-" * 55)
for i, (emb, page) in enumerate(zip(embedded_per_page, pages_surya)):
    sur = surya_words(page['blocks'])
    n_emb, n_sur = len(emb), len(sur)
    delta = (n_emb - n_sur) / n_emb if n_emb else 0.0
    if delta > THRESHOLD_LOSS:
        status = "MODO B - Surya perdeu conteudo"
    elif delta < -THRESHOLD_GAIN:
        status = "MODO B - Surya gerou extra"
    else:
        status = "OK"
    print(f"{i+1:<5} {n_emb:>10} {n_sur:>8} {delta*100:>+7.1f}%  {status}")
