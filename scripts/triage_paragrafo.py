import json, re
import fitz

PDF_PATH     = "input/Teste.pdf"
RESULTS_PATH = "output/surya/Teste/results.json"
THRESHOLD_LOSS = 0.05  # 5% no nivel de paragrao

def real_words(text):
    return re.findall(r'[a-záéíóúàâêôãõüç]{3,}', text.lower())

doc = fitz.open(PDF_PATH)
embedded_per_page = [page.get_text("blocks") for page in doc]

with open(RESULTS_PATH) as f:
    pages_surya = list(json.load(f).values())[0]

print(f"\n{'Pag':<5} {'Bloco':<6} {'Embutido':>10} {'Surya':>8} {'Delta':>8}  {'Status'}")
print("-" * 65)

for i, (emb_blocks, surya_page) in enumerate(zip(embedded_per_page, pages_surya)):
    emb_texts = [b[4] for b in emb_blocks if isinstance(b[4], str) and len(b[4].strip()) > 20]
    surya_texts = [
        re.sub(r'<[^>]+>', ' ', b['html'])
        for b in surya_page['blocks']
        if b['label'] in ('Text', 'Footnote') and len(b['html']) > 40
    ]
    n = min(len(emb_texts), len(surya_texts))
    for j in range(n):
        emb_w = real_words(emb_texts[j])
        sur_w = real_words(surya_texts[j])
        n_emb, n_sur = len(emb_w), len(sur_w)
        if n_emb < 5:
            continue
        delta = (n_emb - n_sur) / n_emb
        if abs(delta) > THRESHOLD_LOSS:
            status = "⚠ REVISAR"
            print(f"{i+1:<5} {j+1:<6} {n_emb:>10} {n_sur:>8} {delta*100:>+7.1f}%  {status}")
            print(f"       emb: {' '.join(emb_w[:8])}...")
            print(f"       sur: {' '.join(sur_w[:8])}...")

print("\nOK = tudo que não apareceu acima")
