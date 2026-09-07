import json, re, glob, sys
import jiwer

PAGE_NUMBERS = [11, 25, 241, 373, 412]

def clean_reference(text):
    text = re.sub(r'<noinclude>.*?</noinclude>', '', text, flags=re.DOTALL)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r'\{\{.*?\}\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_hypothesis(html_blocks):
    text = ' '.join(html_blocks)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

matches = glob.glob('output/benchmark/**/results.json', recursive=True)
if not matches:
    print("Não achei results.json em output/benchmark, confere o caminho.")
    sys.exit(1)

with open(matches[0]) as f:
    data = json.load(f)
pages = list(data.values())[0]

total_ref_words = 0
total_errors = 0.0

print(f"{'Página':<10}{'Palavras (ref)':<16}{'WER':<10}")
for i, pagenum in enumerate(PAGE_NUMBERS):
    with open(f'gabarito_{pagenum}.txt', encoding='utf-8') as f:
        ref = clean_reference(f.read())
    blocks = [b['html'] for b in pages[i]['blocks']]
    hyp = clean_hypothesis(blocks)
    wer = jiwer.wer(ref, hyp)
    n_words = len(ref.split())
    total_ref_words += n_words
    total_errors += wer * n_words
    print(f"{pagenum:<10}{n_words:<16}{wer*100:.1f}%")

print(f"\nWER agregado (5 páginas): {total_errors/total_ref_words*100:.1f}%")
