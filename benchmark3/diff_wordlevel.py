import re, json, difflib, sys

obra = sys.argv[1] if len(sys.argv) > 1 else "caramuru"
backend = sys.argv[2] if len(sys.argv) > 2 else "cpu"

with open(f'gabarito_{obra}.txt', encoding='utf-8') as f:
    ref = f.read().replace('ſ', 's')
ref = re.sub(r'\s+', ' ', ref).strip()

with open(f'output/{obra}_{backend}/progresso.json', encoding='utf-8') as f:
    p = json.load(f)
textos = [p[f'pagina_{i}']['texto'] for i in range(1, 6)]
hyp = re.sub(r'\s+', ' ', ' '.join(textos)).strip()

ref_w = ref.split()
hyp_w = hyp.split()

sm = difflib.SequenceMatcher(None, ref_w, hyp_w, autojunk=False)
count = 0
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag != 'equal':
        count += 1
        print(f"--- {tag} ---")
        print("REF:", ref_w[i1:i2])
        print("HYP:", hyp_w[j1:j2])
        if count >= 25:
            print("... (truncado, mais diferenças existem)")
            break
